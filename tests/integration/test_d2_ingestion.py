import json
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.config import D2SecurityConfig
from djua_sms_gateway.protocol.d2 import calculate_hmac_tag
from djua_sms_gateway.services.ingestion import (
    IngestionDisposition,
    SmsIngestionService,
)
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import InboundStatus, RawSmsInput
from tests.fixtures.d1_messages import D1_VALID_ALL


KEY = bytes.fromhex(
    "000102030405060708090A0B0C0D0E0F"
    "101112131415161718191A1B1C1D1E1F"
)
D2T = (
    "D2T,DJUA-KIN-000001,9IX,TM14E0,21I3V9,1E0,"
    "-99Q6,WU9O,9KG,DW,1Q,E1K,Y6,68,V4,1RX,3H,1VX,27W,9FL,3J,"
    "e0kwQvzx35g"
)
D2E_GX = (
    "D2E,DJUA-KIN-000001,9IY,TM14E0,21I6CG,"
    "GX,-99Q6,WU9O,2N,07,G4ZfNcAaXGY"
)
D2E_GE = (
    "D2E,DJUA-KIN-000001,9IZ,TM14FO,21JGN4,"
    "GE,-99PW,WU94,5,07,veO767hIj34"
)


class D2IngestionTests(unittest.TestCase):
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

    def test_d2t_queues_backend_contract_and_preserves_first_gateway_time(self):
        result = self.service.ingest(self.raw(D2T))
        self.assertEqual(
            result.disposition,
            IngestionDisposition.QUEUED,
        )
        inbound = self.repository.get_inbound(result.sms_id)
        outbox = self.repository.get_outbox(result.outbox_id)
        payload = json.loads(outbox.payload_json)

        self.assertEqual(inbound.protocol_version, "D2T")
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
        self.assertEqual(payload["protocol"], "D2T")
        self.assertEqual(payload["sequence"], 12345)
        self.assertEqual(payload["timestamp_ms"], 123456789)
        self.assertEqual(payload["uptime_ms"], 123456789)
        self.assertEqual(
            payload["gateway_received_at"],
            "2026-09-27T15:30:05.123000+00:00",
        )
        self.assertEqual(payload["solar"]["energy_interval_wh"], 11.2)

        before = outbox.payload_json
        self.repository.record_publish_failure(
            outbox.id,
            error="offline",
            next_attempt_at="2026-09-27T16:00:00+00:00",
        )
        self.assertEqual(
            self.repository.get_outbox(outbox.id).payload_json,
            before,
        )

    def test_d2e_gx_and_ge_use_event_topic_and_derived_state(self):
        gx = self.service.ingest(
            self.raw(D2E_GX, modem_timestamp="gx")
        )
        ge = self.service.ingest(
            self.raw(D2E_GE, modem_timestamp="ge")
        )

        gx_payload = json.loads(
            self.repository.get_outbox(gx.outbox_id).payload_json
        )
        ge_payload = json.loads(
            self.repository.get_outbox(ge.outbox_id).payload_json
        )

        self.assertEqual(
            self.repository.get_outbox(gx.outbox_id).topic,
            "djua/test/DJUA-KIN-000001/geofence/events",
        )
        self.assertEqual(gx_payload["event"], "GEOFENCE_EXIT")
        self.assertEqual(gx_payload["state"], "OUTSIDE")
        self.assertEqual(ge_payload["event"], "GEOFENCE_ENTER")
        self.assertEqual(ge_payload["state"], "INSIDE")

    def test_development_auth_dash_is_queued_as_not_verified(self):
        service = SmsIngestionService(
            self.repository,
            d2_security=D2SecurityConfig(mode="development"),
        )
        raw = (
            "D2E,DJUA-KIN-000001,A,-,0,GX,-,-,-,00,-"
        )
        result = service.ingest(
            self.raw(raw, modem_timestamp="dev")
        )
        payload = json.loads(
            self.repository.get_outbox(result.outbox_id).payload_json
        )
        self.assertEqual(payload["auth_status"], "NOT_VERIFIED")

    def test_bad_hmac_is_archived_without_outbox(self):
        bad = D2T[:-1] + "A"
        result = self.service.ingest(
            self.raw(bad, modem_timestamp="bad")
        )
        self.assertEqual(
            result.disposition,
            IngestionDisposition.INVALID,
        )
        inbound = self.repository.get_inbound(result.sms_id)
        self.assertEqual(inbound.status, InboundStatus.INVALID)
        self.assertEqual(inbound.security_status, "AUTH_INVALID")
        self.assertEqual(self.repository.count_outbox(), 0)

    def test_sender_mismatch_is_archived_without_outbox(self):
        result = self.service.ingest(
            self.raw(
                D2E_GX,
                sender="+243899999999",
                modem_timestamp="sender-mismatch",
            )
        )
        self.assertEqual(
            result.disposition,
            IngestionDisposition.INVALID,
        )
        inbound = self.repository.get_inbound(result.sms_id)
        self.assertEqual(
            inbound.security_status,
            "SENDER_DEVICE_MISMATCH",
        )
        self.assertEqual(inbound.auth_status, "VERIFIED")
        self.assertEqual(self.repository.count_outbox(), 0)

    def test_same_message_id_same_content_is_one_outbox(self):
        first = self.service.ingest(
            self.raw(D2T, modem_timestamp="t1")
        )
        second = self.service.ingest(
            self.raw(D2T, modem_timestamp="t2")
        )
        self.assertEqual(
            first.disposition,
            IngestionDisposition.QUEUED,
        )
        self.assertEqual(
            second.disposition,
            IngestionDisposition.DUPLICATE_LOGICAL,
        )
        self.assertEqual(second.duplicate_of_sms_id, first.sms_id)
        self.assertEqual(self.repository.count_inbound(), 2)
        self.assertEqual(self.repository.count_outbox(), 1)

    def test_same_message_id_different_content_is_explicit_conflict(self):
        first = self.service.ingest(
            self.raw(D2T, modem_timestamp="t1")
        )
        signed = D2T.rsplit(",", 1)[0].replace(
            ",21I3V9,",
            ",21I3VA,",
        )
        conflicting = signed + "," + calculate_hmac_tag(
            signed,
            KEY,
        )
        second = self.service.ingest(
            self.raw(
                conflicting,
                modem_timestamp="t2",
            )
        )

        self.assertEqual(
            second.disposition,
            IngestionDisposition.INVALID,
        )
        self.assertEqual(
            second.duplicate_of_sms_id,
            first.sms_id,
        )
        row = self.repository.get_inbound(second.sms_id)
        self.assertEqual(
            row.security_status,
            "MESSAGE_ID_CONFLICT",
        )
        self.assertEqual(
            row.conflict_with_sms_id,
            first.sms_id,
        )
        self.assertEqual(self.repository.count_outbox(), 1)

    def test_d1_contract_remains_historical(self):
        result = self.service.ingest(
            self.raw(
                D1_VALID_ALL,
                modem_timestamp="legacy",
            )
        )
        payload = json.loads(
            self.repository.get_outbox(result.outbox_id).payload_json
        )
        self.assertNotIn("protocol", payload)
        self.assertNotIn("message_id", payload)
        self.assertEqual(
            self.repository.get_inbound(result.sms_id).protocol_version,
            "D1",
        )


if __name__ == "__main__":
    unittest.main()
