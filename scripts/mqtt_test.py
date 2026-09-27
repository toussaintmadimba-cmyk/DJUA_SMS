#!/usr/bin/env python3
"""Manual broker connectivity test for DJUA_SMS.

This publishes an explicitly synthetic diagnostic payload. It does not use a
field device topic and must not contain production telemetry or secrets.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import threading

from djua_sms_gateway.config import MqttConfig
from djua_sms_gateway.mqtt.client import PahoMqttClient


def main() -> int:
    config = MqttConfig.from_env()
    client = PahoMqttClient(config)
    ack = threading.Event()
    ack_mid: list[int] = []

    def on_ack(mid: int) -> None:
        ack_mid.append(mid)
        ack.set()

    client.set_publish_ack_handler(on_ack)
    topic = f"{config.normalized_topic_prefix}/gateway-test/diagnostic"
    payload = json.dumps(
        {
            "kind": "DJUA_SMS_MQTT_CONNECTIVITY_TEST",
            "client_id": config.client_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    try:
        client.connect()
        receipt = client.publish(topic, payload, qos=1, retain=False)
        if not ack.wait(config.publish_timeout_seconds):
            print(f"ECHEC: PUBACK non reçu pour mid={receipt.mid}")
            return 2
        if ack_mid[-1] != receipt.mid:
            print(f"ECHEC: PUBACK inattendu mid={ack_mid[-1]} attendu={receipt.mid}")
            return 3
        print(f"SUCCES: PUBACK reçu mid={receipt.mid} topic={topic}")
        return 0
    finally:
        client.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
