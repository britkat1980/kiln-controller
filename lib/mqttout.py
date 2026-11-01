import json
import logging

import config

log = logging.getLogger(__name__)


def enabled():
    return bool(getattr(config, "mqtt_enable", False))


class MqttOut:
    """publishes oven state to an mqtt broker when mqtt_enable is set."""

    def __init__(self, client_cls=None, topic=None):
        self.enabled = enabled()
        self.client = None
        # alerts use their own topic so subscribers can tell them apart
        # from the live state stream
        self.topic = topic or getattr(config, "mqtt_topic", "kiln/sensor")
        self.kiln_name = getattr(config, "mqtt_kiln_name", None)
        self._last_rc = 0
        if self.enabled:
            self._connect(client_cls)

    def _connect(self, client_cls):
        try:
            self.client = self._make_client(client_cls)
            self.client.loop_start()
        except Exception:
            log.exception("mqtt client setup failed")
            self.client = None

    def _make_client(self, client_cls):
        if client_cls is None:
            import paho.mqtt.client as mqtt

            client_cls = mqtt.Client
        host = getattr(config, "mqtt_host", "localhost")
        port = getattr(config, "mqtt_port", 1883)
        user = getattr(config, "mqtt_user", None)
        password = getattr(config, "mqtt_pass", None)
        client = client_cls()
        if user is not None:
            client.username_pw_set(user, password)
        # connect_async + loop_start keeps retrying in the background, so a
        # broker or network that is not up yet at boot is picked up later
        client.connect_async(host, port)
        return client

    def publish(self, state):
        if not self.enabled or self.client is None:
            return
        payload = dict(state)
        if self.kiln_name:
            payload["name"] = self.kiln_name
        try:
            result = self.client.publish(self.topic, json.dumps(payload))
            rc = getattr(result, "rc", 0)
            # state is published every second: log a failure once, not
            # every second while the broker is down
            if rc and rc != self._last_rc:
                log.error("mqtt publish returned rc=%s", rc)
            self._last_rc = rc
        except Exception:
            log.exception("mqtt publish failed")
