import os
import unittest
from unittest.mock import patch

from djua_sms_gateway.config import D2SecurityConfig


KEY_HEX = (
    "000102030405060708090A0B0C0D0E0F"
    "101112131415161718191A1B1C1D1E1F"
)


class D2SecurityConfigTests(unittest.TestCase):
    def test_defaults_are_safe_development_without_secrets(self):
        config = D2SecurityConfig().validate()
        self.assertEqual(config.mode, "development")
        self.assertEqual(config.hmac_keys, {})
        self.assertEqual(config.sender_bindings, {})

    def test_environment_loads_hex_key_and_e164_binding(self):
        env = {
            "D2_AUTH_MODE": "production",
            "D2_HMAC_KEYS_JSON": (
                '{"DJUA-KIN-000001":"' + KEY_HEX + '"}'
            ),
            "D2_SENDER_BINDINGS_JSON": (
                '{"DJUA-KIN-000001":"+243810000001"}'
            ),
        }
        with patch.dict(os.environ, env, clear=False):
            config = D2SecurityConfig.from_env()

        self.assertEqual(config.mode, "production")
        self.assertEqual(
            config.key_for("DJUA-KIN-000001"),
            bytes.fromhex(KEY_HEX),
        )
        self.assertEqual(
            config.senders_for("DJUA-KIN-000001"),
            ("+243810000001",),
        )

    def test_bad_key_length_is_rejected(self):
        with self.assertRaises(ValueError):
            D2SecurityConfig(
                hmac_keys={"DJUA-KIN-000001": b"short"}
            ).validate()

    def test_non_e164_sender_is_rejected(self):
        with self.assertRaises(ValueError):
            D2SecurityConfig(
                sender_bindings={
                    "DJUA-KIN-000001": ("0810000001",)
                }
            ).validate()


if __name__ == "__main__":
    unittest.main()
