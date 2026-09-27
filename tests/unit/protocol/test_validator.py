import unittest

from djua_sms_gateway.protocol.models import AuthStatus, ValidationStatus
from djua_sms_gateway.protocol.parser import parse_d1
from djua_sms_gateway.protocol.validator import validate_telemetry
from tests.fixtures.d1_messages import (
    D1_AC_INVALID,
    D1_BATTERY_INVALID,
    D1_GPS_INVALID,
    D1_NEGATIVE_CURRENT,
    D1_RTC_INVALID,
    D1_SOLAR_INVALID,
    D1_SOLAR_ZERO_VALID,
    D1_VALID_ALL,
    D1_VALID_ALL_AUTH,
    replace_field,
)


class D1ValidatorTests(unittest.TestCase):
    def validate(self, message: str):
        return validate_telemetry(parse_d1(message))

    def test_complete_message_is_valid(self) -> None:
        self.assertEqual(self.validate(D1_VALID_ALL).status, ValidationStatus.VALID)

    def test_unknown_protocol_is_invalid(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 0, "D2"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_gps_valid_with_valid_coordinates(self) -> None:
        self.assertEqual(self.validate(D1_VALID_ALL).status, ValidationStatus.VALID)

    def test_gps_valid_with_latitude_over_90_is_invalid(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 7, "90.000001"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_gps_valid_with_longitude_over_180_is_invalid(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 8, "180.000001"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_gps_invalid_with_missing_coordinates_is_valid(self) -> None:
        self.assertEqual(self.validate(D1_GPS_INVALID).status, ValidationStatus.VALID)

    def test_gps_invalid_with_zero_coordinates_is_valid(self) -> None:
        message = replace_field(D1_VALID_ALL, 7, "0")
        message = replace_field(message, 8, "0")
        message = replace_field(message, 21, "1D")
        self.assertEqual(self.validate(message).status, ValidationStatus.VALID)

    def test_gps_invalid_with_nonzero_coordinates_warns(self) -> None:
        message = replace_field(D1_VALID_ALL, 21, "1D")
        result = self.validate(message)
        self.assertEqual(result.status, ValidationStatus.VALID_WITH_WARNING)

    def test_rtc_valid_is_valid(self) -> None:
        self.assertEqual(self.validate(D1_VALID_ALL).status, ValidationStatus.VALID)

    def test_rtc_invalid_is_valid(self) -> None:
        self.assertEqual(self.validate(D1_RTC_INVALID).status, ValidationStatus.VALID)

    def test_invalid_rtc_date_is_rejected(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 3, "20260230120000"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_current_contract_rejects_unconfirmed_timezone_label(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 4, "120"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_battery_valid_is_valid(self) -> None:
        self.assertEqual(self.validate(D1_VALID_ALL).status, ValidationStatus.VALID)

    def test_battery_invalid_is_valid(self) -> None:
        self.assertEqual(self.validate(D1_BATTERY_INVALID).status, ValidationStatus.VALID)

    def test_solar_zero_is_valid_measurement(self) -> None:
        result = self.validate(D1_SOLAR_ZERO_VALID)
        self.assertEqual(result.status, ValidationStatus.VALID)

    def test_solar_invalid_is_valid_transport_state(self) -> None:
        self.assertEqual(self.validate(D1_SOLAR_INVALID).status, ValidationStatus.VALID)

    def test_ac_valid_is_valid(self) -> None:
        self.assertEqual(self.validate(D1_VALID_ALL).status, ValidationStatus.VALID)

    def test_ac_invalid_is_valid_transport_state(self) -> None:
        self.assertEqual(self.validate(D1_AC_INVALID).status, ValidationStatus.VALID)

    def test_positive_current_is_not_rejected(self) -> None:
        self.assertEqual(self.validate(D1_VALID_ALL).status, ValidationStatus.VALID)

    def test_negative_current_is_not_rejected(self) -> None:
        self.assertEqual(self.validate(D1_NEGATIVE_CURRENT).status, ValidationStatus.VALID)

    def test_zero_interval_is_invalid(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 6, "0"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_negative_interval_is_invalid(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 6, "-1"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_nan_is_invalid(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 9, "NaN"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_infinity_is_invalid(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 9, "Infinity"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_reserved_flag_bits_are_invalid(self) -> None:
        result = self.validate(replace_field(D1_VALID_ALL, 21, "3F"))
        self.assertEqual(result.status, ValidationStatus.INVALID_FORMAT)

    def test_hmac_shaped_auth_is_not_claimed_as_verified(self) -> None:
        result = self.validate(D1_VALID_ALL_AUTH)
        self.assertEqual(result.status, ValidationStatus.VALID_WITH_WARNING)
        self.assertEqual(result.auth_status, AuthStatus.NOT_VERIFIED)
        self.assertTrue(any("AUTH_NOT_VERIFIED" in item for item in result.warnings))


if __name__ == "__main__":
    unittest.main()
