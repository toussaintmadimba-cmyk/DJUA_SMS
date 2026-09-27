import os
import unittest
from unittest.mock import patch

from djua_sms_gateway.config import MqttConfig
from djua_sms_gateway.mqtt.client import (
    MqttConnectionError,
    MqttPublishError,
    PahoMqttClient,
)
from tests.unit.mqtt.fakes import FakePahoClient


class MqttClientTests(unittest.TestCase):
    def config(self, **changes):
        values = {
            "host": "broker.example",
            "port": 1883,
            "client_id": "djua-sms-gateway-001",
        }
        values.update(changes)
        return MqttConfig(**values)

    def test_config_validation(self):
        self.config().validate()
        invalid = (
            {"host": ""},
            {"port": 0},
            {"qos": 3},
            {"client_id": ""},
            {"client_id": "djua-DJUA-KIN-000001"},
            {"topic_prefix": "djua/#"},
            {"connect_timeout_seconds": 0},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.config(**changes).validate()

    def test_from_env(self):
        env = {
            "MQTT_HOST": "broker",
            "MQTT_PORT": "1884",
            "MQTT_QOS": "1",
            "MQTT_RETAIN": "true",
            "MQTT_CLIENT_ID": "djua-sms-gateway-test",
        }
        with patch.dict(os.environ, env, clear=True):
            config = MqttConfig.from_env()
        self.assertEqual(config.host, "broker")
        self.assertEqual(config.port, 1884)
        self.assertTrue(config.retain)

    def test_connect_and_publish(self):
        low_level = FakePahoClient()
        client = PahoMqttClient(self.config(), client=low_level)
        acks = []
        client.set_publish_ack_handler(acks.append)
        client.connect()
        self.assertTrue(client.connected)
        receipt = client.publish(
            "djua/test/x/telemetry",
            "{}",
            qos=1,
            retain=False,
        )
        self.assertEqual(receipt.mid, 1)
        low_level.on_publish(low_level, None, 1, 0, None)
        self.assertEqual(acks, [1])

    def test_optional_auth_and_tls(self):
        low_level = FakePahoClient()
        PahoMqttClient(
            self.config(username="u", password="p", tls=True),
            client=low_level,
        )
        self.assertEqual((low_level.username, low_level.password), ("u", "p"))
        self.assertTrue(low_level.tls)

    def test_connection_refused(self):
        low_level = FakePahoClient(connect_reason=5)
        client = PahoMqttClient(
            self.config(connect_timeout_seconds=0.1),
            client=low_level,
        )
        with self.assertRaises(MqttConnectionError):
            client.connect()

    def test_tcp_connect_failure(self):
        low_level = FakePahoClient(connect_fail=True)
        client = PahoMqttClient(
            self.config(connect_timeout_seconds=0.1),
            client=low_level,
        )
        with self.assertRaises(MqttConnectionError):
            client.connect()

    def test_publish_error_rc(self):
        low_level = FakePahoClient(publish_rc=4)
        client = PahoMqttClient(self.config(), client=low_level)
        client.connect()
        with self.assertRaises(MqttPublishError):
            client.publish("x", "{}", qos=1, retain=False)

    def test_reconnect_after_disconnect(self):
        low_level = FakePahoClient()
        client = PahoMqttClient(self.config(), client=low_level)
        client.connect()
        low_level.on_disconnect(low_level, None, None, 1, None)
        self.assertFalse(client.connected)
        client.reconnect()
        self.assertTrue(client.connected)

    def test_disconnect_changes_state(self):
        low_level = FakePahoClient()
        client = PahoMqttClient(self.config(), client=low_level)
        client.connect()
        client.disconnect()
        self.assertFalse(client.connected)


if __name__ == "__main__":
    unittest.main()
