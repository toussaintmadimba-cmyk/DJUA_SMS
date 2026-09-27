import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.protocol.parser import parse_d1
from djua_sms_gateway.storage import Database
from djua_sms_gateway.storage.models import RawSmsInput, StoreDisposition
from djua_sms_gateway.storage.repository import (
    SmsRepository,
    compute_logical_dedupe_key,
    compute_raw_dedupe_key,
)
from tests.fixtures.d1_messages import (
    D1_GPS_INVALID,
    D1_VALID_ALL,
    D1_VALID_ALL_AUTH,
    replace_field,
)


class DeduplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db")
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_raw_key_is_deterministic(self) -> None:
        raw = RawSmsInput("+2431", D1_VALID_ALL, "modem-time")
        self.assertEqual(compute_raw_dedupe_key(raw), compute_raw_dedupe_key(raw))

    def test_same_raw_sms_returns_existing_id(self) -> None:
        raw = RawSmsInput("+2431", D1_VALID_ALL, "modem-time")
        first = self.repository.store_raw_sms(raw)
        second = self.repository.store_raw_sms(raw)
        self.assertEqual(first.disposition, StoreDisposition.STORED)
        self.assertEqual(second.disposition, StoreDisposition.DUPLICATE)
        self.assertEqual(first.record.id, second.record.id)
        self.assertEqual(self.repository.count_inbound(), 1)

    def test_raw_key_does_not_depend_on_modem_memory_index(self) -> None:
        raw = RawSmsInput("+2431", D1_VALID_ALL, "modem-time")
        key = compute_raw_dedupe_key(raw)
        self.assertEqual(len(key), 64)
        self.assertNotIn("SIM", key)

    def test_missing_modem_timestamp_still_deduplicates_exact_replay(self) -> None:
        raw = RawSmsInput("+2431", D1_VALID_ALL, None)
        first = self.repository.store_raw_sms(raw)
        second = self.repository.store_raw_sms(raw)
        self.assertEqual(first.record.id, second.record.id)
        self.assertEqual(self.repository.count_inbound(), 1)

    def test_same_body_with_different_modem_timestamp_is_different_raw_receipt(self) -> None:
        a = RawSmsInput("+2431", D1_VALID_ALL, "t1")
        b = RawSmsInput("+2431", D1_VALID_ALL, "t2")
        self.assertNotEqual(compute_raw_dedupe_key(a), compute_raw_dedupe_key(b))

    def test_logical_key_is_deterministic(self) -> None:
        telemetry = parse_d1(D1_VALID_ALL)
        self.assertEqual(
            compute_logical_dedupe_key(telemetry),
            compute_logical_dedupe_key(telemetry),
        )

    def test_logical_key_ignores_auth_text(self) -> None:
        plain = parse_d1(D1_VALID_ALL)
        authed = parse_d1(D1_VALID_ALL_AUTH)
        self.assertEqual(
            compute_logical_dedupe_key(plain),
            compute_logical_dedupe_key(authed),
        )

    def test_logical_key_normalizes_equivalent_decimal_formatting(self) -> None:
        a = parse_d1(D1_VALID_ALL)
        b = parse_d1(replace_field(D1_VALID_ALL, 9, "12.400"))
        self.assertEqual(
            compute_logical_dedupe_key(a),
            compute_logical_dedupe_key(b),
        )

    def test_logical_key_ignores_values_declared_invalid(self) -> None:
        missing = parse_d1(D1_GPS_INVALID)
        zeroed_message = replace_field(D1_GPS_INVALID, 7, "0")
        zeroed_message = replace_field(zeroed_message, 8, "0")
        zeroed = parse_d1(zeroed_message)
        self.assertEqual(
            compute_logical_dedupe_key(missing),
            compute_logical_dedupe_key(zeroed),
        )

    def test_same_sequence_on_different_devices_is_not_duplicate(self) -> None:
        a = parse_d1(D1_VALID_ALL)
        b = parse_d1(replace_field(D1_VALID_ALL, 1, "DJUA-KIN-000002"))
        self.assertNotEqual(
            compute_logical_dedupe_key(a),
            compute_logical_dedupe_key(b),
        )

    def test_reboot_or_wrap_identity_uses_more_than_device_and_sequence(self) -> None:
        a = parse_d1(D1_VALID_ALL)
        b_message = replace_field(D1_VALID_ALL, 3, "20260928163000")
        b_message = replace_field(b_message, 5, "10")
        b = parse_d1(b_message)
        self.assertNotEqual(
            compute_logical_dedupe_key(a),
            compute_logical_dedupe_key(b),
        )


if __name__ == "__main__":
    unittest.main()
