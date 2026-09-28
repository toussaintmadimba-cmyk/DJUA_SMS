#!/usr/bin/env python3
"""Interactive real-SMS receive test with safe persistence-before-delete."""

from __future__ import annotations

import argparse

from djua_sms_gateway.config import GsmConfig
from djua_sms_gateway.gsm.at_protocol import AtProtocol
from djua_sms_gateway.gsm.modem import Sim800Modem
from djua_sms_gateway.gsm.serial_transport import PySerialTransport
from djua_sms_gateway.gsm.sms_receiver import SmsReceiver
from djua_sms_gateway.services.ingestion import SmsIngestionService
from djua_sms_gateway.storage import Database, SmsRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--database", default="data/djua_sms_gateway.db")
    parser.add_argument("--storage", default=None)
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
        print(
            f"MODEM={report.modem_present} SIM={report.sim_status.value} "
            f"NETWORK={report.network_registration.value}"
        )
        print("En attente d'une notification +CMTI... Ctrl+C pour arrêter.")

        while True:
            notification = modem.poll_notification(timeout_seconds=1.0)
            if notification is None:
                continue
            sms = modem.read_sms(notification.storage, notification.index)
            print("--- SMS REÇU ---")
            print(f"storage={sms.storage} index={sms.index}")
            print(f"sender={sms.sender}")
            print(f"timestamp={sms.modem_timestamp}")
            print(f"body={sms.raw_body}")
            choice = input(
                "Ingérer dans SQLite et supprimer du modem seulement après succès durable ? [y/N] "
            ).strip().lower()
            if choice not in {"y", "yes", "o", "oui"}:
                print("SMS laissé dans le modem.")
                continue

            repository = SmsRepository(Database(args.database))
            receiver = SmsReceiver(modem, SmsIngestionService(repository))
            result = receiver.process_sms(sms)
            print(
                f"result={result.disposition.value} "
                f"sms_id={result.sms_id} deleted={result.deleted}"
            )
            if result.error:
                print(f"error={result.error}")
            return 0 if result.deleted else 3
    except KeyboardInterrupt:
        print("Arrêt demandé. Aucun effacement global exécuté.")
        return 130
    finally:
        modem.close()


if __name__ == "__main__":
    raise SystemExit(main())
