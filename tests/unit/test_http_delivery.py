from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.config import DeliveryMode
from djua_sms_gateway.http_delivery import (
    HttpOutboxWorker,
    HttpPublishDisposition,
    HttpPublisher,
)
from djua_sms_gateway.services.ingestion import (
    IngestionConfig,
    SmsIngestionService,
)
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import InboundStatus, OutboxStatus, RawSmsInput
from tests.fixtures.d1_messages import D1_VALID_ALL


class FakeHttpTransport:
    def __init__(self, *, status=200, error=None):
        self.status = status
        self.error = error
        self.calls = []

    def post(
        self,
        url,
        payload_json,
        *,
        headers,
        timeout_seconds,
    ):
        self.calls.append(
            (url, payload_json, dict(headers), timeout_seconds)
        )
        if self.error is not None:
            raise self.error
        return self.status


class HttpDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db")
        )
        self.ingestion = SmsIngestionService(
            self.repository,
            IngestionConfig(
                delivery_mode=DeliveryMode.HTTP_ONLY,
                http_telemetry_url="http://backend.test/telemetry",
            ),
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def ingest(self):
        return self.ingestion.ingest(
            RawSmsInput(
                sender="+243810000001",
                raw_body=D1_VALID_ALL,
                modem_timestamp="t1",
            )
        )

    def publisher(self, transport):
        return HttpPublisher(
            transport,
            self.repository,
            headers={"x-device-token": "secret"},
            timeout_seconds=3,
            clock=lambda: datetime(
                2026,
                10,
                8,
                tzinfo=timezone.utc,
            ),
        )

    def test_2xx_marks_http_outbox_and_inbound_published(self):
        result = self.ingest()
        self.assertIsNone(result.outbox_id)
        self.assertIsNotNone(result.http_outbox_id)

        transport = FakeHttpTransport(status=201)
        publish_result = self.publisher(transport).publish(
            self.repository.get_http_outbox(result.http_outbox_id)
        )

        self.assertEqual(
            publish_result.disposition,
            HttpPublishDisposition.PUBLISHED,
        )
        self.assertEqual(
            self.repository.get_http_outbox(
                result.http_outbox_id
            ).status,
            OutboxStatus.PUBLISHED,
        )
        self.assertEqual(
            self.repository.get_inbound(result.sms_id).status,
            InboundStatus.PUBLISHED,
        )
        self.assertEqual(
            transport.calls[0][2],
            {"x-device-token": "secret"},
        )

    def test_5xx_schedules_retry_without_losing_payload(self):
        result = self.ingest()
        before = self.repository.get_http_outbox(
            result.http_outbox_id
        ).payload_json
        transport = FakeHttpTransport(status=503)

        publish_result = self.publisher(transport).publish(
            self.repository.get_http_outbox(result.http_outbox_id)
        )
        updated = self.repository.get_http_outbox(
            result.http_outbox_id
        )

        self.assertEqual(
            publish_result.disposition,
            HttpPublishDisposition.RETRY_SCHEDULED,
        )
        self.assertEqual(updated.status, OutboxStatus.PENDING)
        self.assertEqual(updated.attempt_count, 1)
        self.assertIsNotNone(updated.next_attempt_at)
        self.assertEqual(updated.payload_json, before)
        self.assertEqual(
            self.repository.get_inbound(result.sms_id).status,
            InboundStatus.QUEUED,
        )

    def test_non_retryable_4xx_is_terminal(self):
        result = self.ingest()
        transport = FakeHttpTransport(status=400)

        publish_result = self.publisher(transport).publish(
            self.repository.get_http_outbox(result.http_outbox_id)
        )

        self.assertEqual(
            publish_result.disposition,
            HttpPublishDisposition.FAILED,
        )
        self.assertEqual(
            self.repository.get_http_outbox(
                result.http_outbox_id
            ).status,
            OutboxStatus.FAILED,
        )
        self.assertEqual(
            self.repository.get_inbound(result.sms_id).status,
            InboundStatus.FAILED,
        )

    def test_worker_drains_due_http_outbox(self):
        result = self.ingest()
        transport = FakeHttpTransport(status=200)
        worker = HttpOutboxWorker(
            self.repository,
            self.publisher(transport),
            clock=lambda: datetime(
                2026,
                10,
                8,
                12,
                tzinfo=timezone.utc,
            ),
        )

        run = worker.run_once()

        self.assertEqual(run.due, 1)
        self.assertEqual(run.published, 1)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(
            self.repository.get_http_outbox(
                result.http_outbox_id
            ).status,
            OutboxStatus.PUBLISHED,
        )


if __name__ == "__main__":
    unittest.main()
