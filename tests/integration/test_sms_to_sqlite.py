import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.gsm.sms_receiver import ReceiveDisposition, SmsReceiver
from djua_sms_gateway.services.ingestion import SmsIngestionService
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import OutboxStatus
from tests.fixtures.d1_messages import D1_VALID_ALL, replace_field
from tests.unit.gsm.fakes import FakeModem, cmti, modem_sms


class SmsToSqliteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db")
        )
        self.ingestion = SmsIngestionService(self.repository)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_cmti_to_sqlite_commit_then_cmgd(self):
        sms = modem_sms(D1_VALID_ALL, index=7)
        modem = FakeModem([sms], [cmti(7)])
        result = SmsReceiver(modem, self.ingestion).poll_once()
        self.assertEqual(result.disposition, ReceiveDisposition.STORED)
        self.assertTrue(result.deleted)
        self.assertEqual(modem.deleted, [("SM", 7)])
        outbox = self.repository.list_pending_outbox()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0].status, OutboxStatus.PENDING)

    def test_invalid_human_sms_is_archived_without_outbox_then_deleted(self):
        sms = modem_sms("BONJOUR", index=8)
        modem = FakeModem([sms], [cmti(8)])
        result = SmsReceiver(modem, self.ingestion).poll_once()
        self.assertEqual(result.disposition, ReceiveDisposition.INVALID)
        self.assertTrue(result.deleted)
        self.assertEqual(self.repository.count_inbound(), 1)
        self.assertEqual(self.repository.count_outbox(), 0)

    def test_mqtt_unavailable_does_not_block_modem_delete_after_sqlite(self):
        sms = modem_sms(D1_VALID_ALL, index=9)
        modem = FakeModem([sms], [cmti(9)])
        result = SmsReceiver(modem, self.ingestion).poll_once()
        self.assertTrue(result.deleted)
        outbox = self.repository.list_pending_outbox()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0].status, OutboxStatus.PENDING)
        self.assertIsNone(outbox[0].published_at)

    def test_three_devices_keep_sender_and_device_identity_separate(self):
        messages = []
        notifications = []
        for index in range(1, 4):
            device = f"DJUA-KIN-00000{index}"
            body = replace_field(D1_VALID_ALL, 1, device)
            body = replace_field(body, 2, f"9I{index}")
            messages.append(
                modem_sms(
                    body,
                    index=index,
                    sender=f"+24381000000{index}",
                    timestamp=f"transport-{index}",
                )
            )
            notifications.append(cmti(index))

        modem = FakeModem(messages, notifications)
        receiver = SmsReceiver(modem, self.ingestion)
        results = [receiver.poll_once() for _ in range(3)]
        self.assertTrue(all(item.deleted for item in results))
        self.assertEqual(self.repository.count_inbound(), 3)
        self.assertEqual(self.repository.count_outbox(), 3)
        for result, index in zip(results, range(1, 4)):
            inbound = self.repository.get_inbound(result.sms_id)
            self.assertEqual(inbound.sender, f"+24381000000{index}")
            self.assertEqual(inbound.device_id, f"DJUA-KIN-00000{index}")


if __name__ == "__main__":
    unittest.main()
