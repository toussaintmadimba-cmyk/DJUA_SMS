import unittest

from djua_sms_gateway.gsm.at_protocol import AtProtocol
from djua_sms_gateway.gsm.models import (
    NetworkRegistration,
    SimStatus,
)
from djua_sms_gateway.gsm.modem import (
    ModemCommandError,
    Sim800Modem,
    parse_cmti,
)
from tests.fixtures.d1_messages import D1_VALID_ALL
from tests.unit.gsm.fakes import ScriptedTransport


def ready_script(*, creg="+CREG: 0,1", csq="+CSQ: 26,0", cpin="+CPIN: READY"):
    return {
        "AT": ["OK"],
        "AT+CMEE=2": ["OK"],
        "AT+CPIN?": [cpin, "OK"],
        "AT+CREG?": [creg, "OK"],
        "AT+CSQ": [csq, "OK"],
        "AT+CMGF=1": ["OK"],
        "AT+CPMS?": ['+CPMS: "SM",2,30,"SM",2,30,"SM",2,30', "OK"],
        "AT+CNMI=2,1,0,0,0": ["OK"],
    }


class ModemTests(unittest.TestCase):
    def modem(self, script, **kwargs):
        transport = ScriptedTransport(script)
        return Sim800Modem(
            AtProtocol(transport),
            command_timeout_seconds=0.2,
            sleep=lambda _: None,
            **kwargs,
        ), transport

    def test_parse_cmti_variants(self):
        self.assertEqual(parse_cmti('+CMTI: "SM",1').index, 1)
        parsed = parse_cmti(' +CMTI: "ME", 42 ')
        self.assertEqual((parsed.storage, parsed.index), ("ME", 42))

    def test_parse_cmti_malformed(self):
        for line in ("+CMTI", '+CMTI: "SM",x', '+CMTI: SM,1'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_cmti(line)

    def test_initialize_distinguishes_modem_sim_network_sms_and_storage(self):
        modem, _ = self.modem(ready_script())
        report = modem.initialize()
        self.assertTrue(report.modem_present)
        self.assertEqual(report.sim_status, SimStatus.READY)
        self.assertEqual(report.network_registration, NetworkRegistration.HOME)
        self.assertTrue(report.network_registered)
        self.assertEqual(report.signal.rssi, 26)
        self.assertTrue(report.sms_text_mode)
        self.assertEqual((report.storage.name, report.storage.used, report.storage.total), ("SM", 2, 30))
        self.assertTrue(report.cnmi_configured)
        self.assertTrue(report.sms_ready)

    def test_sim_pin_is_reported_without_attempting_pin(self):
        modem, transport = self.modem(ready_script(cpin="+CPIN: SIM PIN", creg="+CREG: 0,0"))
        report = modem.initialize()
        self.assertEqual(report.sim_status, SimStatus.PIN_REQUIRED)
        self.assertFalse(report.sim_ready)
        self.assertFalse(any(cmd.startswith("AT+CPIN=") for cmd in transport.commands))

    def test_sim_puk_is_reported_without_attempting_puk(self):
        modem, _ = self.modem(ready_script(cpin="+CPIN: SIM PUK", creg="+CREG: 0,0"))
        report = modem.initialize()
        self.assertEqual(report.sim_status, SimStatus.PUK_REQUIRED)

    def test_roaming_is_registered(self):
        modem, _ = self.modem(ready_script(creg="+CREG: 0,5"))
        report = modem.initialize()
        self.assertEqual(report.network_registration, NetworkRegistration.ROAMING)
        self.assertTrue(report.network_registered)

    def test_not_registered_is_not_fatal(self):
        modem, _ = self.modem(ready_script(creg="+CREG: 0,2"))
        report = modem.initialize()
        self.assertEqual(report.network_registration, NetworkRegistration.SEARCHING)
        self.assertFalse(report.network_registered)

    def test_csq_99_is_unknown_not_fake_precision(self):
        modem, _ = self.modem(ready_script(csq="+CSQ: 99,99"))
        report = modem.initialize()
        self.assertEqual(report.signal.rssi, 99)
        self.assertFalse(report.signal.known)

    def test_default_does_not_force_sms_storage(self):
        modem, transport = self.modem(ready_script())
        modem.initialize()
        self.assertIn("AT+CPMS?", transport.commands)
        self.assertFalse(any(cmd.startswith('AT+CPMS="') for cmd in transport.commands))

    def test_explicit_storage_is_selected(self):
        script = ready_script()
        script['AT+CPMS="SM"'] = ["+CPMS: 2,30,2,30,2,30", "OK"]
        modem, transport = self.modem(script, sms_storage="SM")
        modem.initialize()
        self.assertIn('AT+CPMS="SM"', transport.commands)

    def test_storage_near_capacity_logs_warning(self):
        script = {
            "AT+CPMS?": ['+CPMS: "SM",9,10,"SM",9,10,"SM",9,10', "OK"],
        }
        modem, _ = self.modem(script)
        with self.assertLogs("djua_sms_gateway.gsm.modem", level="WARNING") as captured:
            storage = modem.get_storage_status()
        self.assertEqual((storage.used, storage.total), (9, 10))
        self.assertTrue(any("SMS_STORAGE" in line for line in captured.output))

    def test_reconnect_revalidates_modem_state(self):
        base = ready_script()
        script = {
            command: [list(response), list(response)]
            for command, response in base.items()
        }
        modem, transport = self.modem(script)
        first = modem.initialize()
        second = modem.reconnect()
        self.assertTrue(first.sms_ready)
        self.assertTrue(second.sms_ready)
        self.assertEqual(transport.reconnect_calls, 1)
        for command in (
            "AT",
            "AT+CPIN?",
            "AT+CREG?",
            "AT+CMGF=1",
            "AT+CPMS?",
            "AT+CNMI=2,1,0,0,0",
        ):
            self.assertEqual(transport.commands.count(command), 2)

    def test_read_sms_extracts_transport_metadata_and_body(self):
        script = {
            'AT+CPMS="SM"': ["+CPMS: 1,30,1,30,1,30", "OK"],
            "AT+CMGR=4": [
                '+CMGR: "REC UNREAD","+243810000001","","26/09/28,06:00:00+04"',
                D1_VALID_ALL,
                "OK",
            ],
        }
        modem, _ = self.modem(script)
        sms = modem.read_sms("SM", 4)
        self.assertEqual(sms.index, 4)
        self.assertEqual(sms.sender, "+243810000001")
        self.assertEqual(sms.modem_timestamp, "26/09/28,06:00:00+04")
        self.assertEqual(sms.raw_body, D1_VALID_ALL)

    def test_read_sms_preserves_multiline_body(self):
        script = {
            'AT+CPMS="SM"': ["+CPMS: 1,30", "OK"],
            "AT+CMGR=2": [
                '+CMGR: "REC READ","+2431","","26/09/28,06:00:00+04"',
                "ligne 1",
                "ligne 2",
                "OK",
            ],
        }
        modem, _ = self.modem(script)
        self.assertEqual(modem.read_sms("SM", 2).raw_body, "ligne 1\nligne 2")

    def test_read_sms_can_represent_empty_body(self):
        script = {
            'AT+CPMS="SM"': ["+CPMS: 1,30", "OK"],
            "AT+CMGR=2": [
                '+CMGR: "REC READ","+2431","","26/09/28,06:00:00+04"',
                "OK",
            ],
        }
        modem, _ = self.modem(script)
        self.assertEqual(modem.read_sms("SM", 2).raw_body, "")

    def test_cmgr_error_is_explicit(self):
        script = {
            'AT+CPMS="SM"': ["+CPMS: 1,30", "OK"],
            "AT+CMGR=9": ["+CMS ERROR: 321"],
        }
        modem, _ = self.modem(script)
        with self.assertRaises(ModemCommandError):
            modem.read_sms("SM", 9)

    def test_cmti_interleaved_during_cmgr_is_not_lost(self):
        script = {
            'AT+CPMS="SM"': ["+CPMS: 1,30", "OK"],
            "AT+CMGR=4": [
                '+CMGR: "REC UNREAD","+2431","","26/09/28,06:00:00+04"',
                '+CMTI: "SM",5',
                D1_VALID_ALL,
                "OK",
            ],
        }
        modem, _ = self.modem(script)
        modem.read_sms("SM", 4)
        notification = modem.poll_notification()
        self.assertEqual((notification.storage, notification.index), ("SM", 5))

    def test_delete_is_precise_and_never_global(self):
        script = {
            'AT+CPMS="SM"': ["+CPMS: 1,30", "OK"],
            "AT+CMGD=7": ["OK"],
        }
        modem, transport = self.modem(script)
        modem.delete_sms("SM", 7)
        self.assertIn("AT+CMGD=7", transport.commands)
        self.assertFalse(any(",4" in cmd for cmd in transport.commands if cmd.startswith("AT+CMGD")))

    def test_list_all_sms_parses_multiple_messages(self):
        script = {
            'AT+CMGL="ALL"': [
                '+CMGL: 1,"REC READ","+2431","","26/09/28,06:00:00+04"',
                "BODY1",
                '+CMGL: 12,"REC UNREAD","+2432","","26/09/28,06:01:00+04"',
                "BODY2",
                "OK",
            ]
        }
        modem, _ = self.modem(script)
        items = modem.list_all_sms()
        self.assertEqual([item.index for item in items], [1, 12])
        self.assertEqual([item.sender for item in items], ["+2431", "+2432"])
        self.assertEqual([item.raw_body for item in items], ["BODY1", "BODY2"])


if __name__ == "__main__":
    unittest.main()
