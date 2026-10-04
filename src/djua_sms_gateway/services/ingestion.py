"""Synchronous ingestion pipeline from raw SMS to durable MQTT outbox."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import logging

from djua_sms_gateway.config import D2SecurityConfig
from djua_sms_gateway.protocol.d2 import (
    D2AuthStatus,
    D2ProtocolError,
    backend_topic,
    normalize_d2_to_backend,
    parse_d2,
    verify_d2_security,
)
from djua_sms_gateway.protocol.dispatch import detect_protocol
from djua_sms_gateway.protocol.errors import ProtocolError
from djua_sms_gateway.protocol.models import ValidationStatus
from djua_sms_gateway.protocol.normalizer import normalize_to_mqtt
from djua_sms_gateway.protocol.parser import parse_d1
from djua_sms_gateway.protocol.validator import validate_telemetry
from djua_sms_gateway.storage.models import (
    QueueDisposition,
    RawSmsInput,
    StoreDisposition,
)
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
        d2_security: D2SecurityConfig | None = None,
    ) -> None:
        self.repository = repository
        self.config = config or IngestionConfig()
        self.d2_security = (
            d2_security or D2SecurityConfig()
        ).validate()

    def ingest(self, raw: RawSmsInput) -> IngestionResult:
        stored = self.repository.store_raw_sms(raw)
        sms_id = stored.record.id

        if stored.disposition is StoreDisposition.DUPLICATE:
            logger.info("SMS_DUPLICATE_RAW sms_id=%s", sms_id)
            return IngestionResult(
                IngestionDisposition.DUPLICATE_RAW,
                sms_id=sms_id,
            )

        logger.info("SMS_STORED sms_id=%s", sms_id)

        try:
            protocol = detect_protocol(raw.raw_body)
        except D2ProtocolError as exc:
            self.repository.mark_invalid(
                sms_id,
                validation_error=str(exc),
                validation_status=exc.code,
            )
            logger.info("SMS_INVALID sms_id=%s", sms_id)
            return IngestionResult(
                IngestionDisposition.INVALID,
                sms_id=sms_id,
                error=str(exc),
            )

        if protocol == "D1":
            return self._ingest_d1(raw, sms_id)

        return self._ingest_d2(
            raw,
            sms_id,
            stored.record.gateway_received_at,
        )

    def _ingest_d1(
        self,
        raw: RawSmsInput,
        sms_id: int,
    ) -> IngestionResult:
        """Preserve the historical D1 path unchanged."""

        try:
            telemetry = parse_d1(raw.raw_body)
        except ProtocolError as exc:
            self.repository.mark_invalid(
                sms_id,
                validation_error=str(exc),
            )
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

        if (
            queued.disposition
            is QueueDisposition.DUPLICATE_LOGICAL
        ):
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

        logger.info(
            "MQTT_OUTBOX_CREATED sms_id=%s outbox_id=%s",
            sms_id,
            queued.outbox.id,
        )
        return IngestionResult(
            IngestionDisposition.QUEUED,
            sms_id=sms_id,
            outbox_id=queued.outbox.id,
        )

    def _ingest_d2(
        self,
        raw: RawSmsInput,
        sms_id: int,
        gateway_received_at: str,
    ) -> IngestionResult:
        try:
            message = parse_d2(raw.raw_body)
        except D2ProtocolError as exc:
            self.repository.mark_invalid(
                sms_id,
                validation_error=str(exc),
                validation_status=exc.code,
            )
            logger.info(
                "SMS_D2_INVALID sms_id=%s code=%s",
                sms_id,
                exc.code,
            )
            return IngestionResult(
                IngestionDisposition.INVALID,
                sms_id=sms_id,
                error=str(exc),
            )

        key = self.d2_security.key_for(message.device_id)
        allowed_senders = self.d2_security.senders_for(
            message.device_id
        )

        try:
            auth_status = verify_d2_security(
                message,
                mode=self.d2_security.mode,
                key=key,
                sender=raw.sender,
                allowed_senders=allowed_senders,
            )
        except D2ProtocolError as exc:
            verified_before_sender_check = exc.code in {
                "SENDER_INVALID",
                "SENDER_BINDING_REQUIRED",
                "SENDER_DEVICE_MISMATCH",
            }
            self.repository.mark_d2_rejected(
                sms_id,
                message,
                validation_error=str(exc),
                security_status=exc.code,
                auth_status=(
                    D2AuthStatus.VERIFIED.value
                    if verified_before_sender_check
                    else None
                ),
            )
            logger.warning(
                "SMS_D2_SECURITY_REJECTED sms_id=%s code=%s",
                sms_id,
                exc.code,
            )
            return IngestionResult(
                IngestionDisposition.INVALID,
                sms_id=sms_id,
                error=str(exc),
            )

        payload = normalize_d2_to_backend(
            message,
            gateway_received_at=gateway_received_at,
            auth_status=auth_status,
        )
        payload_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        topic = backend_topic(
            message,
            self.config.mqtt_topic_prefix,
        )

        queued = self.repository.queue_d2_message(
            sms_id,
            message,
            auth_status=auth_status.value,
            topic=topic,
            payload_json=payload_json,
            qos=self.config.mqtt_qos,
            retain=self.config.mqtt_retain,
        )

        if (
            queued.disposition
            is QueueDisposition.MESSAGE_ID_CONFLICT
        ):
            error = (
                "MESSAGE_ID_CONFLICT:"
                f"{queued.duplicate_of_sms_id}"
            )
            logger.warning(
                "SMS_D2_MESSAGE_ID_CONFLICT sms_id=%s existing=%s",
                sms_id,
                queued.duplicate_of_sms_id,
            )
            return IngestionResult(
                IngestionDisposition.INVALID,
                sms_id=sms_id,
                duplicate_of_sms_id=queued.duplicate_of_sms_id,
                error=error,
            )

        if (
            queued.disposition
            is QueueDisposition.DUPLICATE_LOGICAL
        ):
            logger.info(
                "SMS_D2_DUPLICATE_MESSAGE_ID sms_id=%s duplicate_of=%s",
                sms_id,
                queued.duplicate_of_sms_id,
            )
            return IngestionResult(
                IngestionDisposition.DUPLICATE_LOGICAL,
                sms_id=sms_id,
                duplicate_of_sms_id=queued.duplicate_of_sms_id,
            )

        logger.info(
            "MQTT_OUTBOX_CREATED sms_id=%s outbox_id=%s protocol=%s",
            sms_id,
            queued.outbox.id,
            message.protocol_version,
        )
        return IngestionResult(
            IngestionDisposition.QUEUED,
            sms_id=sms_id,
            outbox_id=queued.outbox.id,
        )
