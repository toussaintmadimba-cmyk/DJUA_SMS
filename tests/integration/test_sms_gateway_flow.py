import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.gsm.at_protocol import AtProtocol
from djua_sms_gateway.gsm.modem import Sim800Modem
from djua_sms_gateway.gsm.serial_transport import SerialTransportError
from djua_sms_gateway.gsm.sms_receiver import SmsReceiver
from djua_sms_gateway.mqtt.publisher import MqttPublisher
from djua_sms_gateway.services.gateway import DjuaSmsGateway
from djua_sms_gateway.services.ingestion import SmsIngestionService
from djua_sms_gateway.services.outbox_worker import MqttOutboxWorker
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import OutboxStatus
from tests.fixtures.d1_messages import D1_VALID_ALL
from tests.unit.gsm.fakes import ScriptedTransport
from tests.unit.mqtt.fakes import FakeTransport


def base_init_script(*, csq_lines=None, cmgl_lines=None):
    return {
        "AT": ["OK"],
        "AT+CMEE=2": ["OK"],
        "AT+CPIN?": ["+CPIN: READY", "OK"],
        "AT+CREG?": ["+CREG: 0,1", "OK"],
        "AT+CSQ": list(csq_lines or ["+CSQ: 26,0", "OK"]),
        "AT+CMGF=1": ["OK"],
        "AT+CPMS?": ['+CPMS: "SM",1,30,"SM",1,30,"SM",1,30', "OK"],
        "AT+CNMI=2,1,0,0,0": ["OK"],
        'AT+CMGL="ALL"': list(cmgl_lines or ["OK"]),
    }


class SmsGatewayFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"

    def tearDown(self):
        self.tempdir.cleanup()

    def build_gateway(self, serial_transport, mqtt_transport=None):
        repository = SmsRepository(Database(self.path))
        modem = Sim800Modem(
            AtProtocol(serial_transport),
            command_timeout_seconds=0.2,
            sleep=lambda _: None,
        )
        receiver = SmsReceiver(modem, SmsIngestionService(repository))
        worker = None
        if mqtt_transport is not None:
            publisher = MqttPublisher(mqtt_transport, repository)
            worker = MqttOutboxWorker(repository, mqtt_transport, publisher)
        gateway = DjuaSmsGateway(
            modem,
            receiver,
            worker,
            reconnect_seconds=0.01,
            sleep=lambda _: None,
        )
        return gateway, repository

    def test_global_fake_serial_to_sqlite_mqtt_puback_and_cmgd_order(self):
        script = base_init_script()
        script["AT+CMGR=7"] = [
            '+CMGR: "REC UNREAD","+243810000001","","26/09/28,06:00:00+04"',
            D1_VALID_ALL,
            "OK",
        ]
        script["AT+CMGD=7"] = ["OK"]
        serial = ScriptedTransport(
            script,
            spontaneous=['+CMTI: "SM",7'],
        )
        mqtt = FakeTransport(mids=[10])
        gateway, repository = self.build_gateway(serial, mqtt)

        gateway.startup()
        receive_result, mqtt_result = gateway.run_once()
        self.assertTrue(receive_result.deleted)
        self.assertEqual(mqtt_result.started, 1)
        self.assertLess(
            serial.commands.index("AT+CMGD=7"),
            len(serial.commands),
        )
        outbox = repository.list_pending_outbox()[0]
        self.assertEqual(outbox.status, OutboxStatus.PENDING)

        mqtt.ack(10)
        self.assertEqual(
            repository.get_outbox(outbox.id).status,
            OutboxStatus.PUBLISHED,
        )

    def test_cmti_arriving_during_csq_is_processed_after_initialization(self):
        script = base_init_script(
            csq_lines=['+CMTI: "SM",4', "+CSQ: 26,0", "OK"]
        )
        script["AT+CMGR=4"] = [
            '+CMGR: "REC UNREAD","+243810000001","","26/09/28,06:00:00+04"',
            D1_VALID_ALL,
            "OK",
        ]
        script["AT+CMGD=4"] = ["OK"]
        serial = ScriptedTransport(script)
        gateway, repository = self.build_gateway(serial)

        gateway.startup()
        receive_result, _ = gateway.run_once()
        self.assertTrue(receive_result.deleted)
        self.assertEqual(repository.count_inbound(), 1)
        self.assertEqual(repository.count_outbox(), 1)

    def test_startup_recovery_scans_cmgl_and_deletes_only_after_persistence(self):
        cmgl = [
            '+CMGL: 3,"REC UNREAD","+243810000001","","26/09/28,05:59:00+04"',
            D1_VALID_ALL,
            "OK",
        ]
        script = base_init_script(cmgl_lines=cmgl)
        script["AT+CMGD=3"] = ["OK"]
        serial = ScriptedTransport(script)
        gateway, repository = self.build_gateway(serial)

        report, recovered = gateway.startup()
        self.assertTrue(report.sms_ready)
        self.assertEqual(len(recovered), 1)
        self.assertTrue(recovered[0].deleted)
        self.assertEqual(repository.count_inbound(), 1)
        self.assertEqual(repository.count_outbox(), 1)
        self.assertIn("AT+CMGD=3", serial.commands)

    def test_serial_loss_triggers_reconnect_and_full_modem_revalidation(self):
        base = base_init_script()
        script = {
            command: [list(response), list(response)]
            for command, response in base.items()
        }
        serial = ScriptedTransport(
            script,
            spontaneous=[SerialTransportError("USB disconnected")],
        )
        gateway, _ = self.build_gateway(serial)
        gateway.startup()

        receive_result, _ = gateway.run_once()
        self.assertIsNone(receive_result)
        self.assertEqual(serial.reconnect_calls, 1)
        for command in (
            "AT",
            "AT+CPIN?",
            "AT+CREG?",
            "AT+CMGF=1",
            "AT+CPMS?",
            "AT+CNMI=2,1,0,0,0",
            'AT+CMGL="ALL"',
        ):
            self.assertEqual(serial.commands.count(command), 2)

    def test_crash_before_cmgd_then_restart_is_duplicate_raw_and_single_outbox(self):
        repository = SmsRepository(Database(self.path))
        ingestion = SmsIngestionService(repository)

        first_script = base_init_script()
        first_script["AT+CMGR=7"] = [
            '+CMGR: "REC UNREAD","+243810000001","","26/09/28,06:00:00+04"',
            D1_VALID_ALL,
            "OK",
        ]
        first_script["AT+CMGD=7"] = [RuntimeError("simulated crash before delete")]
        first_serial = ScriptedTransport(
            first_script,
            spontaneous=['+CMTI: "SM",7'],
        )
        first_modem = Sim800Modem(AtProtocol(first_serial), command_timeout_seconds=0.2, sleep=lambda _: None)
        first_receiver = SmsReceiver(first_modem, ingestion)
        first_modem.initialize()
        first = first_receiver.poll_once()
        self.assertFalse(first.deleted)
        self.assertEqual(repository.count_outbox(), 1)

        second_script = base_init_script()
        second_script["AT+CMGR=7"] = [
            '+CMGR: "REC READ","+243810000001","","26/09/28,06:00:00+04"',
            D1_VALID_ALL,
            "OK",
        ]
        second_script["AT+CMGD=7"] = ["OK"]
        second_serial = ScriptedTransport(
            second_script,
            spontaneous=['+CMTI: "SM",7'],
        )
        second_modem = Sim800Modem(AtProtocol(second_serial), command_timeout_seconds=0.2, sleep=lambda _: None)
        second_receiver = SmsReceiver(second_modem, SmsIngestionService(repository))
        second_modem.initialize()
        second = second_receiver.poll_once()

        self.assertEqual(second.disposition.value, "DUPLICATE_RAW")
        self.assertTrue(second.deleted)
        self.assertEqual(repository.count_inbound(), 1)
        self.assertEqual(repository.count_outbox(), 1)
        self.assertIn("AT+CMGD=7", second_serial.commands)


if __name__ == "__main__":
    unittest.main()
