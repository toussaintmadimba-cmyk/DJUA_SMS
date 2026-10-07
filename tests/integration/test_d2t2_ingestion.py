import json
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.config import D2SecurityConfig
from djua_sms_gateway.services.ingestion import (
    IngestionDisposition,
    SmsIngestionService,
)
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import InboundStatus, RawSmsInput


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

D2T2_DEV = (
    "D2T2,DJUA-KIN-000001,"
    "AAAACgAAAAAAAAAAAAUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAA,-"
)

D2T_SAME_SEQUENCE = (
    "D2T,DJUA-KIN-000001,9IX,TM14E0,21I3V9,1E0,"
    "-99Q6,WU9O,9KG,DW,1Q,E1K,Y6,68,V4,1RX,3H,1VX,27W,9FL,3J,"
    "e0kwQvzx35g"
)


class D2T2IngestionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"
        self.repository = SmsRepository(Database(self.path))
        self.security = D2SecurityConfig(
            mode="production",
            hmac_keys={"DJUA-KIN-000001": KEY},
            sender_bindings={
                "DJUA-KIN-000001": ("+243810000001",)
            },
        ).validate()
        self.service = SmsIngestionService(
            self.repository,
            d2_security=self.security,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def raw(
        self,
        body,
        *,
        sender="+243810000001",
        modem_timestamp="t1",
        gateway_received_at="2026-09-27T15:30:05.123000+00:00",
    ):
        return RawSmsInput(
            sender=sender,
            raw_body=body,
            modem_timestamp=modem_timestamp,
            gateway_received_at=gateway_received_at,
        )

    def test_d2t2_queues_existing_telemetry_topic_with_dc_load(self):
        result = self.service.ingest(self.raw(D2T2))
        self.assertEqual(result.disposition, IngestionDisposition.QUEUED)

        inbound = self.repository.get_inbound(result.sms_id)
        outbox = self.repository.get_outbox(result.outbox_id)
        payload = json.loads(outbox.payload_json)

        self.assertEqual(inbound.protocol_version, "D2T2")
        self.assertEqual(
            inbound.message_id,
            "D2:DJUA-KIN-000001:9IX",
        )
        self.assertEqual(inbound.auth_status, "VERIFIED")
        self.assertIsNone(inbound.security_status)
        self.assertEqual(
            outbox.topic,
            "djua/test/DJUA-KIN-000001/telemetry",
        )
        self.assertEqual(payload["protocol"], "D2T2")
        self.assertEqual(payload["sequence"], 12345)
        self.assertEqual(payload["battery"]["voltage_v"], 12.4)
        self.assertEqual(payload["solar"]["energy_interval_wh"], 11.2)
        self.assertEqual(payload["ac_load"]["active_power_w"], 244.5)
        self.assertEqual(
            payload["dc_load"],
            {
                "current_a": 3.2,
                "energy_interval_wh": 19.76,
                "power_w": 39.5,
                "voltage_v": 12.35,
            },
        )
        self.assertTrue(payload["validity"]["dc_load"])
        self.assertTrue(payload["validity"]["dc_load_energy"])

    def test_development_auth_dash_is_queued_not_verified(self):
        service = SmsIngestionService(
            self.repository,
            d2_security=D2SecurityConfig(mode="development"),
        )
        result = service.ingest(
            self.raw(D2T2_DEV, modem_timestamp="dev")
        )
        self.assertEqual(result.disposition, IngestionDisposition.QUEUED)
        payload = json.loads(
            self.repository.get_outbox(result.outbox_id).payload_json
        )
        self.assertEqual(payload["auth_status"], "NOT_VERIFIED")
        self.assertIsNone(payload["dc_load"]["power_w"])

    def test_bad_hmac_is_archived_without_outbox(self):
        bad = D2T2[:-1] + "A"
        result = self.service.ingest(
            self.raw(bad, modem_timestamp="bad")
        )
        self.assertEqual(result.disposition, IngestionDisposition.INVALID)
        inbound = self.repository.get_inbound(result.sms_id)
        self.assertEqual(inbound.status, InboundStatus.INVALID)
        self.assertEqual(inbound.security_status, "AUTH_INVALID")
        self.assertEqual(self.repository.count_outbox(), 0)

    def test_same_d2t2_message_replay_creates_one_outbox(self):
        first = self.service.ingest(
            self.raw(D2T2, modem_timestamp="t1")
        )
        second = self.service.ingest(
            self.raw(D2T2, modem_timestamp="t2")
        )
        self.assertEqual(first.disposition, IngestionDisposition.QUEUED)
        self.assertEqual(
            second.disposition,
            IngestionDisposition.DUPLICATE_LOGICAL,
        )
        self.assertEqual(second.duplicate_of_sms_id, first.sms_id)
        self.assertEqual(self.repository.count_outbox(), 1)

    def test_d2t_and_d2t2_share_the_same_sequence_namespace(self):
        old = self.service.ingest(
            self.raw(D2T_SAME_SEQUENCE, modem_timestamp="old")
        )
        new = self.service.ingest(
            self.raw(D2T2, modem_timestamp="new")
        )
        self.assertEqual(old.disposition, IngestionDisposition.QUEUED)
        self.assertEqual(new.disposition, IngestionDisposition.INVALID)
        self.assertEqual(new.duplicate_of_sms_id, old.sms_id)

        row = self.repository.get_inbound(new.sms_id)
        self.assertEqual(row.security_status, "MESSAGE_ID_CONFLICT")
        self.assertEqual(row.conflict_with_sms_id, old.sms_id)
        self.assertEqual(self.repository.count_outbox(), 1)


if __name__ == "__main__":
    unittest.main()
