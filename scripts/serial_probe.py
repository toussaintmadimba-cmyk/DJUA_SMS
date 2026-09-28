#!/usr/bin/env python3
"""Minimal SIM800L serial probe: open port, send AT, print response."""

from __future__ import annotations

import argparse

from djua_sms_gateway.config import GsmConfig
from djua_sms_gateway.gsm.at_protocol import AtProtocol
from djua_sms_gateway.gsm.serial_transport import PySerialTransport


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="COM16, /dev/ttyUSB0, etc.")
    parser.add_argument("--baud", type=int, default=9600)
    args = parser.parse_args()

    config = GsmConfig(serial_port=args.port, baud_rate=args.baud).validate()
    transport = PySerialTransport(config)
    try:
        transport.open()
        response = AtProtocol(
            transport,
            command_timeout_seconds=config.command_timeout_seconds,
        ).execute("AT")
        print(f"PORT={args.port} BAUD={args.baud}")
        print(f"OK={response.ok} TIMEOUT={response.timed_out}")
        for line in response.lines:
            print(line)
        if response.error:
            print(f"ERROR={response.error}")
        return 0 if response.ok else 2
    finally:
        transport.close()


if __name__ == "__main__":
    raise SystemExit(main())
