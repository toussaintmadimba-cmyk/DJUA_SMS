"""Structural and contract validation for parsed D1 telemetry."""

from __future__ import annotations

from datetime import datetime
import math
import re

from .models import SmsTelemetry, ValidationResult, ValidationStatus

DEVICE_ID_RE = re.compile(r"^[A-Z0-9-]{1,32}$")
AUTH_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
SUPPORTED_FLAGS_MASK = 0x1F
MAX_ESP32_MILLIS = 0xFFFFFFFF
CONFIRMED_DJUA_TIMEZONE_MINUTES = 60


def _all_finite(values: tuple[tuple[str, float | None], ...], errors: list[str]) -> None:
    for name, value in values:
        if value is not None and not math.isfinite(value):
            errors.append(f"{name}: value must be finite")


def _check_measurement_group(
    name: str,
    valid: bool,
    values: tuple[tuple[str, float | None], ...],
    errors: list[str],
    warnings: list[str],
) -> None:
    missing = [field for field, value in values if value is None]
    provided = [field for field, value in values if value is not None]

    if valid and missing:
        errors.append(f"{name}: valid flag requires values for {', '.join(missing)}")
    elif not valid and provided:
        warnings.append(f"{name}: invalid flag set; provided values will be ignored")


def validate_telemetry(telemetry: SmsTelemetry) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if telemetry.protocol_version != "D1":
        errors.append(f"protocol: unsupported version {telemetry.protocol_version!r}")

    if DEVICE_ID_RE.fullmatch(telemetry.device_id) is None:
        errors.append("device_id: expected [A-Z0-9-]{1,32}")

    if telemetry.flags & ~SUPPORTED_FLAGS_MASK:
        errors.append("flags: reserved bits must be zero for D1")

    if telemetry.sequence < 0:
        errors.append("sequence: must be non-negative")

    if telemetry.uptime_ms < 0 or telemetry.uptime_ms > MAX_ESP32_MILLIS:
        errors.append("uptime_ms: must fit ESP32 millis() uint32 range")

    if telemetry.interval_seconds <= 0:
        errors.append("interval_seconds: must be greater than zero")

    numeric_values = (
        ("latitude", telemetry.latitude),
        ("longitude", telemetry.longitude),
        ("battery_voltage", telemetry.battery_voltage),
        ("battery_current", telemetry.battery_current),
        ("battery_power", telemetry.battery_power),
        ("solar_voltage", telemetry.solar_voltage),
        ("solar_current", telemetry.solar_current),
        ("solar_power", telemetry.solar_power),
        ("solar_energy_interval_wh", telemetry.solar_energy_interval_wh),
        ("ac_voltage", telemetry.ac_voltage),
        ("ac_current", telemetry.ac_current),
        ("ac_active_power", telemetry.ac_active_power),
        ("ac_apparent_power", telemetry.ac_apparent_power),
        ("ac_energy_interval_wh", telemetry.ac_energy_interval_wh),
    )
    _all_finite(numeric_values, errors)

    if telemetry.rtc_valid:
        if telemetry.rtc is None:
            errors.append("rtc: RTC-valid flag requires a timestamp")
        else:
            try:
                datetime.strptime(telemetry.rtc, "%Y%m%d%H%M%S")
            except ValueError:
                errors.append("rtc: expected a real date in YYYYMMDDhhmmss format")

        if telemetry.timezone_minutes is None:
            errors.append("tz_min: RTC-valid flag requires a timezone offset")
        elif telemetry.timezone_minutes != CONFIRMED_DJUA_TIMEZONE_MINUTES:
            errors.append(
                "tz_min: current DJUA MQTT contract is confirmed only for GMT+1 (+60)"
            )
    elif telemetry.rtc is not None or telemetry.timezone_minutes is not None:
        warnings.append("rtc: RTC-invalid flag set; rtc/timezone values will be ignored")

    if telemetry.gps_valid:
        if telemetry.latitude is None or telemetry.longitude is None:
            errors.append("gps: GPS-valid flag requires latitude and longitude")
        else:
            if math.isfinite(telemetry.latitude) and not -90.0 <= telemetry.latitude <= 90.0:
                errors.append("latitude: must be within [-90, 90]")
            if math.isfinite(telemetry.longitude) and not -180.0 <= telemetry.longitude <= 180.0:
                errors.append("longitude: must be within [-180, 180]")
    else:
        gps_values = (telemetry.latitude, telemetry.longitude)
        if gps_values != (None, None) and gps_values != (0.0, 0.0):
            warnings.append("gps: GPS-invalid flag set; coordinates will be ignored")

    _check_measurement_group(
        "battery",
        telemetry.battery_valid,
        (
            ("battery_voltage", telemetry.battery_voltage),
            ("battery_current", telemetry.battery_current),
            ("battery_power", telemetry.battery_power),
        ),
        errors,
        warnings,
    )
    _check_measurement_group(
        "solar",
        telemetry.solar_valid,
        (
            ("solar_voltage", telemetry.solar_voltage),
            ("solar_current", telemetry.solar_current),
            ("solar_power", telemetry.solar_power),
            ("solar_energy_interval_wh", telemetry.solar_energy_interval_wh),
        ),
        errors,
        warnings,
    )
    _check_measurement_group(
        "ac",
        telemetry.ac_valid,
        (
            ("ac_voltage", telemetry.ac_voltage),
            ("ac_current", telemetry.ac_current),
            ("ac_active_power", telemetry.ac_active_power),
            ("ac_apparent_power", telemetry.ac_apparent_power),
            ("ac_energy_interval_wh", telemetry.ac_energy_interval_wh),
        ),
        errors,
        warnings,
    )

    if telemetry.auth != "-":
        if AUTH_RE.fullmatch(telemetry.auth) is None:
            errors.append("auth: expected '-' or 11 base64url characters")
        else:
            warnings.append("auth: AUTH_NOT_VERIFIED")

    if errors:
        status = ValidationStatus.INVALID_FORMAT
    elif warnings:
        status = ValidationStatus.VALID_WITH_WARNING
    else:
        status = ValidationStatus.VALID

    return ValidationResult(
        status=status,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )
