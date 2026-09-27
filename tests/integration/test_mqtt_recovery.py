import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.mqtt.publisher import MqttPublisher
from djua_sms_gateway.services.ingestion import SmsIngestionService
from djua_sms_gateway.services.outbox_worker import MqttOutboxWorker
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import OutboxStatus, RawSmsInput
from tests.fixtures.d1_messages import D1_VALID_ALL
from tests.unit.mqtt.fakes import FakeTransport


class FailAckCommitRepository(SmsRepository):
    def __init__(self, database):
        super().__init__(database)
        self.fail_once = True

    def mark_outbox_published(self, outbox_id, *, published_at=None):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated crash before SQLite commit")
        return super().mark_outbox_published(
            outbox_id,
            published_at=published_at,
        )


class MqttRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"

    def tearDown(self):
        self.tempdir.cleanup()

    def seed(self, repository):
        return SmsIngestionService(repository).ingest(
            RawSmsInput("+2431", D1_VALID_ALL, "t1")
        )

    def test_crash_before_puback_keeps_pending_and_republishes(self):
        repository = SmsRepository(Database(self.path))
        result = self.seed(repository)
        client = FakeTransport(mids=[10])
        MqttOutboxWorker(
            repository,
            client,
            MqttPublisher(client, repository),
        ).run_once()

        self.assertEqual(
            repository.get_outbox(result.outbox_id).status,
            OutboxStatus.PENDING,
        )

        restarted = SmsRepository(Database(self.path))
        client2 = FakeTransport(mids=[20])
        MqttOutboxWorker(
            restarted,
            client2,
            MqttPublisher(client2, restarted),
        ).run_once()
        self.assertEqual(len(client2.calls), 1)
        client2.ack(20)
        self.assertEqual(
            restarted.get_outbox(result.outbox_id).status,
            OutboxStatus.PUBLISHED,
        )

    def test_puback_then_commit_failure_allows_at_least_once_republish(self):
        repository = FailAckCommitRepository(Database(self.path))
        result = self.seed(repository)
        client = FakeTransport(mids=[10])
        MqttOutboxWorker(
            repository,
            client,
            MqttPublisher(client, repository),
        ).run_once()
        client.ack(10)

        self.assertEqual(
            repository.get_outbox(result.outbox_id).status,
            OutboxStatus.PENDING,
        )

        restarted = SmsRepository(Database(self.path))
        client2 = FakeTransport(mids=[20])
        MqttOutboxWorker(
            restarted,
            client2,
            MqttPublisher(client2, restarted),
        ).run_once()
        self.assertEqual(len(client2.calls), 1)
        client2.ack(20)
        self.assertEqual(
            restarted.get_outbox(result.outbox_id).status,
            OutboxStatus.PUBLISHED,
        )


if __name__ == "__main__":
    unittest.main()
