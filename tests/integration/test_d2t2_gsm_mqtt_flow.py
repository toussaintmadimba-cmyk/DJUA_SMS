import json
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.config import D2SecurityConfig
from djua_sms_gateway.gsm.sms_receiver import ReceiveDisposition, SmsReceiver
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

D2T2 = (
    "D2T2,DJUA-KIN-000001,"
    "AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAAR"
    "gj9B9AmNBZ4ABfgjA-AyAAGLAAHuAH_A,"
    "rHcRllcP4gs"
)


class D2T2GsmMqttFlowTests(unittest.TestCase):
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

    def test_simulated_sim868_d2t2_reaches_mqtt_with_dc_load(self):
        modem = FakeModem(
            [modem_sms(D2T2, index=31)],
            [cmti(31)],
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
        self.assertEqual(modem.deleted, [("SM", 31)])

        pending = self.repository.list_pending_outbox()
        self.assertEqual(len(pending), 1)
        outbox = pending[0]
        self.assertEqual(
            outbox.topic,
            "djua/test/DJUA-KIN-000001/telemetry",
        )

        mqtt = FakeTransport(mids=[301])
        MqttOutboxWorker(
            self.repository,
            mqtt,
            MqttPublisher(mqtt, self.repository),
        ).run_once()

        published_call = next(
            call for call in mqtt.calls if call[1] == outbox.topic
        )
        payload = json.loads(published_call[2])
        self.assertEqual(payload["protocol"], "D2T2")
        self.assertEqual(payload["dc_load"]["voltage_v"], 12.35)
        self.assertEqual(payload["dc_load"]["current_a"], 3.2)

        mqtt.ack(301)
        self.assertEqual(
            self.repository.get_outbox(outbox.id).status,
            OutboxStatus.PUBLISHED,
        )


if __name__ == "__main__":
    unittest.main()
