import json
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.config import D2SecurityConfig
from djua_sms_gateway.gsm.sms_receiver import (
    ReceiveDisposition,
    SmsReceiver,
)
from djua_sms_gateway.mqtt.publisher import MqttPublisher
from djua_sms_gateway.services.ingestion import SmsIngestionService
from djua_sms_gateway.services.outbox_worker import MqttOutboxWorker
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import OutboxStatus
from tests.unit.gsm.fakes import FakeModem, cmti, modem_sms
from tests.unit.mqtt.fakes import FakeTransport


KEY = bytes.fromhex(
    "000102030405060708090A0B0C0D0E0F"
    "101112131415161718191A1B1C1D1E1F"
)
D2T = (
    "D2T,DJUA-KIN-000001,9IX,TM14E0,21I3V9,1E0,"
    "-99Q6,WU9O,9KG,DW,1Q,E1K,Y6,68,V4,1RX,3H,1VX,27W,9FL,3J,"
    "e0kwQvzx35g"
)
D2E = (
    "D2E,DJUA-KIN-000001,9IY,TM14E0,21I6CG,"
    "GX,-99Q6,WU9O,2N,07,G4ZfNcAaXGY"
)


class D2GsmMqttFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db")
        )
        security = D2SecurityConfig(
            mode="production",
            hmac_keys={"DJUA-KIN-000001": KEY},
            sender_bindings={
                "DJUA-KIN-000001": ("+243810000001",)
            },
        )
        self.ingestion = SmsIngestionService(
            self.repository,
            d2_security=security,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def receive_and_publish(self, body, *, index, mid):
        modem = FakeModem(
            [modem_sms(body, index=index)],
            [cmti(index)],
        )
        receive = SmsReceiver(
            modem,
            self.ingestion,
        ).poll_once()

        self.assertEqual(
            receive.disposition,
            ReceiveDisposition.STORED,
        )
        self.assertTrue(receive.deleted)
        self.assertEqual(modem.deleted, [("SM", index)])

        pending = self.repository.list_pending_outbox()
        selected = next(
            item for item in pending if item.sms_id == receive.sms_id
        )

        mqtt = FakeTransport(mids=[mid])
        MqttOutboxWorker(
            self.repository,
            mqtt,
            MqttPublisher(mqtt, self.repository),
        ).run_once()
        published_call = next(
            call for call in mqtt.calls
            if call[1] == selected.topic
        )
        mqtt.ack(mid)

        self.assertEqual(
            self.repository.get_outbox(selected.id).status,
            OutboxStatus.PUBLISHED,
        )
        return receive, selected, published_call

    def test_simulated_sim868_sms_d2t_to_sqlite_then_mqtt(self):
        _, outbox, call = self.receive_and_publish(
            D2T,
            index=21,
            mid=101,
        )
        self.assertEqual(
            outbox.topic,
            "djua/test/DJUA-KIN-000001/telemetry",
        )
        self.assertEqual(
            json.loads(call[2])["protocol"],
            "D2T",
        )

    def test_simulated_sim868_sms_d2e_to_sqlite_then_mqtt(self):
        _, outbox, call = self.receive_and_publish(
            D2E,
            index=22,
            mid=102,
        )
        self.assertEqual(
            outbox.topic,
            "djua/test/DJUA-KIN-000001/geofence/events",
        )
        payload = json.loads(call[2])
        self.assertEqual(payload["protocol"], "D2E")
        self.assertEqual(payload["event"], "GEOFENCE_EXIT")

    def test_security_rejection_is_durable_then_precisely_deleted(self):
        bad = D2T[:-1] + "A"
        modem = FakeModem(
            [modem_sms(bad, index=23)],
            [cmti(23)],
        )
        result = SmsReceiver(
            modem,
            self.ingestion,
        ).poll_once()
        self.assertEqual(
            result.disposition,
            ReceiveDisposition.INVALID,
        )
        self.assertTrue(result.deleted)
        self.assertEqual(modem.deleted, [("SM", 23)])
        self.assertEqual(self.repository.count_inbound(), 1)
        self.assertEqual(self.repository.count_outbox(), 0)
        inbound = self.repository.get_inbound(result.sms_id)
        self.assertEqual(inbound.security_status, "AUTH_INVALID")


if __name__ == "__main__":
    unittest.main()
