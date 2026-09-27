import json
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.mqtt.publisher import MqttPublisher
from djua_sms_gateway.services.ingestion import SmsIngestionService
from djua_sms_gateway.services.outbox_worker import MqttOutboxWorker
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import (
    InboundStatus,
    OutboxStatus,
    RawSmsInput,
)
from tests.fixtures.d1_messages import (
    D1_SOLAR_INVALID,
    D1_SOLAR_ZERO_VALID,
    D1_VALID_ALL,
    replace_field,
)
from tests.unit.mqtt.fakes import FakeTransport


class MqttOutboxFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"
        self.repository = SmsRepository(Database(self.path))
        self.ingestion = SmsIngestionService(self.repository)

    def tearDown(self):
        self.tempdir.cleanup()

    def ingest(self, body, index="1"):
        return self.ingestion.ingest(
            RawSmsInput(
                sender=f"+243{index}",
                raw_body=body,
                modem_timestamp=f"t{index}",
            )
        )

    def test_d1_to_puback_then_restart_does_not_republish(self):
        result = self.ingest(D1_VALID_ALL)
        client = FakeTransport(mids=[7])
        publisher = MqttPublisher(client, self.repository)
        worker = MqttOutboxWorker(self.repository, client, publisher)
        run = worker.run_once()
        self.assertEqual(run.started, 1)
        client.ack(7)

        self.assertEqual(
            self.repository.get_outbox(result.outbox_id).status,
            OutboxStatus.PUBLISHED,
        )
        self.assertEqual(
            self.repository.get_inbound(result.sms_id).status,
            InboundStatus.PUBLISHED,
        )

        restarted = SmsRepository(Database(self.path))
        client2 = FakeTransport()
        worker2 = MqttOutboxWorker(
            restarted,
            client2,
            MqttPublisher(client2, restarted),
        )
        self.assertEqual(worker2.run_once().due, 0)
        self.assertEqual(client2.calls, [])

    def test_transport_does_not_modify_solar_null_or_zero_payload(self):
        first = self.ingest(D1_SOLAR_INVALID, "1")
        second = self.ingest(
            replace_field(D1_SOLAR_ZERO_VALID, 2, "9IY"),
            "2",
        )
        client = FakeTransport(mids=[1, 2])
        worker = MqttOutboxWorker(
            self.repository,
            client,
            MqttPublisher(client, self.repository),
        )
        worker.run_once()
        payloads = [json.loads(call[2]) for call in client.calls]
        self.assertIsNone(payloads[0]["solar"]["power_w"])
        self.assertEqual(payloads[1]["solar"]["power_w"], 0.0)
        self.assertEqual(
            client.calls[0][2],
            self.repository.get_outbox(first.outbox_id).payload_json,
        )
        self.assertEqual(
            client.calls[1][2],
            self.repository.get_outbox(second.outbox_id).payload_json,
        )

    def test_topic_injection_device_id_is_rejected_before_outbox(self):
        bad = replace_field(D1_VALID_ALL, 1, "DJUA-KIN-000001/#")
        result = self.ingest(bad, "9")
        self.assertEqual(result.disposition.value, "INVALID")
        self.assertEqual(self.repository.count_outbox(), 0)

    def test_multi_device_one_gateway_client_publishes_exact_topics(self):
        expected = []
        for index in range(1, 4):
            device = f"DJUA-KIN-00000{index}"
            message = replace_field(D1_VALID_ALL, 1, device)
            message = replace_field(message, 2, f"9I{index}")
            result = self.ingest(message, str(index))
            expected.append(
                self.repository.get_outbox(result.outbox_id).topic
            )
        client = FakeTransport(mids=[10, 11, 12])
        MqttOutboxWorker(
            self.repository,
            client,
            MqttPublisher(client, self.repository),
        ).run_once()
        self.assertEqual(
            [call[1] for call in client.calls],
            expected,
        )


if __name__ == "__main__":
    unittest.main()
