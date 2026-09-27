import json
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.services.ingestion import IngestionDisposition, SmsIngestionService
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import OutboxStatus, RawSmsInput
from tests.fixtures.d1_messages import D1_VALID_ALL


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_end_to_end_simulated_restart_preserves_identical_payload(self) -> None:
        first_repository = SmsRepository(Database(self.path))
        service = SmsIngestionService(first_repository)
        result = service.ingest(
            RawSmsInput(
                sender="+243810000001",
                modem_timestamp="26/09/27,16:30:10+04",
                gateway_received_at="2026-09-27T15:30:11+00:00",
                raw_body=D1_VALID_ALL,
            )
        )
        self.assertEqual(result.disposition, IngestionDisposition.QUEUED)
        before = first_repository.get_outbox(result.outbox_id)

        restarted_repository = SmsRepository(Database(self.path))
        pending = restarted_repository.list_pending_outbox()
        self.assertEqual(len(pending), 1)
        after = pending[0]
        self.assertEqual(after.status, OutboxStatus.PENDING)
        self.assertEqual(after.payload_json, before.payload_json)
        self.assertEqual(json.loads(after.payload_json), json.loads(before.payload_json))

    def test_pending_is_not_deleted_on_startup(self) -> None:
        repository = SmsRepository(Database(self.path))
        service = SmsIngestionService(repository)
        result = service.ingest(RawSmsInput("+2431", D1_VALID_ALL, "t1"))
        self.assertEqual(result.disposition, IngestionDisposition.QUEUED)

        restarted = SmsRepository(Database(self.path))
        first_read = restarted.list_pending_outbox()
        second_read = restarted.list_pending_outbox()
        self.assertEqual(len(first_read), 1)
        self.assertEqual(len(second_read), 1)
        self.assertEqual(first_read[0].id, second_read[0].id)


if __name__ == "__main__":
    unittest.main()
