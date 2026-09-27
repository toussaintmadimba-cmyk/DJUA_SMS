import unittest

from djua_sms_gateway.protocol.errors import NormalizationError
from djua_sms_gateway.protocol.normalizer import normalize_to_mqtt
from djua_sms_gateway.protocol.parser import parse_d1
from tests.fixtures.d1_messages import (
    D1_AC_INVALID,
    D1_BATTERY_INVALID,
    D1_GPS_INVALID,
    D1_RTC_INVALID,
    D1_SOLAR_INVALID,
    D1_SOLAR_ZERO_VALID,
    D1_VALID_ALL,
    replace_field,
)


class D1NormalizerTests(unittest.TestCase):
    def normalize(self, message: str) -> dict:
        return normalize_to_mqtt(parse_d1(message)).to_dict()

    def test_complete_payload_matches_djua_contract(self) -> None:
        payload = self.normalize(D1_VALID_ALL)
        self.assertEqual(payload["kit_id"], "DJUA-KIN-000001")
        self.assertEqual(payload["timestamp_ms"], 123456789)
        self.assertEqual(payload["timestamp"], "2026-09-27T16:30:00+01:00")
        self.assertEqual(payload["timezone"], "GMT+1")
        self.assertEqual(payload["interval_seconds"], 1800)
        self.assertEqual(payload["latitude"], -4.3251)
        self.assertEqual(payload["longitude"], 15.3222)
        self.assertEqual(
            payload["battery"],
            {"voltage_v": 12.4, "current_a": 0.5, "power_w": 6.2},
        )
        self.assertEqual(
            payload["solar"],
            {
                "voltage_v": 18.2,
                "current_a": 1.23,
                "power_w": 22.39,
                "energy_interval_wh": 11.2,
            },
        )
        self.assertEqual(
            payload["ac_load"],
            {
                "voltage_v": 230.1,
                "current_a": 1.25,
                "active_power_w": 244.5,
                "apparent_power_va": 287.6,
                "energy_interval_wh": 122.25,
            },
        )

    def test_rtc_invalid_omits_timestamp_and_timezone(self) -> None:
        payload = self.normalize(D1_RTC_INVALID)
        self.assertNotIn("timestamp", payload)
        self.assertNotIn("timezone", payload)
        self.assertEqual(payload["timestamp_ms"], 123456789)

    def test_gps_invalid_normalizes_to_zero_coordinates(self) -> None:
        payload = self.normalize(D1_GPS_INVALID)
        self.assertEqual(payload["latitude"], 0.0)
        self.assertEqual(payload["longitude"], 0.0)

    def test_battery_invalid_normalizes_to_zero_values(self) -> None:
        payload = self.normalize(D1_BATTERY_INVALID)
        self.assertEqual(
            payload["battery"],
            {"voltage_v": 0.0, "current_a": 0.0, "power_w": 0.0},
        )

    def test_solar_valid_zero_stays_zero_not_null(self) -> None:
        payload = self.normalize(D1_SOLAR_ZERO_VALID)
        self.assertEqual(payload["solar"]["power_w"], 0.0)
        self.assertEqual(payload["solar"]["current_a"], 0.0)
        self.assertIsNotNone(payload["solar"]["power_w"])

    def test_solar_invalid_normalizes_to_null(self) -> None:
        payload = self.normalize(D1_SOLAR_INVALID)
        self.assertEqual(
            payload["solar"],
            {
                "voltage_v": None,
                "current_a": None,
                "power_w": None,
                "energy_interval_wh": None,
            },
        )

    def test_ac_invalid_normalizes_to_zero_values(self) -> None:
        payload = self.normalize(D1_AC_INVALID)
        self.assertEqual(
            payload["ac_load"],
            {
                "voltage_v": 0.0,
                "current_a": 0.0,
                "active_power_w": 0.0,
                "apparent_power_va": 0.0,
                "energy_interval_wh": 0.0,
            },
        )

    def test_transport_fields_are_not_added_to_mqtt_payload(self) -> None:
        payload = self.normalize(D1_VALID_ALL)
        for field in ("protocol", "sequence", "flags", "auth"):
            self.assertNotIn(field, payload)

    def test_invalid_telemetry_cannot_be_normalized(self) -> None:
        telemetry = parse_d1(replace_field(D1_VALID_ALL, 6, "0"))
        with self.assertRaises(NormalizationError):
            normalize_to_mqtt(telemetry)


if __name__ == "__main__":
    unittest.main()
