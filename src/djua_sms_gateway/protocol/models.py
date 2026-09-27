"""Simple immutable models for the D1 protocol core."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ValidationStatus(str, Enum):
    INVALID_FORMAT = "INVALID_FORMAT"
    VALID_WITH_WARNING = "VALID_WITH_WARNING"
    VALID = "VALID"


class AuthStatus(str, Enum):
    NOT_VERIFIED = "AUTH_NOT_VERIFIED"


@dataclass(frozen=True)
class SmsTelemetry:
    protocol_version: str
    device_id: str
    sequence: int
    rtc: str | None
    timezone_minutes: int | None
    uptime_ms: int
    interval_seconds: int
    latitude: float | None
    longitude: float | None
    battery_voltage: float | None
    battery_current: float | None
    battery_power: float | None
    solar_voltage: float | None
    solar_current: float | None
    solar_power: float | None
    solar_energy_interval_wh: float | None
    ac_voltage: float | None
    ac_current: float | None
    ac_active_power: float | None
    ac_apparent_power: float | None
    ac_energy_interval_wh: float | None
    flags: int
    auth: str
    rtc_valid: bool
    gps_valid: bool
    battery_valid: bool
    solar_valid: bool
    ac_valid: bool
    raw_message: str = field(repr=False)


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    auth_status: AuthStatus = AuthStatus.NOT_VERIFIED

    @property
    def is_valid(self) -> bool:
        return self.status is not ValidationStatus.INVALID_FORMAT


@dataclass(frozen=True)
class DjuaMqttPayload:
    kit_id: str
    timestamp_ms: int
    interval_seconds: int
    latitude: float
    longitude: float
    battery_voltage: float
    battery_current: float
    battery_power: float
    solar_voltage: float | None
    solar_current: float | None
    solar_power: float | None
    solar_energy_interval_wh: float | None
    ac_voltage: float
    ac_current: float
    ac_active_power: float
    ac_apparent_power: float
    ac_energy_interval_wh: float
    timestamp: str | None = None
    timezone: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kit_id": self.kit_id,
            "timestamp_ms": self.timestamp_ms,
            "interval_seconds": self.interval_seconds,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "battery": {
                "voltage_v": self.battery_voltage,
                "current_a": self.battery_current,
                "power_w": self.battery_power,
            },
            "solar": {
                "voltage_v": self.solar_voltage,
                "current_a": self.solar_current,
                "power_w": self.solar_power,
                "energy_interval_wh": self.solar_energy_interval_wh,
            },
            "ac_load": {
                "voltage_v": self.ac_voltage,
                "current_a": self.ac_current,
                "active_power_w": self.ac_active_power,
                "apparent_power_va": self.ac_apparent_power,
                "energy_interval_wh": self.ac_energy_interval_wh,
            },
        }
        if self.timestamp is not None:
            payload["timestamp"] = self.timestamp
        if self.timezone is not None:
            payload["timezone"] = self.timezone
        return payload
