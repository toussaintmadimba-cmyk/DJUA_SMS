"""Synchronous ingestion pipeline from raw SMS to durable MQTT outbox."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import logging

from djua_sms_gateway.protocol.errors import ProtocolError
from djua_sms_gateway.protocol.models import ValidationStatus
from djua_sms_gateway.protocol.normalizer import normalize_to_mqtt
from djua_sms_gateway.protocol.parser import parse_d1
from djua_sms_gateway.protocol.validator import validate_telemetry
from djua_sms_gateway.storage.models import QueueDisposition, RawSmsInput, StoreDisposition
from djua_sms_gateway.storage.repository import SmsRepository

logger = logging.getLogger(__name__)


class IngestionDisposition(str, Enum):
    QUEUED = "QUEUED"
    INVALID = "INVALID"
    DUPLICATE_RAW = "DUPLICATE_RAW"
    DUPLICATE_LOGICAL = "DUPLICATE_LOGICAL"


@dataclass(frozen=True)
class IngestionConfig:
    mqtt_topic_prefix: str = "djua/test"
    mqtt_qos: int = 1
    mqtt_retain: bool = False


@dataclass(frozen=True)
class IngestionResult:
    disposition: IngestionDisposition
    sms_id: int
    outbox_id: int | None = None
    duplicate_of_sms_id: int | None = None
    error: str | None = None

    @property
    def durably_stored(self) -> bool:
        return True


class SmsIngestionService:
    def __init__(
        self,
        repository: SmsRepository,
        config: IngestionConfig | None = None,
    ) -> None:
        self.repository = repository
        self.config = config or IngestionConfig()

    def ingest(self, raw: RawSmsInput) -> IngestionResult:
        stored = self.repository.store_raw_sms(raw)
        sms_id = stored.record.id
        if stored.disposition is StoreDisposition.DUPLICATE:
            logger.info("SMS_DUPLICATE_RAW sms_id=%s", sms_id)
            return IngestionResult(IngestionDisposition.DUPLICATE_RAW, sms_id=sms_id)

        logger.info("SMS_STORED sms_id=%s", sms_id)

        try:
            telemetry = parse_d1(raw.raw_body)
        except ProtocolError as exc:
            self.repository.mark_invalid(sms_id, validation_error=str(exc))
            logger.info("SMS_INVALID sms_id=%s", sms_id)
            return IngestionResult(
                IngestionDisposition.INVALID,
                sms_id=sms_id,
                error=str(exc),
            )

        validation = validate_telemetry(telemetry)
        if validation.status is ValidationStatus.INVALID_FORMAT:
            error = "\n".join(validation.errors)
            warning = "\n".join(validation.warnings) or None
            self.repository.mark_invalid(
                sms_id,
                validation_error=error,
                validation_status=validation.status.value,
                validation_warning=warning,
                telemetry=telemetry,
            )
            logger.info("SMS_INVALID sms_id=%s", sms_id)
            return IngestionResult(
                IngestionDisposition.INVALID,
                sms_id=sms_id,
                error=error,
            )

        logger.info("SMS_VALIDATED sms_id=%s", sms_id)
        payload = normalize_to_mqtt(telemetry).to_dict()
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        prefix = self.config.mqtt_topic_prefix.rstrip("/")
        topic = f"{prefix}/{telemetry.device_id}/telemetry"
        queued = self.repository.queue_valid_sms(
            sms_id,
            telemetry,
            validation,
            topic=topic,
            payload_json=payload_json,
            qos=self.config.mqtt_qos,
            retain=self.config.mqtt_retain,
        )

        if queued.disposition is QueueDisposition.DUPLICATE_LOGICAL:
            logger.info(
                "SMS_DUPLICATE_LOGICAL sms_id=%s duplicate_of=%s",
                sms_id,
                queued.duplicate_of_sms_id,
            )
            return IngestionResult(
                IngestionDisposition.DUPLICATE_LOGICAL,
                sms_id=sms_id,
                duplicate_of_sms_id=queued.duplicate_of_sms_id,
            )

        logger.info("MQTT_OUTBOX_CREATED sms_id=%s outbox_id=%s", sms_id, queued.outbox.id)
        return IngestionResult(
            IngestionDisposition.QUEUED,
            sms_id=sms_id,
            outbox_id=queued.outbox.id,
        )
