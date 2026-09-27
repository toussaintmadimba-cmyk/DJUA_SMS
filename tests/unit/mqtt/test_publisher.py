from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.mqtt.publisher import (
    MqttPublisher,
    PublishDisposition,
    compute_backoff_seconds,
)
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import OutboxStatus
from tests.unit.mqtt.fakes import FakeTransport, seed_outbox


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db")
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def publisher(self, client, **changes):
        return MqttPublisher(
            client,
            self.repository,
            clock=lambda: datetime(2026, 9, 28, tzinfo=timezone.utc),
            **changes,
        )

    def test_puback_marks_only_matching_outbox(self):
        first = seed_outbox(self.repository, key="1")
        second = seed_outbox(self.repository, key="2")
        client = FakeTransport(mids=[10, 11])
        publisher = self.publisher(client)
        publisher.publish(first)
        publisher.publish(second)
        client.ack(11)
        self.assertEqual(
            self.repository.get_outbox(second.id).status,
            OutboxStatus.PUBLISHED,
        )
        self.assertEqual(
            self.repository.get_outbox(first.id).status,
            OutboxStatus.PENDING,
        )
        client.ack(10)
        self.assertEqual(
            self.repository.get_outbox(first.id).status,
            OutboxStatus.PUBLISHED,
        )

    def test_early_ack_race_is_handled(self):
        outbox = seed_outbox(self.repository, key="1")
        client = FakeTransport(mids=[7], auto_ack=True)
        result = self.publisher(client).publish(outbox)
        self.assertEqual(result.disposition, PublishDisposition.ACKED)
        self.assertEqual(
            self.repository.get_outbox(outbox.id).status,
            OutboxStatus.PUBLISHED,
        )

    def test_publishes_exact_outbox_topic_payload_qos_retain(self):
        outbox = seed_outbox(
            self.repository,
            key="1",
            topic="custom/topic",
            payload='{"solar":{"power_w":null}}',
            qos=1,
            retain=False,
        )
        client = FakeTransport(mids=[3])
        self.publisher(client).publish(outbox)
        self.assertEqual(
            client.calls[0][1:],
            (
                "custom/topic",
                '{"solar":{"power_w":null}}',
                1,
                False,
            ),
        )

    def test_immediate_publish_failure_schedules_retry(self):
        outbox = seed_outbox(self.repository, key="1")
        client = FakeTransport(connected=False)
        result = self.publisher(client).publish(outbox)
        self.assertEqual(result.disposition, PublishDisposition.FAILED)
        updated = self.repository.get_outbox(outbox.id)
        self.assertEqual(updated.attempt_count, 1)
        self.assertIsNotNone(updated.next_attempt_at)
        self.assertEqual(updated.status, OutboxStatus.PENDING)

    def test_timeout_schedules_retry_and_late_ack_is_ignored(self):
        outbox = seed_outbox(self.repository, key="1")
        ticks = iter([0.0, 20.0])
        client = FakeTransport(mids=[5])
        publisher = self.publisher(
            client,
            publish_timeout_seconds=10,
            monotonic=lambda: next(ticks),
        )
        publisher.publish(outbox)
        self.assertEqual(publisher.expire_timeouts(), [outbox.id])
        client.ack(5)
        updated = self.repository.get_outbox(outbox.id)
        self.assertEqual(updated.status, OutboxStatus.PENDING)
        self.assertEqual(updated.attempt_count, 1)

    def test_backoff_is_exponential_and_capped(self):
        self.assertEqual(
            compute_backoff_seconds(0, base_seconds=2, max_seconds=10),
            2,
        )
        self.assertEqual(
            compute_backoff_seconds(1, base_seconds=2, max_seconds=10),
            4,
        )
        self.assertEqual(
            compute_backoff_seconds(10, base_seconds=2, max_seconds=10),
            10,
        )


if __name__ == "__main__":
    unittest.main()
