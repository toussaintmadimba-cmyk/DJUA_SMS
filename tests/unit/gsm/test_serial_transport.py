import unittest

from djua_sms_gateway.config import GsmConfig
from djua_sms_gateway.gsm.serial_transport import (
    PySerialTransport,
    SerialTransportError,
)
from tests.unit.gsm.fakes import FakeSerialDevice


class SerialTransportTests(unittest.TestCase):
    def make_transport(self, **changes):
        config = GsmConfig(
            serial_port=changes.pop("serial_port", "COM_TEST"),
            baud_rate=changes.pop("baud_rate", 9600),
            **changes,
        )
        devices = []

        def factory(**kwargs):
            device = FakeSerialDevice(**kwargs)
            devices.append(device)
            return device

        return PySerialTransport(config, serial_factory=factory), devices

    def test_gsm_config_defaults_and_validation(self):
        config = GsmConfig(serial_port="COM_TEST").validate()
        self.assertEqual(config.baud_rate, 9600)
        self.assertEqual(config.cnmi, "2,1,0,0,0")
        for config in (
            GsmConfig(serial_port=""),
            GsmConfig(serial_port="x", baud_rate=0),
            GsmConfig(serial_port="x", serial_timeout_seconds=0),
            GsmConfig(serial_port="x", init_retries=0),
            GsmConfig(serial_port="x", cnmi="2,2"),
        ):
            with self.assertRaises(ValueError):
                config.validate()

    def test_open_passes_port_baud_and_timeouts(self):
        transport, devices = self.make_transport(
            baud_rate=19200,
            serial_timeout_seconds=0.7,
            serial_write_timeout_seconds=1.5,
        )
        transport.open()
        self.assertTrue(transport.is_open)
        self.assertEqual(devices[0].kwargs["port"], "COM_TEST")
        self.assertEqual(devices[0].kwargs["baudrate"], 19200)
        self.assertEqual(devices[0].kwargs["timeout"], 0.7)
        self.assertEqual(devices[0].kwargs["write_timeout"], 1.5)

    def test_write_line_appends_carriage_return(self):
        transport, devices = self.make_transport()
        transport.open()
        transport.write_line("AT")
        self.assertEqual(devices[0].writes, [b"AT\r"])
        self.assertEqual(devices[0].flushed, 1)

    def test_read_line_decodes_and_strips_line_endings(self):
        transport, devices = self.make_transport()
        transport.open()
        devices[0].reads.append(b"+CSQ: 26,0\r\n")
        self.assertEqual(transport.read_line(), "+CSQ: 26,0")
        self.assertIsNone(transport.read_line())

    def test_reset_buffers_delegates_to_pyserial(self):
        transport, devices = self.make_transport()
        transport.open()
        transport.reset_buffers()
        self.assertEqual(devices[0].reset_in, 1)
        self.assertEqual(devices[0].reset_out, 1)

    def test_write_failure_marks_port_lost(self):
        transport, devices = self.make_transport()
        transport.open()
        devices[0].fail_write = True
        with self.assertRaises(SerialTransportError):
            transport.write_line("AT")
        self.assertFalse(transport.is_open)

    def test_reconnect_closes_and_reopens(self):
        transport, devices = self.make_transport()
        transport.open()
        first = devices[0]
        transport.reconnect()
        self.assertFalse(first.is_open)
        self.assertEqual(len(devices), 2)
        self.assertTrue(transport.is_open)


if __name__ == "__main__":
    unittest.main()
