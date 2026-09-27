"""Normalize validated D1 telemetry into the observed DJUA MQTT contract."""

from __future__ import annotations

from .errors import NormalizationError
from .models import DjuaMqttPayload, SmsTelemetry, ValidationStatus
from .validator import validate_telemetry


def _timestamp_iso8601(rtc: str) -> str:
    return (
        f"{rtc[0:4]}-{rtc[4:6]}-{rtc[6:8]}"
        f"T{rtc[8:10]}:{rtc[10:12]}:{rtc[12:14]}+01:00"
    )


def normalize_to_mqtt(telemetry: SmsTelemetry) -> DjuaMqttPayload:
    validation = validate_telemetry(telemetry)
    if validation.status is ValidationStatus.INVALID_FORMAT:
        raise NormalizationError("; ".join(validation.errors))

    if telemetry.gps_valid:
        latitude = float(telemetry.latitude)
        longitude = float(telemetry.longitude)
    else:
        latitude = 0.0
        longitude = 0.0

    if telemetry.battery_valid:
        battery_voltage = float(telemetry.battery_voltage)
        battery_current = float(telemetry.battery_current)
        battery_power = float(telemetry.battery_power)
    else:
        battery_voltage = 0.0
        battery_current = 0.0
        battery_power = 0.0

    if telemetry.solar_valid:
        solar_voltage = float(telemetry.solar_voltage)
        solar_current = float(telemetry.solar_current)
        solar_power = float(telemetry.solar_power)
        solar_energy_interval_wh = float(telemetry.solar_energy_interval_wh)
    else:
        solar_voltage = None
        solar_current = None
        solar_power = None
        solar_energy_interval_wh = None

    if telemetry.ac_valid:
        ac_voltage = float(telemetry.ac_voltage)
        ac_current = float(telemetry.ac_current)
        ac_active_power = float(telemetry.ac_active_power)
        ac_apparent_power = float(telemetry.ac_apparent_power)
        ac_energy_interval_wh = float(telemetry.ac_energy_interval_wh)
    else:
        ac_voltage = 0.0
        ac_current = 0.0
        ac_active_power = 0.0
        ac_apparent_power = 0.0
        ac_energy_interval_wh = 0.0

    timestamp = None
    timezone = None
    if telemetry.rtc_valid:
        timestamp = _timestamp_iso8601(telemetry.rtc)
        timezone = "GMT+1"

    return DjuaMqttPayload(
        kit_id=telemetry.device_id,
        timestamp_ms=telemetry.uptime_ms,
        interval_seconds=telemetry.interval_seconds,
        latitude=latitude,
        longitude=longitude,
        battery_voltage=battery_voltage,
        battery_current=battery_current,
        battery_power=battery_power,
        solar_voltage=solar_voltage,
        solar_current=solar_current,
        solar_power=solar_power,
        solar_energy_interval_wh=solar_energy_interval_wh,
        ac_voltage=ac_voltage,
        ac_current=ac_current,
        ac_active_power=ac_active_power,
        ac_apparent_power=ac_apparent_power,
        ac_energy_interval_wh=ac_energy_interval_wh,
        timestamp=timestamp,
        timezone=timezone,
    )
