from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.mqtt.publisher import MqttPublisher
from djua_sms_gateway.services.outbox_worker import MqttOutboxWorker
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import OutboxStatus
from tests.unit.mqtt.fakes import FakeTransport, seed_outbox


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db")
        )
        self.now = datetime(2026, 9, 28, tzinfo=timezone.utc)

    def tearDown(self):
        self.tempdir.cleanup()

    def worker(self, client):
        publisher = MqttPublisher(
            client,
            self.repository,
            clock=lambda: self.now,
            retry_base_seconds=2,
            retry_max_seconds=30,
        )
        return (
            MqttOutboxWorker(
                self.repository,
                client,
                publisher,
                clock=lambda: self.now,
            ),
            publisher,
        )

    def test_broker_offline_preserves_three_messages_and_schedules_retry(self):
        rows = [seed_outbox(self.repository, key=str(i)) for i in range(1, 4)]
        client = FakeTransport(
            connected=False,
            connect_error=RuntimeError("broker offline"),
        )
        worker, _ = self.worker(client)
        result = worker.run_once()
        self.assertTrue(result.connect_failed)
        self.assertEqual(result.failed, 3)
        self.assertEqual(self.repository.count_outbox(), 3)
        for row in rows:
            updated = self.repository.get_outbox(row.id)
            self.assertEqual(updated.status, OutboxStatus.PENDING)
            self.assertEqual(updated.attempt_count, 1)
            self.assertIsNotNone(updated.next_attempt_at)

    def test_reconnect_retries_due_messages(self):
        outbox = seed_outbox(self.repository, key="1")
        client = FakeTransport(
            connected=False,
            connect_error=RuntimeError("offline"),
        )
        worker, _ = self.worker(client)
        worker.run_once()
        client.connect_error = None
        self.now += timedelta(seconds=3)
        result = worker.run_once()
        self.assertEqual(result.started, 1)
        client.ack(client.calls[-1][0])
        self.assertEqual(
            self.repository.get_outbox(outbox.id).status,
            OutboxStatus.PUBLISHED,
        )

    def test_order_is_outbox_id_ascending(self):
        rows = [seed_outbox(self.repository, key=str(i)) for i in range(1, 4)]
        client = FakeTransport(mids=[10, 11, 12])
        worker, _ = self.worker(client)
        worker.run_once()
        self.assertEqual(
            [call[1] for call in client.calls],
            [row.topic for row in rows],
        )

    def test_second_run_does_not_duplicate_inflight(self):
        seed_outbox(self.repository, key="1")
        client = FakeTransport(mids=[10, 11])
        worker, _ = self.worker(client)
        first = worker.run_once()
        second = worker.run_once()
        self.assertEqual(first.started, 1)
        self.assertEqual(second.skipped_in_flight, 1)
        self.assertEqual(len(client.calls), 1)

    def test_disconnect_keeps_inflight_pending_and_ack_after_reconnect_completes(self):
        outbox = seed_outbox(self.repository, key="1")
        client = FakeTransport(mids=[10])
        worker, _ = self.worker(client)
        worker.run_once()
        client.drop()
        self.assertEqual(
            self.repository.get_outbox(outbox.id).status,
            OutboxStatus.PENDING,
        )
        client.connect()
        client.ack(10)
        self.assertEqual(
            self.repository.get_outbox(outbox.id).status,
            OutboxStatus.PUBLISHED,
        )

    def test_shutdown_disconnects_client(self):
        client = FakeTransport()
        worker, _ = self.worker(client)
        worker.shutdown()
        self.assertEqual(client.disconnect_calls, 1)


if __name__ == "__main__":
    unittest.main()
