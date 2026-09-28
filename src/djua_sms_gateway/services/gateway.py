"""Simple orchestration of modem receive, persistence and MQTT outbox work."""

from __future__ import annotations

import logging
import time

from djua_sms_gateway.gsm.modem import Sim800Modem
from djua_sms_gateway.gsm.serial_transport import SerialTransportError
from djua_sms_gateway.gsm.sms_receiver import SmsReceiver
from djua_sms_gateway.services.outbox_worker import MqttOutboxWorker

logger = logging.getLogger(__name__)


class DjuaSmsGateway:
    def __init__(
        self,
        modem: Sim800Modem,
        sms_receiver: SmsReceiver,
        outbox_worker: MqttOutboxWorker | None = None,
        *,
        reconnect_seconds: float = 5.0,
        sleep=time.sleep,
    ) -> None:
        if reconnect_seconds <= 0:
            raise ValueError("reconnect_seconds must be > 0")
        self.modem = modem
        self.sms_receiver = sms_receiver
        self.outbox_worker = outbox_worker
        self.reconnect_seconds = reconnect_seconds
        self._sleep = sleep
        self._started = False
        self._stopping = False

    def startup(self):
        report = self.modem.initialize()
        self._started = True
        recovery_results = []
        if report.sim_ready and report.sms_text_mode:
            recovery_results = self.sms_receiver.recover_stored_messages()
        return report, recovery_results

    def run_once(
        self,
        *,
        gsm_poll_timeout_seconds: float = 0.0,
        mqtt_limit: int | None = None,
    ):
        if not self._started:
            self.startup()

        receive_result = None
        try:
            receive_result = self.sms_receiver.poll_once(
                timeout_seconds=gsm_poll_timeout_seconds
            )
        except SerialTransportError:
            logger.warning("GSM_PORT_LOST")
            self.reconnect_modem()

        mqtt_result = None
        if self.outbox_worker is not None:
            mqtt_result = self.outbox_worker.run_once(limit=mqtt_limit)
        return receive_result, mqtt_result

    def reconnect_modem(self):
        self._sleep(self.reconnect_seconds)
        report = self.modem.reconnect()
        self._started = True
        recovery_results = []
        if report.sim_ready and report.sms_text_mode:
            recovery_results = self.sms_receiver.recover_stored_messages()
        return report, recovery_results

    def run_forever(
        self,
        *,
        gsm_poll_timeout_seconds: float = 0.5,
        idle_sleep_seconds: float = 0.05,
    ) -> None:
        self._stopping = False
        while not self._stopping:
            try:
                if not self._started:
                    self.startup()
                self.run_once(gsm_poll_timeout_seconds=gsm_poll_timeout_seconds)
            except SerialTransportError:
                logger.warning("GSM_PORT_LOST")
                self._started = False
                try:
                    self.reconnect_modem()
                except Exception:
                    logger.exception("GSM_RECONNECT_FAILED")
                    self._sleep(self.reconnect_seconds)
            except Exception:
                if not self._started:
                    logger.exception("GSM_STARTUP_FAILED")
                    self._sleep(self.reconnect_seconds)
                else:
                    raise
            if idle_sleep_seconds > 0:
                self._sleep(idle_sleep_seconds)

    def stop(self) -> None:
        self._stopping = True

    def shutdown(self) -> None:
        self.stop()
        try:
            self.modem.close()
        finally:
            if self.outbox_worker is not None:
                self.outbox_worker.shutdown()
        self._started = False
