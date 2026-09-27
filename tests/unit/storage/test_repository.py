import json
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.protocol.normalizer import normalize_to_mqtt
from djua_sms_gateway.protocol.parser import parse_d1
from djua_sms_gateway.protocol.validator import validate_telemetry
from djua_sms_gateway.storage import Database
from djua_sms_gateway.storage.models import (
    InboundStatus,
    OutboxStatus,
    QueueDisposition,
    RawSmsInput,
    StoreDisposition,
)
from djua_sms_gateway.storage.repository import SmsRepository
from tests.fixtures.d1_messages import D1_VALID_ALL


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"
        self.repository = SmsRepository(Database(self.path))

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def raw(self, **changes) -> RawSmsInput:
        values = {
            "sender": "+243810000001",
            "modem_timestamp": "26/09/27,16:30:10+04",
            "gateway_received_at": "2026-09-27T15:30:11+00:00",
            "raw_body": D1_VALID_ALL,
        }
        values.update(changes)
        return RawSmsInput(**values)

    def queue_one(self):
        stored = self.repository.store_raw_sms(self.raw())
        telemetry = parse_d1(D1_VALID_ALL)
        validation = validate_telemetry(telemetry)
        payload_json = json.dumps(
            normalize_to_mqtt(telemetry).to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return self.repository.queue_valid_sms(
            stored.record.id,
            telemetry,
            validation,
            topic="djua/test/DJUA-KIN-000001/telemetry",
            payload_json=payload_json,
        )

    def test_store_raw_sms_commits_and_returns_record(self) -> None:
        result = self.repository.store_raw_sms(self.raw())
        self.assertEqual(result.disposition, StoreDisposition.STORED)
        self.assertTrue(result.durably_stored)
        self.assertEqual(result.record.status, InboundStatus.RECEIVED)
        self.assertEqual(result.record.raw_body, D1_VALID_ALL)

    def test_utf8_raw_body_and_null_modem_timestamp_are_stored(self) -> None:
        raw = self.raw(raw_body="D1,diagnostic-é", modem_timestamp=None)
        result = self.repository.store_raw_sms(raw)
        loaded = self.repository.get_inbound(result.record.id)
        self.assertEqual(loaded.raw_body, "D1,diagnostic-é")
        self.assertIsNone(loaded.modem_timestamp)

    def test_queue_valid_sms_creates_pending_outbox(self) -> None:
        queued = self.queue_one()
        self.assertEqual(queued.disposition, QueueDisposition.QUEUED)
        self.assertEqual(queued.outbox.status, OutboxStatus.PENDING)
        self.assertEqual(queued.outbox.qos, 1)
        self.assertFalse(queued.outbox.retain)
        inbound = self.repository.get_inbound(queued.sms_id)
        self.assertEqual(inbound.status, InboundStatus.QUEUED)

    def test_payload_json_round_trips(self) -> None:
        queued = self.queue_one()
        parsed = json.loads(queued.outbox.payload_json)
        self.assertEqual(parsed["kit_id"], "DJUA-KIN-000001")
        self.assertNotIn("protocol", parsed)
        self.assertNotIn("flags", parsed)

    def test_pending_outbox_survives_repository_reopen(self) -> None:
        queued = self.queue_one()
        reopened = SmsRepository(Database(self.path))
        pending = reopened.list_pending_outbox()
        self.assertEqual([item.id for item in pending], [queued.outbox.id])
        self.assertEqual(pending[0].payload_json, queued.outbox.payload_json)

    def test_mark_outbox_published_updates_both_tables(self) -> None:
        queued = self.queue_one()
        updated = self.repository.mark_outbox_published(
            queued.outbox.id,
            published_at="2026-09-27T16:00:00+00:00",
        )
        self.assertEqual(updated.status, OutboxStatus.PUBLISHED)
        self.assertEqual(updated.published_at, "2026-09-27T16:00:00+00:00")
        inbound = self.repository.get_inbound(queued.sms_id)
        self.assertEqual(inbound.status, InboundStatus.PUBLISHED)
        self.assertEqual(self.repository.list_pending_outbox(), [])

    def test_publish_failure_preserves_payload_and_increments_attempt(self) -> None:
        queued = self.queue_one()
        before = queued.outbox.payload_json
        failed = self.repository.record_publish_failure(
            queued.outbox.id,
            error="broker unavailable",
            next_attempt_at="2026-09-27T16:10:00+00:00",
        )
        self.assertEqual(failed.status, OutboxStatus.PENDING)
        self.assertEqual(failed.attempt_count, 1)
        self.assertEqual(failed.last_error, "broker unavailable")
        self.assertEqual(failed.payload_json, before)

    def test_terminal_failure_is_retained_not_deleted(self) -> None:
        queued = self.queue_one()
        failed = self.repository.record_publish_failure(
            queued.outbox.id,
            error="manual terminal failure",
            terminal=True,
        )
        self.assertEqual(failed.status, OutboxStatus.FAILED)
        self.assertIsNotNone(self.repository.get_outbox(failed.id))
        self.assertEqual(
            self.repository.get_inbound(queued.sms_id).status,
            InboundStatus.FAILED,
        )

    def test_atomic_queue_rolls_back_if_outbox_insert_fails(self) -> None:
        stored = self.repository.store_raw_sms(self.raw())
        telemetry = parse_d1(D1_VALID_ALL)
        validation = validate_telemetry(telemetry)
        with self.assertRaises(Exception):
            self.repository.queue_valid_sms(
                stored.record.id,
                telemetry,
                validation,
                topic="djua/test/DJUA-KIN-000001/telemetry",
                payload_json="{}",
                qos=9,
            )
        inbound = self.repository.get_inbound(stored.record.id)
        self.assertEqual(inbound.status, InboundStatus.RECEIVED)
        self.assertIsNone(inbound.logical_dedupe_key)
        self.assertEqual(self.repository.count_outbox(), 0)


if __name__ == "__main__":
    unittest.main()
