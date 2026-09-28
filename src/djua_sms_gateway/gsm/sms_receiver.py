"""Receive modem SMS, persist through ingestion, then delete safely."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging

from djua_sms_gateway.services.ingestion import (
    IngestionDisposition,
    IngestionResult,
    SmsIngestionService,
)
from djua_sms_gateway.storage.models import RawSmsInput

from .models import CmtiNotification, ModemSms
from .modem import ModemCommandError, Sim800Modem
from .serial_transport import SerialTransportError

logger = logging.getLogger(__name__)


class ReceiveDisposition(str, Enum):
    STORED = "STORED"
    DUPLICATE_RAW = "DUPLICATE_RAW"
    INVALID = "INVALID"
    DELETE_FAILED = "DELETE_FAILED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    READ_FAILED = "READ_FAILED"
    NO_NOTIFICATION = "NO_NOTIFICATION"


@dataclass(frozen=True)
class SmsReceiveResult:
    disposition: ReceiveDisposition
    storage: str | None = None
    index: int | None = None
    sms_id: int | None = None
    deleted: bool = False
    error: str | None = None


class SmsReceiver:
    def __init__(self, modem: Sim800Modem, ingestion: SmsIngestionService) -> None:
        self.modem = modem
        self.ingestion = ingestion

    def process_sms(self, sms: ModemSms) -> SmsReceiveResult:
        try:
            ingestion_result = self.ingestion.ingest(
                RawSmsInput(
                    sender=sms.sender.strip(),
                    raw_body=sms.raw_body,
                    modem_timestamp=sms.modem_timestamp,
                )
            )
        except Exception as exc:
            logger.exception(
                "SMS_PERSISTENCE_FAILED storage=%s index=%s",
                sms.storage,
                sms.index,
            )
            return SmsReceiveResult(
                ReceiveDisposition.PERSISTENCE_FAILED,
                storage=sms.storage,
                index=sms.index,
                deleted=False,
                error=str(exc),
            )

        if not ingestion_result.durably_stored:
            return SmsReceiveResult(
                ReceiveDisposition.PERSISTENCE_FAILED,
                storage=sms.storage,
                index=sms.index,
                sms_id=ingestion_result.sms_id,
                deleted=False,
                error="ingestion did not confirm durable storage",
            )

        try:
            self.modem.delete_sms(sms.storage, sms.index)
            logger.info("SMS_DELETE_OK storage=%s index=%s", sms.storage, sms.index)
        except SerialTransportError:
            logger.warning(
                "GSM_PORT_LOST_AFTER_PERSIST storage=%s index=%s",
                sms.storage,
                sms.index,
            )
            raise
        except Exception as exc:
            logger.warning(
                "SMS_DELETE_FAILED storage=%s index=%s",
                sms.storage,
                sms.index,
            )
            return SmsReceiveResult(
                ReceiveDisposition.DELETE_FAILED,
                storage=sms.storage,
                index=sms.index,
                sms_id=ingestion_result.sms_id,
                deleted=False,
                error=str(exc),
            )

        return SmsReceiveResult(
            self._map_ingestion(ingestion_result),
            storage=sms.storage,
            index=sms.index,
            sms_id=ingestion_result.sms_id,
            deleted=True,
        )

    def handle_notification(self, notification: CmtiNotification) -> SmsReceiveResult:
        try:
            sms = self.modem.read_sms(notification.storage, notification.index)
        except SerialTransportError:
            raise
        except Exception as exc:
            logger.warning(
                "SMS_READ_FAILED storage=%s index=%s",
                notification.storage,
                notification.index,
            )
            return SmsReceiveResult(
                ReceiveDisposition.READ_FAILED,
                storage=notification.storage,
                index=notification.index,
                deleted=False,
                error=str(exc),
            )
        return self.process_sms(sms)

    def poll_once(self, *, timeout_seconds: float = 0.0) -> SmsReceiveResult:
        notification = self.modem.poll_notification(timeout_seconds=timeout_seconds)
        if notification is None:
            return SmsReceiveResult(ReceiveDisposition.NO_NOTIFICATION)
        return self.handle_notification(notification)

    def recover_stored_messages(self) -> list[SmsReceiveResult]:
        results: list[SmsReceiveResult] = []
        for sms in self.modem.list_all_sms():
            results.append(self.process_sms(sms))
        return results

    @staticmethod
    def _map_ingestion(result: IngestionResult) -> ReceiveDisposition:
        if result.disposition is IngestionDisposition.DUPLICATE_RAW:
            logger.info("SMS_DUPLICATE sms_id=%s", result.sms_id)
            return ReceiveDisposition.DUPLICATE_RAW
        if result.disposition is IngestionDisposition.INVALID:
            logger.info("SMS_INVALID sms_id=%s", result.sms_id)
            return ReceiveDisposition.INVALID
        logger.info("SMS_STORED sms_id=%s", result.sms_id)
        return ReceiveDisposition.STORED
