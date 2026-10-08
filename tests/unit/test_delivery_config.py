import os
import unittest
from unittest.mock import patch

from djua_sms_gateway.config import DeliveryMode, HttpConfig
from scripts.run_gateway import load_runtime_configs


class DeliveryConfigTests(unittest.TestCase):
    def test_delivery_mode_defaults_to_mqtt_only(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                DeliveryMode.from_env(),
                DeliveryMode.MQTT_ONLY,
            )

    def test_delivery_mode_rejects_unknown_value(self):
        with patch.dict(
            os.environ,
            {"DELIVERY_MODE": "MAGIC"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "DELIVERY_MODE"):
                DeliveryMode.from_env()

    def test_http_config_accepts_backend_and_optional_event_url(self):
        env = {
            "HTTP_BACKEND_URL": "http://127.0.0.1:5000/api/iot/telemetry",
            "HTTP_EVENT_URL": "https://example.test/geofence/events",
            "HTTP_API_KEY_HEADER": "x-device-token",
            "HTTP_API_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=True):
            config = HttpConfig.from_env()
        self.assertEqual(
            config.normalized_backend_url,
            "http://127.0.0.1:5000/api/iot/telemetry",
        )
        self.assertEqual(
            config.normalized_event_url,
            "https://example.test/geofence/events",
        )
        self.assertEqual(
            config.headers,
            {"x-device-token": "secret"},
        )

    def test_http_only_does_not_require_mqtt_host(self):
        env = {
            "SERIAL_PORT": "COM16",
            "DELIVERY_MODE": "HTTP_ONLY",
            "HTTP_BACKEND_URL": "http://127.0.0.1:5000/api/iot/telemetry",
        }
        with patch.dict(os.environ, env, clear=True):
            app, gsm, mqtt, security = load_runtime_configs()
        self.assertEqual(app.delivery_mode, DeliveryMode.HTTP_ONLY)
        self.assertEqual(gsm.serial_port, "COM16")
        self.assertIsNone(mqtt)
        self.assertIsNotNone(app.http)
        self.assertEqual(security.mode, "development")

    def test_dual_mode_requires_both_http_and_mqtt_configuration(self):
        env = {
            "SERIAL_PORT": "COM16",
            "DELIVERY_MODE": "MQTT_AND_HTTP",
            "HTTP_BACKEND_URL": "http://127.0.0.1:5000/api/iot/telemetry",
            "MQTT_HOST": "test.mosquitto.org",
        }
        with patch.dict(os.environ, env, clear=True):
            app, _gsm, mqtt, _security = load_runtime_configs()
        self.assertEqual(app.delivery_mode, DeliveryMode.MQTT_AND_HTTP)
        self.assertIsNotNone(app.http)
        self.assertEqual(mqtt.host, "test.mosquitto.org")


if __name__ == "__main__":
    unittest.main()
