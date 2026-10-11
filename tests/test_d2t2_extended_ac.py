"""Regression tests for the 60-byte D2T2 extended AC layout.

These tests keep the historical authenticated vector, deliberately set the
AC extension discriminator, and cover values, unavailable codes and HMAC.
"""

import base64
import hashlib
import hmac
import unittest

from djua_sms_gateway.protocol.d2 import D2AuthStatus, D2ProtocolError
from djua_sms_gateway.protocol.d2t2 import (
    D2T2_AC_EXTENDED_FLAG,
    D2T2_LAYOUT,
    normalize_d2t2_to_backend,
    parse_d2t2,
    verify_d2t2_security,
)


LEGACY = (
    "D2T2,DJUA-KIN-000001,"
    "AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAARgj9B9AmNBZ4ABfgjA-AyAAGLAAHuAH_A,"
    "rHcRllcP4gs"
)

EXTENDED_SIGNED = (
    "D2T2,DJUA-KIN-000001,"
    "AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAARgj9B9AmN6ceABfgjA-AyAAGLAAHuAP_o"
)
EXTENDED_AUTH = "RIiCkWzDza4"
TEST_KEY = bytes(range(32))


def replace_fields(message: str, replacements: dict[str, int]) -> str:
    parts = message.split(",")
    original = base64.urlsafe_b64decode(parts[2] + "==")
    packed = int.from_bytes(original, "big")
    remaining = 480

    for name, width, _signed in D2T2_LAYOUT:
        remaining -= width
        if name not in replacements:
            continue
        mask = ((1 << width) - 1) << remaining
        packed = (packed & ~mask) | ((replacements[name] & ((1 << width) - 1)) << remaining)

    assert remaining == 0
    parts[2] = base64.urlsafe_b64encode(packed.to_bytes(60, "big")).decode("ascii").rstrip("=")
    parts[3] = "-"  # Development only: tests of parse and normalization
    return ",".join(parts)


def extended(message: str = LEGACY, *, power_factor_code: int = 1870, frequency_code: int = 1000) -> str:
    flags = 0x01FF | D2T2_AC_EXTENDED_FLAG
    return replace_fields(
        message,
        {
            "flags": flags,
            "ac_apparent_power_raw": (power_factor_code << 6) | (frequency_code >> 6),
            "reserved_tail": frequency_code & 0x3F,
        },
    )


class D2T2ExtendedACTests(unittest.TestCase):
    def test_legacy_unchanged(self):
        message = parse_d2t2(LEGACY)
        self.assertFalse(message.ac_extended)
        self.assertEqual(message.ac_apparent_power, 287.6)
        output = normalize_d2t2_to_backend(
            message,
            gateway_received_at="2026-10-11T12:00:00+00:00",
            auth_status=D2AuthStatus.VERIFIED,
        )
        self.assertEqual(output["ac_load"]["apparent_power_va"], 287.6)
        self.assertNotIn("power_factor", output["ac_load"])

    def test_extended_ac_values_and_json(self):
        sms = extended()
        self.assertEqual(len(sms.split(",")[2]), 80)
        self.assertLessEqual(len(sms), 130)
        message = parse_d2t2(sms)
        self.assertTrue(message.ac_extended)
        self.assertIsNone(message.ac_apparent_power)
        self.assertAlmostEqual(message.ac_power_factor, 0.87)
        self.assertAlmostEqual(message.ac_frequency_hz, 50.00)
        output = normalize_d2t2_to_backend(
            message,
            gateway_received_at="2026-10-11T12:00:00+00:00",
            auth_status=D2AuthStatus.NOT_VERIFIED,
        )
        self.assertNotIn("apparent_power_va", output["ac_load"])
        self.assertAlmostEqual(output["ac_load"]["power_factor"], 0.87)
        self.assertAlmostEqual(output["ac_load"]["frequency_hz"], 50)
        self.assertEqual(output["dc_load"]["power_w"], 39.5)

    def test_unknown_values_use_null_without_invalidating_ac(self):
        sms = extended(power_factor_code=2047, frequency_code=4095)
        message = parse_d2t2(sms)
        self.assertTrue(message.ac_valid)
        self.assertIsNone(message.ac_power_factor)
        self.assertIsNone(message.ac_frequency_hz)

    def test_reject_reserved_pf_code(self):
        with self.assertRaises(D2ProtocolError):
            parse_d2t2(extended(power_factor_code=2046))

    def test_reject_reserved_frequency_code(self):
        with self.assertRaises(D2ProtocolError):
            parse_d2t2(extended(frequency_code=3001))

    def test_reject_nonzero_legacy_tail(self):
        with self.assertRaises(D2ProtocolError):
            parse_d2t2(replace_fields(LEGACY, {"reserved_tail": 1}))

    def test_authenticated_reference_vector(self):
        self.assertEqual(
            base64.urlsafe_b64encode(
                hmac.new(TEST_KEY, EXTENDED_SIGNED.encode("ascii"), hashlib.sha256).digest()[:8]
            ).decode("ascii").rstrip("="),
            EXTENDED_AUTH,
        )
        message = parse_d2t2(EXTENDED_SIGNED + "," + EXTENDED_AUTH)
        self.assertTrue(message.ac_extended)
        self.assertAlmostEqual(message.ac_power_factor, 0.87)
        self.assertAlmostEqual(message.ac_frequency_hz, 50.0)
        self.assertEqual(
            verify_d2t2_security(
                message,
                mode="production",
                key=TEST_KEY,
                sender="+243812345678",
                allowed_senders=("+243812345678",),
            ),
            D2AuthStatus.VERIFIED,
        )


if __name__ == "__main__":
    unittest.main()
