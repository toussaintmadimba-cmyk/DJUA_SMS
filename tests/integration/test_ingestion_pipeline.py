import json
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.services.ingestion import (
    IngestionDisposition,
    SmsIngestionService,
)
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import InboundStatus, RawSmsInput
from tests.fixtures.d1_messages import (
    D1_MALFORMED,
    D1_SOLAR_INVALID,
    D1_SOLAR_ZERO_VALID,
    D1_VALID_ALL,
    D1_VALID_ALL_AUTH,
    replace_field,
)


class IngestionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"
        self.repository = SmsRepository(Database(self.path))
        self.service = SmsIngestionService(self.repository)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def raw(self, body: str, *, sender: str = "+243810000001", modem_timestamp: str = "t1"):
        return RawSmsInput(
            sender=sender,
            raw_body=body,
            modem_timestamp=modem_timestamp,
            gateway_received_at="2026-09-27T16:00:00+00:00",
        )

    def test_valid_sms_flows_to_persistent_outbox_without_network(self) -> None:
        result = self.service.ingest(self.raw(D1_VALID_ALL))
        self.assertEqual(result.disposition, IngestionDisposition.QUEUED)
        inbound = self.repository.get_inbound(result.sms_id)
        outbox = self.repository.get_outbox(result.outbox_id)
        self.assertEqual(inbound.status, InboundStatus.QUEUED)
        self.assertEqual(outbox.topic, "djua/test/DJUA-KIN-000001/telemetry")
        payload = json.loads(outbox.payload_json)
        self.assertEqual(payload["kit_id"], "DJUA-KIN-000001")
        self.assertNotIn("protocol", payload)
        self.assertNotIn("sequence", payload)
        self.assertNotIn("flags", payload)
        self.assertNotIn("auth", payload)

    def test_invalid_sms_is_kept_for_audit_without_outbox(self) -> None:
        result = self.service.ingest(self.raw(D1_MALFORMED))
        self.assertEqual(result.disposition, IngestionDisposition.INVALID)
        inbound = self.repository.get_inbound(result.sms_id)
        self.assertEqual(inbound.status, InboundStatus.INVALID)
        self.assertTrue(inbound.validation_error)
        self.assertEqual(inbound.raw_body, D1_MALFORMED)
        self.assertEqual(self.repository.count_outbox(), 0)

    def test_crash_before_modem_delete_replay_creates_one_row_and_one_outbox(self) -> None:
        raw = self.raw(D1_VALID_ALL)
        first = self.service.ingest(raw)
        second = self.service.ingest(raw)
        self.assertEqual(first.disposition, IngestionDisposition.QUEUED)
        self.assertEqual(second.disposition, IngestionDisposition.DUPLICATE_RAW)
        self.assertEqual(first.sms_id, second.sms_id)
        self.assertEqual(self.repository.count_inbound(), 1)
        self.assertEqual(self.repository.count_outbox(), 1)

    def test_different_raw_sms_same_logical_telemetry_has_one_outbox(self) -> None:
        first = self.service.ingest(self.raw(D1_VALID_ALL, modem_timestamp="t1"))
        second = self.service.ingest(self.raw(D1_VALID_ALL_AUTH, modem_timestamp="t2"))
        self.assertEqual(first.disposition, IngestionDisposition.QUEUED)
        self.assertEqual(second.disposition, IngestionDisposition.DUPLICATE_LOGICAL)
        self.assertEqual(second.duplicate_of_sms_id, first.sms_id)
        self.assertEqual(self.repository.count_inbound(), 2)
        self.assertEqual(self.repository.count_outbox(), 1)
        duplicate = self.repository.get_inbound(second.sms_id)
        self.assertEqual(duplicate.status, InboundStatus.VALIDATED)
        self.assertIn("DUPLICATE_LOGICAL", duplicate.validation_warning)

    def test_solar_invalid_is_persisted_as_json_null(self) -> None:
        result = self.service.ingest(self.raw(D1_SOLAR_INVALID))
        payload = json.loads(self.repository.get_outbox(result.outbox_id).payload_json)
        self.assertEqual(
            payload["solar"],
            {
                "voltage_v": None,
                "current_a": None,
                "power_w": None,
                "energy_interval_wh": None,
            },
        )

    def test_solar_valid_zero_is_persisted_as_zero_not_null(self) -> None:
        result = self.service.ingest(self.raw(D1_SOLAR_ZERO_VALID))
        payload = json.loads(self.repository.get_outbox(result.outbox_id).payload_json)
        self.assertEqual(payload["solar"]["power_w"], 0.0)
        self.assertIsNotNone(payload["solar"]["power_w"])

    def test_multi_device_creates_distinct_rows_topics_and_keys(self) -> None:
        results = []
        for index in range(1, 4):
            device = f"DJUA-KIN-00000{index}"
            message = replace_field(D1_VALID_ALL, 1, device)
            results.append(
                self.service.ingest(
                    self.raw(
                        message,
                        sender=f"+24381000000{index}",
                        modem_timestamp=f"t{index}",
                    )
                )
            )
        self.assertTrue(all(r.disposition is IngestionDisposition.QUEUED for r in results))
        self.assertEqual(self.repository.count_inbound(), 3)
        self.assertEqual(self.repository.count_outbox(), 3)
        topics = {
            self.repository.get_outbox(result.outbox_id).topic for result in results
        }
        self.assertEqual(len(topics), 3)

    def test_same_sequence_on_different_devices_does_not_collide(self) -> None:
        first = self.service.ingest(self.raw(D1_VALID_ALL, sender="+2431", modem_timestamp="t1"))
        second_message = replace_field(D1_VALID_ALL, 1, "DJUA-KIN-000002")
        second = self.service.ingest(
            self.raw(second_message, sender="+2432", modem_timestamp="t2")
        )
        self.assertEqual(first.disposition, IngestionDisposition.QUEUED)
        self.assertEqual(second.disposition, IngestionDisposition.QUEUED)
        self.assertEqual(self.repository.count_outbox(), 2)

    def test_reboot_with_reused_sequence_is_distinct_when_rtc_and_uptime_change(self) -> None:
        first = self.service.ingest(self.raw(D1_VALID_ALL, modem_timestamp="t1"))
        rebooted = replace_field(D1_VALID_ALL, 3, "20260928163000")
        rebooted = replace_field(rebooted, 5, "10")
        second = self.service.ingest(self.raw(rebooted, modem_timestamp="t2"))
        self.assertEqual(first.disposition, IngestionDisposition.QUEUED)
        self.assertEqual(second.disposition, IngestionDisposition.QUEUED)
        self.assertEqual(self.repository.count_outbox(), 2)

    def test_uint32_max_millis_is_stored_without_wrap_correction(self) -> None:
        message = replace_field(D1_VALID_ALL, 5, "1Z141Z3")
        result = self.service.ingest(self.raw(message))
        self.assertEqual(result.disposition, IngestionDisposition.QUEUED)
        payload = json.loads(self.repository.get_outbox(result.outbox_id).payload_json)
        self.assertEqual(payload["timestamp_ms"], 4294967295)


if __name__ == "__main__":
    unittest.main()
