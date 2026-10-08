import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.config import DeliveryMode
from djua_sms_gateway.services.ingestion import (
    IngestionConfig,
    IngestionDisposition,
    SmsIngestionService,
)
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import (
    InboundStatus,
    OutboxStatus,
    RawSmsInput,
)
from tests.fixtures.d1_messages import D1_VALID_ALL


class DualOutputIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db")
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def raw(self, timestamp="t1"):
        return RawSmsInput(
            sender="+243810000001",
            raw_body=D1_VALID_ALL,
            modem_timestamp=timestamp,
        )

    def test_dual_mode_creates_two_durable_outboxes_with_same_payload(self):
        service = SmsIngestionService(
            self.repository,
            IngestionConfig(
                delivery_mode=DeliveryMode.MQTT_AND_HTTP,
                http_telemetry_url="http://backend.test/telemetry",
            ),
        )

        result = service.ingest(self.raw())

        self.assertEqual(
            result.disposition,
            IngestionDisposition.QUEUED,
        )
        self.assertIsNotNone(result.outbox_id)
        self.assertIsNotNone(result.http_outbox_id)
        mqtt = self.repository.get_outbox(result.outbox_id)
        http = self.repository.get_http_outbox(
            result.http_outbox_id
        )
        self.assertEqual(mqtt.status, OutboxStatus.PENDING)
        self.assertEqual(http.status, OutboxStatus.PENDING)
        self.assertEqual(mqtt.payload_json, http.payload_json)
        self.assertEqual(
            http.url,
            "http://backend.test/telemetry",
        )
        self.assertEqual(self.repository.count_outbox(), 1)
        self.assertEqual(self.repository.count_http_outbox(), 1)

    def test_dual_inbound_is_published_only_after_both_outputs_succeed(self):
        service = SmsIngestionService(
            self.repository,
            IngestionConfig(
                delivery_mode=DeliveryMode.MQTT_AND_HTTP,
                http_telemetry_url="http://backend.test/telemetry",
            ),
        )
        result = service.ingest(self.raw())

        self.repository.mark_outbox_published(result.outbox_id)
        self.assertEqual(
            self.repository.get_inbound(result.sms_id).status,
            InboundStatus.QUEUED,
        )

        self.repository.mark_http_outbox_published(
            result.http_outbox_id
        )
        self.assertEqual(
            self.repository.get_inbound(result.sms_id).status,
            InboundStatus.PUBLISHED,
        )

    def test_http_only_creates_no_mqtt_outbox(self):
        service = SmsIngestionService(
            self.repository,
            IngestionConfig(
                delivery_mode=DeliveryMode.HTTP_ONLY,
                http_telemetry_url="http://backend.test/telemetry",
            ),
        )

        result = service.ingest(self.raw())

        self.assertIsNone(result.outbox_id)
        self.assertIsNotNone(result.http_outbox_id)
        self.assertEqual(self.repository.count_outbox(), 0)
        self.assertEqual(self.repository.count_http_outbox(), 1)


if __name__ == "__main__":
    unittest.main()
