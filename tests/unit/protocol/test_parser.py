import unittest

from djua_sms_gateway.protocol.errors import D1ParseError
from djua_sms_gateway.protocol.parser import decode_base36, parse_d1
from tests.fixtures.d1_messages import D1_MALFORMED, D1_VALID_ALL, replace_field


class D1ParserTests(unittest.TestCase):
    def test_valid_d1_message(self) -> None:
        telemetry = parse_d1(D1_VALID_ALL)
        self.assertEqual(telemetry.protocol_version, "D1")
        self.assertEqual(telemetry.device_id, "DJUA-KIN-000001")
        self.assertEqual(telemetry.sequence, 12345)
        self.assertEqual(telemetry.uptime_ms, 123456789)
        self.assertEqual(telemetry.flags, 0x1F)
        self.assertTrue(telemetry.rtc_valid)
        self.assertTrue(telemetry.gps_valid)
        self.assertTrue(telemetry.battery_valid)
        self.assertTrue(telemetry.solar_valid)
        self.assertTrue(telemetry.ac_valid)

    def test_exact_field_count(self) -> None:
        self.assertEqual(len(D1_VALID_ALL.split(",")), 23)

    def test_missing_field_is_rejected(self) -> None:
        with self.assertRaises(D1ParseError):
            parse_d1(D1_MALFORMED)

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(D1ParseError):
            parse_d1(D1_VALID_ALL + ",EXTRA")

    def test_unknown_djua_version_is_parsed_for_validator(self) -> None:
        telemetry = parse_d1(replace_field(D1_VALID_ALL, 0, "D2"))
        self.assertEqual(telemetry.protocol_version, "D2")

    def test_empty_device_id_is_rejected(self) -> None:
        with self.assertRaises(D1ParseError):
            parse_d1(replace_field(D1_VALID_ALL, 1, ""))

    def test_sequence_is_strict_base36(self) -> None:
        telemetry = parse_d1(replace_field(D1_VALID_ALL, 2, "ZZ"))
        self.assertEqual(telemetry.sequence, 1295)

    def test_base36_examples(self) -> None:
        expected = {
            "0": 0,
            "1": 1,
            "Z": 35,
            "10": 36,
            "ZZ": 1295,
        }
        for value, decoded in expected.items():
            with self.subTest(value=value):
                self.assertEqual(decode_base36(value, "test"), decoded)

    def test_invalid_base36_is_rejected(self) -> None:
        for value in ("", "z", "1!", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(D1ParseError):
                    decode_base36(value, "test")

    def test_uptime_base36_is_strict(self) -> None:
        telemetry = parse_d1(D1_VALID_ALL)
        self.assertEqual(telemetry.uptime_ms, 123456789)
        with self.assertRaises(D1ParseError):
            parse_d1(replace_field(D1_VALID_ALL, 5, "21i3v9"))

    def test_valid_flags_are_decoded(self) -> None:
        cases = {
            "00": (False, False, False, False, False),
            "01": (True, False, False, False, False),
            "02": (False, True, False, False, False),
            "04": (False, False, True, False, False),
            "08": (False, False, False, True, False),
            "10": (False, False, False, False, True),
            "1F": (True, True, True, True, True),
        }
        for raw, expected in cases.items():
            with self.subTest(flags=raw):
                telemetry = parse_d1(replace_field(D1_VALID_ALL, 21, raw))
                actual = (
                    telemetry.rtc_valid,
                    telemetry.gps_valid,
                    telemetry.battery_valid,
                    telemetry.solar_valid,
                    telemetry.ac_valid,
                )
                self.assertEqual(actual, expected)

    def test_invalid_flags_are_rejected(self) -> None:
        for flags in ("1G", "1f", "F", "001"):
            with self.subTest(flags=flags):
                with self.assertRaises(D1ParseError):
                    parse_d1(replace_field(D1_VALID_ALL, 21, flags))

    def test_valid_float_is_converted(self) -> None:
        telemetry = parse_d1(D1_VALID_ALL)
        self.assertEqual(telemetry.battery_voltage, 12.4)

    def test_invalid_float_is_rejected(self) -> None:
        with self.assertRaises(D1ParseError):
            parse_d1(replace_field(D1_VALID_ALL, 9, "twelve"))

    def test_nan_and_infinity_reach_validator_as_floats(self) -> None:
        nan_value = parse_d1(replace_field(D1_VALID_ALL, 9, "NaN"))
        inf_value = parse_d1(replace_field(D1_VALID_ALL, 9, "Infinity"))
        self.assertNotEqual(nan_value.battery_voltage, nan_value.battery_voltage)
        self.assertEqual(inf_value.battery_voltage, float("inf"))

    def test_unexpected_space_is_rejected(self) -> None:
        with self.assertRaises(D1ParseError):
            parse_d1(replace_field(D1_VALID_ALL, 1, "DJUA KIN"))

    def test_empty_line_is_rejected(self) -> None:
        with self.assertRaises(D1ParseError):
            parse_d1("")

    def test_non_djua_message_is_rejected(self) -> None:
        with self.assertRaises(D1ParseError):
            parse_d1(replace_field(D1_VALID_ALL, 0, "X1"))


if __name__ == "__main__":
    unittest.main()
