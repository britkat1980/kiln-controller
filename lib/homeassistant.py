'''home assistant integration over mqtt.

publishes the oven state as one topic per value under <mqtt_kiln_name>/,
publishes home assistant mqtt discovery configs so the kiln shows up as
a device with sensors, buttons and a profile select, and listens on
<mqtt_kiln_name>/control/# for commands from those buttons/select.

nothing here may block heater control: the paho client runs its own
network thread (connect_async + loop_start), publishes just queue, and
every failure is logged and swallowed.
'''
import datetime
import json
import logging
import time

import config

log = logging.getLogger(__name__)

# commands accepted on <kiln>/control/<name>
COMMANDS = {
    'Pause_Program': 'pause',
    'Resume_Program': 'resume',
    'Stop_Program': 'stop',
    'Restart_Controller': 'restart',
    'profiles': 'run',
}

# the select's "nothing chosen" option. choosing it does nothing.
NO_PROFILE = 'None'

# key -> (component, kind, friendly name, is pidstat, icon)
# unique_id is <kiln>_<friendly name> when a friendly name is given,
# else <kiln>_<key>. never change these: home assistant keys entities
# (and their history) on unique_id.
ENTITIES = {
    'cost': ('sensor', 'money', '', False, 'mdi:currency-gbp'),
    'runtime': ('sensor', '', 'Program Running Time', False, 'mdi:timer-outline'),
    'endtime': ('sensor', '', 'Program End Time', False, 'mdi:timer-outline'),
    'progress': ('sensor', 'percent', 'Progress', False, 'mdi:timer-outline'),
    'temperature': ('sensor', 'temperature', '', False, 'mdi:thermometer'),
    'temperature_raw': ('sensor', 'temperature', 'Temperature Raw', False, 'mdi:thermometer-lines'),
    'target': ('sensor', 'temperature', '', False, 'mdi:thermometer-check'),
    'state': ('sensor', '', '', False, 'mdi:progress-clock'),
    'heat': ('binary_sensor', '', '', False, 'mdi:fire'),
    'heat_rate': ('sensor', '', '', False, 'mdi:fire-circle'),
    'totaltime': ('sensor', '', 'Program Duration', False, 'mdi:timer-outline'),
    'catching_up': ('binary_sensor', '', '', False, 'mdi:run-fast'),
    'name': ('sensor', '', '', False, ''),
    'profiles': ('select', '', '', False, ''),
    'Resume_Program': ('button', '', '', False, ''),
    'Pause_Program': ('button', '', '', False, ''),
    'Stop_Program': ('button', '', '', False, ''),
    'Restart_Controller': ('button', '', '', False, ''),
    # pidstats
    'time': ('sensor', 'timestamp', 'PID Time', True, 'mdi:clock-outline'),
    'timedelta': ('sensor', '', 'PID Time Delta', True, 'mdi:timer-sand'),
    'setpoint': ('sensor', '', 'PID Setpoint', True, 'mdi:thermometer-check'),
    'ispoint': ('sensor', '', '', True, 'mdi:thermometer'),
    'err': ('sensor', '', '', True, 'mdi:alert-circle-outline'),
    'errDelta': ('sensor', '', '', True, 'mdi:delta'),
    'p': ('sensor', '', '', True, 'mdi:alpha-p-circle-outline'),
    'i': ('sensor', '', '', True, 'mdi:alpha-i-circle-outline'),
    'd': ('sensor', '', '', True, 'mdi:alpha-d-circle-outline'),
    'kp': ('sensor', '', '', True, 'mdi:alpha-p-box-outline'),
    'ki': ('sensor', '', '', True, 'mdi:alpha-i-box-outline'),
    'kd': ('sensor', '', '', True, 'mdi:alpha-d-box-outline'),
    'pid': ('sensor', '', 'Power Output', True, ''),
    'out': ('sensor', '', 'PID Out', True, 'mdi:chart-bell-curve'),
}

# pidstats keys whose topic name differs from the pid's own key
PIDSTAT_TOPICS = {'timeDelta': 'timedelta'}

# discovery topics are <prefix>/<component>/<NODE_ID>/<key>/config
NODE_ID = 'kiln_controller'


def enabled():
    return bool(getattr(config, 'mqtt_enable', False)) and \
        bool(getattr(config, 'mqtt_ha_discovery', False))


def format_duration(seconds):
    '''seconds -> H:MM:SS'''
    return str(datetime.timedelta(seconds=int(seconds or 0)))


class HomeAssistant(object):
    '''on_command(command, argument) is called on the mqtt network
    thread for each valid command and returns (ok, message).
    profile_names() returns the current list of profile names.'''

    def __init__(self, on_command, profile_names, client=None, clock=time.time):
        self.on_command = on_command
        self.profile_names = profile_names
        self.clock = clock
        self.base = str(getattr(config, 'mqtt_kiln_name', None) or 'kiln').replace(' ', '_')
        self.prefix = getattr(config, 'mqtt_ha_prefix', 'homeassistant')
        self.interval = getattr(config, 'mqtt_ha_interval', 15)
        self.currency = getattr(config, 'mqtt_ha_currency', 'GBP')
        self.last_publish = None
        self.last_key = None
        self.published_profiles = None
        self.client = client
        if self.client is None:
            self.client = self._make_client()

    # ------------------------------------------------------------------
    # connection

    def _make_client(self):
        try:
            import paho.mqtt.client as mqtt
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                 client_id='%s_kiln_controller' % self.base)
            user = getattr(config, 'mqtt_user', None)
            if user is not None:
                client.username_pw_set(user, getattr(config, 'mqtt_pass', None))
            client.will_set(self.topic('status'), 'offline', retain=True)
            client.reconnect_delay_set(min_delay=1, max_delay=60)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.connect_async(getattr(config, 'mqtt_host', 'localhost'),
                                 int(getattr(config, 'mqtt_port', 1883)))
            client.loop_start()
            return client
        except Exception:
            log.exception("home assistant mqtt client setup failed")
            return None

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, 'is_failure', bool(reason_code)):
            log.error("home assistant mqtt connect failed: %s" % reason_code)
            return
        log.info("home assistant mqtt connected")
        client.subscribe(self.topic('control/#'))
        # home assistant announces itself here when it (re)starts
        client.subscribe('%s/status' % self.prefix)
        self.publish_discovery()
        self._send('status', 'online')
        # force a full state publish on the next oven cycle
        self.last_publish = None

    def _on_message(self, client, userdata, message):
        try:
            payload = message.payload.decode('utf-8').strip()
            if message.topic == '%s/status' % self.prefix:
                if payload == 'online':
                    self.publish_discovery()
                    self._send('status', 'online')
                    self.last_publish = None
                return
            # a retained command would replay on every reconnect, and
            # could start a firing nobody asked for. only act on live ones.
            if message.retain:
                log.warning("ignoring retained mqtt command on %s" % message.topic)
                return
            self.handle_command(message.topic.split('/')[-1], payload)
        except Exception:
            log.exception("home assistant mqtt message failed")

    def handle_command(self, name, payload):
        command = COMMANDS.get(name)
        if command is None:
            log.warning("ignoring unknown mqtt command %s" % name)
            return
        argument = None
        if command == 'run':
            if not payload or payload == NO_PROFILE:
                return
            argument = payload
        log.info("mqtt command %s %s" % (command, argument or ''))
        ok, message = self.on_command(command, argument)
        if not ok:
            log.warning("mqtt command %s failed: %s" % (command, message))
        # put the select back to the running profile (or None)
        self.last_publish = None

    # ------------------------------------------------------------------
    # publishing

    def topic(self, key):
        return '%s/%s' % (self.base, key)

    def _send(self, key, value, retain=True):
        if self.client is None:
            return
        try:
            self.client.publish(self.topic(key), value, retain=retain)
        except Exception:
            log.exception("home assistant mqtt publish failed")

    def discovery_configs(self):
        '''(topic, payload) for every entity'''
        device = {'identifiers': [self.base], 'name': self.base,
                  'manufacturer': 'kiln-controller', 'model': self.base}
        unit = '°F' if config.temp_scale.lower() == 'f' else '°C'
        out = []
        for key, (component, kind, friendly, is_pid, icon) in ENTITIES.items():
            ident = friendly.replace(' ', '_') if friendly else key
            cfg = {
                'name': friendly or key.replace('_', ' '),
                'unique_id': '%s_%s' % (self.base, ident),
                'default_entity_id': '%s.%s_%s' % (component, self.base, ident),
                'stat_t': self.topic(('pidstats/' if is_pid else '') + key),
                'avty_t': self.topic('status'),
                'pl_avail': 'online',
                'pl_not_avail': 'offline',
                'device': device,
            }
            if icon:
                cfg['icon'] = icon
            if component == 'select':
                cfg['stat_t'] = self.topic('profile')
                cfg['options'] = list(self.profile_names()) + [NO_PROFILE]
                cfg['command_topic'] = self.topic('control/' + key)
            elif component == 'button':
                cfg['command_topic'] = self.topic('control/' + key)
            elif component == 'binary_sensor':
                cfg['payload_on'] = '1'
                cfg['payload_off'] = '0'
            elif kind == 'temperature':
                cfg['unit_of_meas'] = unit
                cfg['device_class'] = 'temperature'
                cfg['state_class'] = 'measurement'
            elif kind == 'money':
                cfg['unit_of_meas'] = self.currency
                cfg['device_class'] = 'monetary'
            elif kind == 'timestamp':
                cfg['device_class'] = 'timestamp'
            elif kind == 'percent':
                cfg['unit_of_meas'] = '%'
            topic = '%s/%s/%s/%s/config' % (self.prefix, component, NODE_ID, key)
            out.append((topic, json.dumps(cfg)))
        return out

    def publish_discovery(self):
        if self.client is None:
            return
        try:
            self.published_profiles = list(self.profile_names())
            for topic, payload in self.discovery_configs():
                self.client.publish(topic, payload, retain=True)
        except Exception:
            log.exception("home assistant discovery publish failed")

    def state_messages(self, state, now=None):
        '''(key, value) for every topic in an oven state broadcast'''
        now = now or datetime.datetime.now()
        msgs = []
        for key in ('temperature', 'temperature_raw', 'target', 'heat_rate', 'cost'):
            if state.get(key) is not None:
                msgs.append((key, round(state[key], 2)))
        msgs.append(('state', state.get('state')))
        msgs.append(('heat', '1' if (state.get('heat') or 0) > 0 else '0'))
        msgs.append(('catching_up', '1' if state.get('catching_up') else '0'))
        msgs.append(('runtime', format_duration(state.get('runtime'))))
        msgs.append(('totaltime', format_duration(state.get('totaltime'))))
        msgs.append(('profile', state.get('profile') or NO_PROFILE))
        msgs.append(('name', self.base))

        running = state.get('state') in ('RUNNING', 'PAUSED')
        totaltime = state.get('totaltime') or 0
        runtime = state.get('runtime') or 0
        if running and totaltime > 0:
            left = max(totaltime - runtime, 0)
            msgs.append(('endtime', (now + datetime.timedelta(seconds=left)).strftime('%H:%M:%S')))
            msgs.append(('progress', round(min(runtime / totaltime, 1) * 100, 2)))
        else:
            msgs.append(('endtime', '-'))
            msgs.append(('progress', 0))

        for key, value in (state.get('pidstats') or {}).items():
            key = PIDSTAT_TOPICS.get(key, key)
            if key not in ENTITIES:
                continue
            if key == 'time':
                value = datetime.datetime.fromtimestamp(value).astimezone().isoformat()
            elif isinstance(value, (int, float)):
                value = round(value, 2)
            msgs.append(('pidstats/' + key, value))
        return msgs

    def publish(self, state):
        '''called by the oven watcher every duty cycle. publishes every
        mqtt_ha_interval seconds, or straight away when the oven state
        or profile changes.'''
        if self.client is None:
            return
        now = self.clock()
        key = (state.get('state'), state.get('profile'))
        if self.last_publish is not None and key == self.last_key and \
                now - self.last_publish < self.interval:
            return
        self.last_publish = now
        self.last_key = key
        try:
            if list(self.profile_names()) != self.published_profiles:
                self.publish_discovery()
        except Exception:
            log.exception("home assistant profile list check failed")
        for topic, value in self.state_messages(state):
            self._send(topic, value)
        self._send('status', 'online')
