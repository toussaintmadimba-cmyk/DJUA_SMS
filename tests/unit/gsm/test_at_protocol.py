import unittest

from djua_sms_gateway.gsm.at_protocol import AtProtocol
from tests.unit.gsm.fakes import ScriptedTransport


class AtProtocolTests(unittest.TestCase):
    def test_ok_response_skips_echo_and_keeps_lines(self):
        transport = ScriptedTransport(
            {"AT+CSQ": ["AT+CSQ", "+CSQ: 26,0", "OK"]}
        )
        response = AtProtocol(transport).execute("AT+CSQ")
        self.assertTrue(response.ok)
        self.assertEqual(response.lines, ("+CSQ: 26,0",))

    def test_timeout_is_explicit(self):
        transport = ScriptedTransport({"AT": [None]})
        response = AtProtocol(transport).execute("AT", timeout_seconds=0.02)
        self.assertFalse(response.ok)
        self.assertTrue(response.timed_out)
        self.assertEqual(response.error, "TIMEOUT")

    def test_plain_error_is_preserved(self):
        response = AtProtocol(
            ScriptedTransport({"AT+BAD": ["ERROR"]})
        ).execute("AT+BAD")
        self.assertFalse(response.ok)
        self.assertEqual(response.error, "ERROR")

    def test_cme_error_is_preserved(self):
        response = AtProtocol(
            ScriptedTransport({"AT+CPIN?": ["+CME ERROR: SIM not inserted"]})
        ).execute("AT+CPIN?")
        self.assertEqual(response.error, "+CME ERROR: SIM not inserted")

    def test_cms_error_is_preserved(self):
        response = AtProtocol(
            ScriptedTransport({"AT+CMGR=1": ["+CMS ERROR: 321"]})
        ).execute("AT+CMGR=1")
        self.assertEqual(response.error, "+CMS ERROR: 321")

    def test_cmti_arriving_during_command_is_queued(self):
        transport = ScriptedTransport(
            {
                "AT+CSQ": [
                    '+CMTI: "SM",4',
                    "+CSQ: 26,0",
                    "OK",
                ]
            }
        )
        protocol = AtProtocol(transport)
        response = protocol.execute("AT+CSQ")
        self.assertEqual(response.lines, ("+CSQ: 26,0",))
        self.assertEqual(protocol.pop_urc(), '+CMTI: "SM",4')

    def test_ready_line_is_not_mixed_with_command_response(self):
        transport = ScriptedTransport(
            {"AT": ["SMS Ready", "OK"]}
        )
        protocol = AtProtocol(transport)
        response = protocol.execute("AT")
        self.assertTrue(response.ok)
        self.assertEqual(response.lines, ())
        self.assertEqual(protocol.pop_urc(), "SMS Ready")

    def test_poll_urc_reads_spontaneous_line(self):
        protocol = AtProtocol(
            ScriptedTransport(spontaneous=['+CMTI: "ME",42'])
        )
        self.assertEqual(
            protocol.poll_urc(timeout_seconds=0),
            '+CMTI: "ME",42',
        )


if __name__ == "__main__":
    unittest.main()
