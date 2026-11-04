import datetime
import json
import types

import pytest

import config
import homeassistant
from homeassistant import HomeAssistant


class FakeClient:
    def __init__(self):
        self.published = []
        self.subscribed = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def topics(self):
        return {t: p for (t, p, _) in self.published}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def ha(monkeypatch):
    monkeypatch.setattr(config, 'mqtt_kiln_name', 'Kittec_CB40', raising=False)
    monkeypatch.setattr(config, 'mqtt_ha_interval', 15, raising=False)
    monkeypatch.setattr(config, 'mqtt_ha_currency', 'GBP', raising=False)
    monkeypatch.setattr(config, 'temp_scale', 'c')
    commands = []
    profiles = ['bisque', 'glaze']

    def on_command(command, argument):
        commands.append((command, argument))
        return True, None

    h = HomeAssistant(on_command, lambda: list(profiles),
                      client=FakeClient(), clock=Clock())
    h.commands = commands
    h.profiles = profiles
    return h


def state(**kw):
    s = {
        'temperature': 512.345, 'temperature_raw': 500.0, 'target': 520.0,
        'state': 'RUNNING', 'heat': 0.4, 'heat_rate': 100.123, 'cost': 1.234,
        'runtime': 3600, 'totaltime': 7200, 'profile': 'bisque',
        'catching_up': False,
        'pidstats': {'time': 1700000000.5, 'timeDelta': 2.0, 'out': 0.4567},
    }
    s.update(kw)
    return s


def test_enabled_needs_both_flags(monkeypatch):
    monkeypatch.setattr(config, 'mqtt_enable', True, raising=False)
    monkeypatch.setattr(config, 'mqtt_ha_discovery', False, raising=False)
    assert not homeassistant.enabled()
    monkeypatch.setattr(config, 'mqtt_ha_discovery', True, raising=False)
    assert homeassistant.enabled()
    monkeypatch.setattr(config, 'mqtt_enable', False, raising=False)
    assert not homeassistant.enabled()


def test_discovery_keeps_fork_ids_and_topics(ha):
    configs = dict(ha.discovery_configs())
    temp = json.loads(configs['homeassistant/sensor/kiln_controller/temperature/config'])
    assert temp['unique_id'] == 'Kittec_CB40_temperature'
    assert temp['stat_t'] == 'Kittec_CB40/temperature'
    assert temp['avty_t'] == 'Kittec_CB40/status'
    assert temp['device_class'] == 'temperature'
    assert temp['unit_of_meas'] == '°C'
    runtime = json.loads(configs['homeassistant/sensor/kiln_controller/runtime/config'])
    assert runtime['unique_id'] == 'Kittec_CB40_Program_Running_Time'
    delta = json.loads(configs['homeassistant/sensor/kiln_controller/timedelta/config'])
    assert delta['stat_t'] == 'Kittec_CB40/pidstats/timedelta'


def test_discovery_unique_ids_are_unique(ha):
    ids = [json.loads(p)['unique_id'] for _, p in ha.discovery_configs()]
    assert len(ids) == len(set(ids))


def test_discovery_device_classes_are_valid(ha):
    configs = dict(ha.discovery_configs())
    cost = json.loads(configs['homeassistant/sensor/kiln_controller/cost/config'])
    assert cost['device_class'] == 'monetary'
    assert cost['unit_of_meas'] == 'GBP'
    for _, payload in ha.discovery_configs():
        dc = json.loads(payload).get('device_class')
        assert dc is None or dc == dc.lower()


def test_fahrenheit_unit(ha, monkeypatch):
    monkeypatch.setattr(config, 'temp_scale', 'f')
    configs = dict(ha.discovery_configs())
    temp = json.loads(configs['homeassistant/sensor/kiln_controller/target/config'])
    assert temp['unit_of_meas'] == '°F'


def test_select_lists_profiles_and_none(ha):
    configs = dict(ha.discovery_configs())
    sel = json.loads(configs['homeassistant/select/kiln_controller/profiles/config'])
    assert sel['options'] == ['bisque', 'glaze', 'None']
    assert sel['command_topic'] == 'Kittec_CB40/control/profiles'
    assert sel['stat_t'] == 'Kittec_CB40/profile'


def test_state_messages(ha):
    now = datetime.datetime(2026, 1, 1, 12, 0, 0)
    msgs = dict(ha.state_messages(state(), now=now))
    assert msgs['temperature'] == 512.35
    assert msgs['heat'] == '1'
    assert msgs['catching_up'] == '0'
    assert msgs['runtime'] == '1:00:00'
    assert msgs['totaltime'] == '2:00:00'
    assert msgs['endtime'] == '13:00:00'
    assert msgs['progress'] == 50.0
    assert msgs['profile'] == 'bisque'
    assert msgs['pidstats/timedelta'] == 2.0
    assert msgs['pidstats/out'] == 0.46
    # timestamp sensors need a timezone
    assert datetime.datetime.fromisoformat(msgs['pidstats/time']).tzinfo is not None


def test_idle_state_messages(ha):
    msgs = dict(ha.state_messages(state(state='IDLE', profile=None, heat=0,
                                        runtime=0, totaltime=0, pidstats={})))
    assert msgs['profile'] == 'None'
    assert msgs['heat'] == '0'
    assert msgs['endtime'] == '-'
    assert msgs['progress'] == 0


def test_publish_is_rate_limited(ha):
    ha.publish(state())
    first = len(ha.client.published)
    assert first > 0
    assert ha.client.topics()['Kittec_CB40/status'] == 'online'
    ha.clock.now += 5
    ha.publish(state())
    assert len(ha.client.published) == first
    ha.clock.now += 11
    ha.publish(state())
    assert len(ha.client.published) > first


def test_publish_immediately_on_state_change(ha):
    ha.publish(state())
    first = len(ha.client.published)
    ha.clock.now += 1
    ha.publish(state(state='IDLE'))
    assert len(ha.client.published) > first


def test_profile_change_republishes_discovery(ha):
    ha.publish(state())
    ha.profiles.append('new-one')
    ha.client.published.clear()
    ha.clock.now += 20
    ha.publish(state())
    sel = json.loads(ha.client.topics()['homeassistant/select/kiln_controller/profiles/config'])
    assert 'new-one' in sel['options']


def message(topic, payload, retain=False):
    return types.SimpleNamespace(topic=topic, payload=payload.encode(), retain=retain)


@pytest.mark.parametrize('name,expected', [
    ('Pause_Program', ('pause', None)),
    ('Resume_Program', ('resume', None)),
    ('Stop_Program', ('stop', None)),
    ('Restart_Controller', ('restart', None)),
])
def test_button_commands(ha, name, expected):
    ha._on_message(None, None, message('Kittec_CB40/control/' + name, 'PRESS'))
    assert ha.commands == [expected]


def test_select_starts_profile(ha):
    ha._on_message(None, None, message('Kittec_CB40/control/profiles', 'glaze'))
    assert ha.commands == [('run', 'glaze')]


def test_select_none_does_nothing(ha):
    ha._on_message(None, None, message('Kittec_CB40/control/profiles', 'None'))
    assert ha.commands == []


def test_retained_commands_ignored(ha):
    ha._on_message(None, None, message('Kittec_CB40/control/profiles', 'glaze', retain=True))
    assert ha.commands == []


def test_unknown_command_ignored(ha):
    ha._on_message(None, None, message('Kittec_CB40/control/Self_Destruct', 'PRESS'))
    assert ha.commands == []


def test_ha_birth_republishes_discovery(ha):
    ha._on_message(None, None, message('homeassistant/status', 'online'))
    assert 'homeassistant/sensor/kiln_controller/temperature/config' in ha.client.topics()


def test_on_connect_subscribes_and_announces(ha):
    rc = types.SimpleNamespace(is_failure=False)
    ha._on_connect(ha.client, None, None, rc, None)
    assert 'Kittec_CB40/control/#' in ha.client.subscribed
    assert 'homeassistant/status' in ha.client.subscribed
    assert ha.client.topics()['Kittec_CB40/status'] == 'online'


def test_on_connect_failure_does_nothing(ha):
    rc = types.SimpleNamespace(is_failure=True)
    ha._on_connect(ha.client, None, None, rc, None)
    assert ha.client.subscribed == []


def test_command_errors_do_not_raise(ha):
    def boom(command, argument):
        raise RuntimeError('nope')
    ha.on_command = boom
    ha._on_message(None, None, message('Kittec_CB40/control/Stop_Program', 'PRESS'))


def test_no_client_is_harmless(ha):
    ha.client = None
    ha.publish(state())
    ha.publish_discovery()


def test_schedule_discovery_has_attributes_topic(ha):
    configs = dict(ha.discovery_configs())
    sched = json.loads(configs['homeassistant/sensor/kiln_controller/schedule/config'])
    assert sched['unique_id'] == 'Kittec_CB40_Schedule'
    assert sched['stat_t'] == 'Kittec_CB40/schedule'
    assert sched['json_attr_t'] == 'Kittec_CB40/schedule/attributes'


def test_schedule_laid_from_run_start(ha):
    ha.schedule = lambda: [(0, 20.0), (3600, 600.04), (7200, 1222.0)]
    now = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    msgs = dict(ha.state_messages(state(runtime=1800), now=now))
    assert msgs['schedule'] == 'bisque'
    attrs = json.loads(msgs['schedule/attributes'])
    start = int(now.timestamp() - 1800) * 1000
    assert attrs['start'] == start
    assert attrs['end'] == start + 7200 * 1000
    assert attrs['points'] == [[start, 20.0], [start + 3600000, 600.0],
                               [start + 7200000, 1222.0]]


def test_schedule_start_ignores_timing_jitter(ha):
    ha.schedule = lambda: [(0, 20.0), (60, 30.0)]
    now = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    a = ha.schedule_attributes(state(runtime=1800.0), now)
    b = ha.schedule_attributes(state(runtime=1797.3), now)
    assert a == b


def test_schedule_empty_when_idle(ha):
    ha.schedule = lambda: [(0, 20.0), (60, 30.0)]
    msgs = dict(ha.state_messages(state(state='IDLE', profile=None)))
    assert msgs['schedule'] == 'None'
    assert json.loads(msgs['schedule/attributes']) == {'start': None, 'end': None, 'points': []}


def test_schedule_lookup_error_is_harmless(ha):
    def broken():
        raise RuntimeError('no oven')
    ha.schedule = broken
    msgs = dict(ha.state_messages(state()))
    assert json.loads(msgs['schedule/attributes'])['points'] == []


def test_shutdown_button_only_when_allowed(ha, monkeypatch):
    topic = 'homeassistant/button/kiln_controller/Shutdown_Pi/config'
    monkeypatch.setattr(config, 'allow_remote_shutdown', False, raising=False)
    assert topic not in dict(ha.discovery_configs())
    monkeypatch.setattr(config, 'allow_remote_shutdown', True)
    button = json.loads(dict(ha.discovery_configs())[topic])
    assert button['unique_id'] == 'Kittec_CB40_Shutdown_Pi'
    assert button['command_topic'] == 'Kittec_CB40/control/Shutdown_Pi'


def test_shutdown_button_command(ha):
    ha.handle_command('Shutdown_Pi', 'PRESS')
    assert ha.commands == [('shutdown', None)]
