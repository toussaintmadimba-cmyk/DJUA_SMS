import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.gsm.serial_transport import SerialTransportError
from djua_sms_gateway.gsm.sms_receiver import ReceiveDisposition, SmsReceiver
from djua_sms_gateway.services.ingestion import SmsIngestionService
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import InboundStatus
from tests.fixtures.d1_messages import D1_VALID_ALL
from tests.unit.gsm.fakes import FakeModem, cmti, modem_sms


class RaisingIngestion:
    def ingest(self, raw):
        raise RuntimeError("simulated SQLite failure")


class SmsReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db")
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def receiver(self, modem):
        return SmsReceiver(modem, SmsIngestionService(self.repository))

    def test_valid_d1_is_persisted_before_precise_delete(self):
        sms = modem_sms(D1_VALID_ALL, index=7)
        modem = FakeModem([sms])
        result = self.receiver(modem).process_sms(sms)
        self.assertEqual(result.disposition, ReceiveDisposition.STORED)
        self.assertTrue(result.deleted)
        self.assertEqual(modem.deleted, [("SM", 7)])
        self.assertEqual(self.repository.count_inbound(), 1)
        self.assertEqual(self.repository.count_outbox(), 1)

    def test_invalid_non_d1_is_archived_then_deletable(self):
        sms = modem_sms("BONJOUR", index=2)
        modem = FakeModem([sms])
        result = self.receiver(modem).process_sms(sms)
        self.assertEqual(result.disposition, ReceiveDisposition.INVALID)
        self.assertTrue(result.deleted)
        inbound = self.repository.get_inbound(result.sms_id)
        self.assertEqual(inbound.status, InboundStatus.INVALID)
        self.assertEqual(inbound.raw_body, "BONJOUR")
        self.assertEqual(self.repository.count_outbox(), 0)

    def test_duplicate_raw_deletes_replayed_modem_copy_without_second_outbox(self):
        sms = modem_sms(D1_VALID_ALL, index=7)
        modem = FakeModem([sms])
        receiver = self.receiver(modem)
        first = receiver.process_sms(sms)
        second = receiver.process_sms(sms)
        self.assertEqual(first.disposition, ReceiveDisposition.STORED)
        self.assertEqual(second.disposition, ReceiveDisposition.DUPLICATE_RAW)
        self.assertEqual(self.repository.count_inbound(), 1)
        self.assertEqual(self.repository.count_outbox(), 1)
        self.assertEqual(modem.deleted, [("SM", 7), ("SM", 7)])

    def test_sqlite_failure_forbids_cmgd(self):
        sms = modem_sms(D1_VALID_ALL, index=3)
        modem = FakeModem([sms])
        receiver = SmsReceiver(modem, RaisingIngestion())
        result = receiver.process_sms(sms)
        self.assertEqual(result.disposition, ReceiveDisposition.PERSISTENCE_FAILED)
        self.assertFalse(result.deleted)
        self.assertEqual(modem.deleted, [])

    def test_cmgd_failure_does_not_rollback_persistence(self):
        sms = modem_sms(D1_VALID_ALL, index=4)
        modem = FakeModem([sms])
        modem.delete_error = RuntimeError("CMGD failed")
        result = self.receiver(modem).process_sms(sms)
        self.assertEqual(result.disposition, ReceiveDisposition.DELETE_FAILED)
        self.assertFalse(result.deleted)
        self.assertEqual(self.repository.count_inbound(), 1)
        self.assertEqual(self.repository.count_outbox(), 1)

    def test_serial_loss_during_read_is_propagated_for_gateway_reconnect(self):
        modem = FakeModem(notifications=[cmti(6)])
        modem.read_error = SerialTransportError("USB disconnected")
        with self.assertRaises(SerialTransportError):
            self.receiver(modem).poll_once()
        self.assertEqual(modem.deleted, [])

    def test_serial_loss_during_delete_occurs_after_persistence_and_is_propagated(self):
        sms = modem_sms(D1_VALID_ALL, index=6)
        modem = FakeModem([sms])
        modem.delete_error = SerialTransportError("USB disconnected")
        with self.assertRaises(SerialTransportError):
            self.receiver(modem).process_sms(sms)
        self.assertEqual(self.repository.count_inbound(), 1)
        self.assertEqual(self.repository.count_outbox(), 1)
        self.assertEqual(modem.deleted, [])

    def test_read_failure_does_not_delete(self):
        modem = FakeModem(notifications=[cmti(5)])
        modem.read_error = RuntimeError("CMGR failed")
        result = self.receiver(modem).poll_once()
        self.assertEqual(result.disposition, ReceiveDisposition.READ_FAILED)
        self.assertEqual(modem.deleted, [])

    def test_three_successive_notifications_do_not_mix_sms(self):
        messages = [
            modem_sms(D1_VALID_ALL, index=1, sender="+2431", timestamp="t1"),
            modem_sms(D1_VALID_ALL.replace("9IX", "9IY", 1), index=2, sender="+2432", timestamp="t2"),
            modem_sms(D1_VALID_ALL.replace("9IX", "9IZ", 1), index=3, sender="+2433", timestamp="t3"),
        ]
        modem = FakeModem(messages, [cmti(1), cmti(2), cmti(3)])
        receiver = self.receiver(modem)
        results = [receiver.poll_once() for _ in range(3)]
        self.assertTrue(all(item.deleted for item in results))
        self.assertEqual(modem.deleted, [("SM", 1), ("SM", 2), ("SM", 3)])
        self.assertEqual(self.repository.count_inbound(), 3)
        self.assertEqual(self.repository.count_outbox(), 3)

    def test_startup_recovery_processes_stored_messages(self):
        messages = [
            modem_sms(D1_VALID_ALL, index=1, sender="+2431", timestamp="t1"),
            modem_sms("BONJOUR", index=2, sender="+2432", timestamp="t2"),
        ]
        modem = FakeModem(messages)
        results = self.receiver(modem).recover_stored_messages()
        self.assertEqual(len(results), 2)
        self.assertEqual(modem.deleted, [("SM", 1), ("SM", 2)])
        self.assertEqual(self.repository.count_inbound(), 2)
        self.assertEqual(self.repository.count_outbox(), 1)

    def test_sender_and_modem_timestamp_remain_separate_transport_metadata(self):
        sms = modem_sms(
            D1_VALID_ALL,
            sender="  +243999  ",
            timestamp="26/09/28,07:00:00+04",
        )
        modem = FakeModem([sms])
        result = self.receiver(modem).process_sms(sms)
        inbound = self.repository.get_inbound(result.sms_id)
        self.assertEqual(inbound.sender, "+243999")
        self.assertEqual(inbound.modem_timestamp, "26/09/28,07:00:00+04")
        self.assertIn("2026-09-27T16:30:00+01:00", self.repository.get_outbox(1).payload_json)


if __name__ == "__main__":
    unittest.main()
