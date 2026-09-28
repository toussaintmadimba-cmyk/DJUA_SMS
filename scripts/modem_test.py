#!/usr/bin/env python3
"""Non-destructive SIM800L diagnostic for the DJUA_SMS receiver."""

from __future__ import annotations

import argparse

from djua_sms_gateway.config import GsmConfig
from djua_sms_gateway.gsm.at_protocol import AtProtocol
from djua_sms_gateway.gsm.modem import Sim800Modem
from djua_sms_gateway.gsm.serial_transport import PySerialTransport


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--storage", default=None, help="Optional explicit SMS storage, e.g. SM")
    parser.add_argument("--cnmi", default="2,1,0,0,0")
    args = parser.parse_args()

    config = GsmConfig(
        serial_port=args.port,
        baud_rate=args.baud,
        sms_storage=args.storage,
        cnmi=args.cnmi,
    ).validate()
    transport = PySerialTransport(config)
    modem = Sim800Modem(
        AtProtocol(transport, command_timeout_seconds=config.command_timeout_seconds),
        init_retries=config.init_retries,
        command_timeout_seconds=config.command_timeout_seconds,
        sms_storage=config.sms_storage,
        cnmi=config.cnmi,
    )
    try:
        report = modem.initialize()
        print(f"MODEM={'OK' if report.modem_present else 'NOK'}")
        print(f"SIM={report.sim_status.value}")
        print(f"NETWORK={report.network_registration.value}")
        if report.signal is None:
            print("SIGNAL=UNKNOWN")
        else:
            label = "UNKNOWN" if not report.signal.known else str(report.signal.rssi)
            print(f"SIGNAL_RSSI={label} BER={report.signal.ber}")
        print(f"SMS_MODE={'TEXT' if report.sms_text_mode else 'NOT_READY'}")
        if report.storage:
            print(
                f"STORAGE={report.storage.name} "
                f"USED={report.storage.used} TOTAL={report.storage.total}"
            )
        else:
            print("STORAGE=UNKNOWN")
        print(f"CNMI={'OK' if report.cnmi_configured else 'NOK'}")
        print("Aucun SMS n'a été supprimé.")
        return 0 if report.modem_present else 2
    finally:
        modem.close()


if __name__ == "__main__":
    raise SystemExit(main())
