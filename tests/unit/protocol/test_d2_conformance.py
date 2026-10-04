import json
import unittest
from pathlib import Path

from djua_sms_gateway.protocol.d2 import (
    D2AuthStatus,
    D2EMessage,
    D2ProtocolError,
    D2TMessage,
    backend_topic,
    calculate_hmac_tag,
    gsm7_septet_count,
    normalize_d2_to_backend,
    parse_d2,
    verify_d2_security,
)


VECTORS_PATH = (
    Path(__file__).resolve().parents[2]
    / "vectors"
    / "d2_conformance.json"
)


def decoded(message):
    if isinstance(message, D2TMessage):
        return {
            "protocol": "D2T",
            "device_id": message.device_id,
            "sequence": message.sequence,
            "rtc_epoch_s": message.rtc_epoch_s,
            "uptime_ms": message.uptime_ms,
            "interval_seconds": message.interval_seconds,
            "latitude": message.latitude,
            "longitude": message.longitude,
            "battery": {
                "voltage_v": message.battery_voltage,
                "current_a": message.battery_current,
                "power_w": message.battery_power,
            },
            "solar": {
                "voltage_v": message.solar_voltage,
                "current_a": message.solar_current,
                "power_w": message.solar_power,
                "energy_interval_wh": message.solar_energy_interval_wh,
            },
            "ac_load": {
                "voltage_v": message.ac_voltage,
                "current_a": message.ac_current,
                "active_power_w": message.ac_active_power,
                "apparent_power_va": message.ac_apparent_power,
                "energy_interval_wh": message.ac_energy_interval_wh,
            },
            "flags": message.flags,
        }
    if isinstance(message, D2EMessage):
        return {
            "protocol": "D2E",
            "device_id": message.device_id,
            "sequence": message.sequence,
            "rtc_epoch_s": message.rtc_epoch_s,
            "uptime_ms": message.uptime_ms,
            "event_code": message.event_code,
            "latitude": message.latitude,
            "longitude": message.longitude,
            "distance_m": message.distance_m,
            "flags": message.flags,
        }
    raise TypeError(type(message))


class D2ConformanceVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
        cls.test_key = bytes.fromhex(cls.document["test_key_hex"])

    def test_valid_vectors_are_exact(self):
        valid = [
            item
            for item in self.document["vectors"]
            if "expected_decoded" in item
        ]
        self.assertGreaterEqual(len(valid), 7)

        for vector in valid:
            with self.subTest(vector=vector["name"]):
                message = parse_d2(vector["sms"])
                self.assertEqual(
                    gsm7_septet_count(vector["sms"]),
                    vector["gsm7_septets"],
                )
                self.assertEqual(
                    decoded(message),
                    vector["expected_decoded"],
                )

                if vector["expected_auth"] == "-":
                    status = verify_d2_security(
                        message,
                        mode="development",
                        key=None,
                    )
                else:
                    key = bytes.fromhex(vector["test_key_hex"])
                    self.assertEqual(
                        calculate_hmac_tag(message.signed_part, key),
                        vector["expected_auth"],
                    )
                    status = verify_d2_security(
                        message,
                        mode="production",
                        key=key,
                        sender=vector["sender"],
                        allowed_senders=[vector["sender"]],
                    )

                self.assertEqual(
                    backend_topic(message),
                    vector["backend_topic"],
                )
                self.assertEqual(
                    normalize_d2_to_backend(
                        message,
                        gateway_received_at=vector[
                            "gateway_received_at"
                        ],
                        auth_status=status,
                    ),
                    vector["expected_backend_payload"],
                )

    def test_invalid_vectors_fail_for_the_declared_reason(self):
        invalid = [
            item
            for item in self.document["vectors"]
            if item.get("expected_error")
        ]

        parse_errors = {
            "SMS_TOO_LONG",
            "NON_GSM7",
            "NON_CANONICAL_BASE36",
            "FLAG_VALUE_MISMATCH",
        }

        for vector in invalid:
            with self.subTest(vector=vector["name"]):
                expected = vector["expected_error"]
                if expected in parse_errors:
                    with self.assertRaises(D2ProtocolError) as context:
                        parse_d2(vector["sms"])
                    self.assertEqual(context.exception.code, expected)
                    continue

                message = parse_d2(vector["sms"])
                key = bytes.fromhex(vector["test_key_hex"])
                allowed = [
                    vector.get("allowed_sender", vector["sender"])
                ]
                with self.assertRaises(D2ProtocolError) as context:
                    verify_d2_security(
                        message,
                        mode=vector["mode"],
                        key=key,
                        sender=vector["sender"],
                        allowed_senders=allowed,
                    )
                self.assertEqual(context.exception.code, expected)

    def test_all_declared_gsm7_lengths_are_exact(self):
        for vector in self.document["vectors"]:
            if vector["name"] == "d2t_non_gsm7":
                continue
            with self.subTest(vector=vector["name"]):
                self.assertIsInstance(vector["gsm7_septets"], int)
                self.assertEqual(
                    gsm7_septet_count(vector["sms"]),
                    vector["gsm7_septets"],
                )

    def test_non_gsm7_vector_is_checked_separately(self):
        vector = next(
            item
            for item in self.document["vectors"]
            if item["name"] == "d2t_non_gsm7"
        )
        self.assertIsNone(vector["gsm7_septets"])
        with self.assertRaises(D2ProtocolError) as context:
            gsm7_septet_count(vector["sms"])
        self.assertEqual(context.exception.code, "NON_GSM7")

    def test_boundary_vector_is_exactly_one_sms(self):
        vector = next(
            item
            for item in self.document["vectors"]
            if item["name"] == "d2t_max_authenticated"
        )
        self.assertEqual(vector["gsm7_septets"], 160)
        self.assertEqual(gsm7_septet_count(vector["sms"]), 160)

    def test_oversize_vector_is_161(self):
        vector = next(
            item
            for item in self.document["vectors"]
            if item["name"] == "d2t_161_septets"
        )
        self.assertEqual(vector["gsm7_septets"], 161)


if __name__ == "__main__":
    unittest.main()
