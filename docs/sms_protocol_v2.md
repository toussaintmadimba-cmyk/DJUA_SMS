# DJUA SMS Protocol D2 — specification v1

Status: PHASE A FROZEN CONTRACT. This document is the source of truth for D2T/D2E wire format. D1 remains unchanged.

## 1. Scope

D2 extends the existing DJUA_SMS gateway; it does not replace the D1 pipeline.

```text
D1,  -> legacy D1 parser/validator/normalizer
D2T, -> D2 telemetry
D2E, -> D2 urgent event
other -> INVALID
```

Receiver hardware confirmed by the project is SIM868. The existing driver/class names may still say SIM800 because the same AT/SMS path has already worked with the SIM868. Do not rewrite the driver merely because of its name. The future transmitter modem is unspecified.

## 2. GSM-7 invariant

Every valid D2 message must fit in one GSM-7 SMS:

```text
maximum = 160 septets
concatenation = forbidden
truncation = forbidden
UCS-2 fallback = forbidden
```

Allowed D2 characters:

```text
A-Z a-z 0-9 , - _
```

Lowercase and underscore are needed only by base64url authentication tags. Characters from the GSM 03.38 extension table such as ^ { } \ [ ] ~ | and € are forbidden. For every valid D2 message, every allowed character costs exactly one septet. Implementations must nevertheless use a GSM-7-aware counter and reject unsupported characters.

## 3. Common numeric encoding

Unsigned integers use canonical uppercase base36: `0-9A-Z`.

Signed integers use an optional leading minus: `-9IX`. The single token `-` means ABSENT. `-0` is forbidden. Leading zeroes are forbidden except for fixed-width flag fields.

Float-to-wire rounding is round-half-away-from-zero:

```text
x >= 0: floor(x * scale + 0.5)
x <  0: ceil (x * scale - 0.5)
```

No saturation or silent clipping is allowed.

## 4. D2T grammar

Exactly 22 fields / 21 commas:

```text
D2T,DEV,SEQ,RTC,UP,INT,LAT,LON,BV,BI,BP,SV,SI,SP,SE,AV,AI,AP,AS,AE,F,AUTH
```

| Field | Wire unit/resolution | Allowed decoded range |
|---|---|---|
| DEV | ASCII | `[A-Z0-9-]{1,32}` |
| SEQ | integer | 1..4294967295 |
| RTC | Unix UTC seconds | 2000-01-01T00:00:00Z..2099-12-31T23:59:59Z, or `-` |
| UP | milliseconds | 0..4294967295 |
| INT | seconds | 10..86400 |
| LAT | 1e-5 degree | -90..+90 |
| LON | 1e-5 degree | -180..+180 |
| BV | 1 mV | 0..32 V |
| BI | 1 mA | -200..+200 A |
| BP | 0.1 W | -6400..+6400 W |
| SV | 1 mV | 0..100 V |
| SI | 1 mA | -100..+100 A |
| SP | 0.1 W | -10000..+10000 W |
| SE | 0.01 Wh | -240000..+240000 Wh |
| AV | 0.1 V RMS | 0..400 V |
| AI | 0.01 A RMS | 0..30 A |
| AP | 0.1 W | -12000..+12000 W |
| AS | 0.1 VA | 0..12000 VA |
| AE | 0.01 Wh | -288000..+288000 Wh |
| F | bitmask | 00..3J, exactly 2 base36 chars |
| AUTH | base64url | exactly 11 chars, or `-` only in development |

These are protocol representation limits, not electrical safety limits. Firmware must separately enforce the real sensor/hardware limits before deciding that a measurement is valid.

### Sign convention

Battery current/power > 0 means charge into the battery; < 0 means discharge. Solar power/energy > 0 means production toward the system; < 0 means reverse flow. AC active power/energy > 0 means load consumption; < 0 means export/return toward the source.

## 5. D2T flags

Seven bits:

```text
bit0 RTC_VALID
bit1 GPS_VALID
bit2 BATTERY_VALID
bit3 SOLAR_VALID
bit4 AC_VALID
bit5 SOLAR_ENERGY_COMPLETE
bit6 AC_ENERGY_COMPLETE
```

The integer 0..127 is encoded as exactly two base36 characters, `00`..`3J`.

Presence rules are strict:

```text
RTC_VALID=0     -> RTC=-
GPS_VALID=0     -> LAT=-, LON=-
BATTERY_VALID=0 -> BV=-, BI=-, BP=-
SOLAR_VALID=0   -> SV=-, SI=-, SP=-
AC_VALID=0      -> AV=-, AI=-, AP=-, AS=-
SOLAR_ENERGY_COMPLETE=0 -> SE=-
AC_ENERGY_COMPLETE=0    -> AE=-
```

If a validity/complete bit is 1, its required fields must be present. `SOLAR_ENERGY_COMPLETE=1` implies `SOLAR_VALID=1`; `AC_ENERGY_COMPLETE=1` implies `AC_VALID=1`.

A real zero is encoded as `0`, never `-`.

## 6. D2T energy and freshness

Initial firmware policy:

```text
ENERGY_SAMPLE_PERIOD = 10 s
ENERGY_MAX_GAP       = 20 s
ELECTRICAL_MAX_AGE   = 20 s
GPS_MAX_AGE          = 5 s
nominal D2T interval = 1800 s, configurable
```

Energy is net signed energy estimated by trapezoidal integration of valid timestamped power acquisitions:

```text
dE_Wh = ((P0 + P1) / 2) * (t1 - t0) / 3600
```

A segment is integrated only when both acquisitions are valid and `0 < dt <= 20 s`. An invalid acquisition or a gap >20 s marks the corresponding energy complete flag false for the rest of that D2T period. No energy may be invented by holding the last sample or extrapolating partial energy.

The acquisition at the nominal boundary or the first acquisition immediately after it closes period A and becomes the starting point of period B. The previous trapezoid belongs only to A; the following trapezoid belongs only to B. `INT` is the actual covered duration rounded to seconds.

If the boundary acquisition is invalid, A is incomplete and B starts incomplete for that energy channel.

A D2 message is immutable once created. Retries resend the exact same bytes, sequence, RTC, measurements, flags and HMAC. New acquisitions feed the next period.

## 7. D2E grammar

Exactly 11 fields / 10 commas:

```text
D2E,DEV,SEQ,RTC,UP,EV,LAT,LON,DIST,F,AUTH
```

Initial event codes only:

```text
GX -> GEOFENCE_EXIT  -> OUTSIDE
GE -> GEOFENCE_ENTER -> INSIDE
```

The geofence state is derived and is not transported.

`DIST` is the geodesic distance in whole metres from the event GPS position to the configured geofence centre, range 0..1000000 m, or `-`.

D2E flags:

```text
bit0 RTC_VALID
bit1 GPS_VALID
bit2 DISTANCE_VALID
```

Encoded as exactly two base36 chars `00`..`07`. `DISTANCE_VALID=1` requires `GPS_VALID=1`.

## 8. Authentication

Each device uses a 32-byte random secret key provisioned outside Git.

The signed bytes are exactly:

```text
ASCII(",".join(all_fields_before_auth))
```

There is no final comma, CR, LF, whitespace normalization or padding.

```text
digest = HMAC-SHA-256(device_key, signed_bytes)
tag_bytes = digest[0:8]
AUTH = RFC4648 base64url(tag_bytes) without "=" padding
```

The authenticated tag is exactly 11 characters. Comparison must be constant-time.

Development mode permits `AUTH=-` and yields backend `auth_status = NOT_VERIFIED`. A present but incorrect HMAC is always rejected. Production mode requires a valid HMAC.

## 9. Sender binding

The raw sender is always retained. Production additionally requires a configured canonical E.164 sender <-> device_id association. A mismatch is archived/quarantined and creates no backend outbox. The phone number is not part of the HMAC because it is not authored by the transmitter.

## 10. Sequence, identity and message_id

One global uint32 sequence is shared by D2T and D2E:

```text
range = 1..4294967295
0 = forbidden
wrap = forbidden
reservation block = 256
```

The firmware must durably advance `next_unreserved` before using a reserved block. Unused numbers after reboot may be lost; sequence reuse is forbidden.

A new device starts D2_UNPROVISIONED and receives its technical device_id, HMAC key, counter state and provisioning metadata explicitly. Missing/corrupt counter state after provisioning causes D2_COUNTER_FAULT; it must never silently restart at 1.

Restoring an old counter backup is not an allowed recovery procedure. After irrecoverable counter-state loss, or after replacing the ESP32 without a provably safe counter migration, reprovision with a new technical device_id. The commercial kit identity may remain stable in the backend. After sequence 4294967295, reprovisioning with a new technical identity is required.

D2 urgent events must be durably stored on the transmitter after sequence assignment/HMAC construction and before being considered created, so a power loss does not lose the event.

`message_id` is not transported. DJUA_SMS derives:

```text
D2:<device_id>:<SEQ_BASE36>
```

The backend should enforce uniqueness on message_id.

## 11. Time semantics

D2 wire RTC is Unix UTC seconds. D2 v1 is configured for GMT+1 presentation. If RTC is invalid, RTC is `-` and no backend timestamp/timezone is emitted. The absolute maximum RTC value is 2099-12-31T23:59:59Z; formatting that instant at GMT+1 naturally yields 2100-01-01T00:59:59+01:00.

`UP` is ESP32 uptime in milliseconds, not Unix time. For compatibility the D2T backend payload carries both `uptime_ms` and legacy `timestamp_ms` with the same uptime value.

`gateway_received_at` is the UTC time of first durable local ingestion in DJUA_SMS. It is generated by the gateway, is not on the SMS, and is preserved across modem rereads and MQTT retries.

## 12. Backend mapping

D2T topic:

```text
djua/test/<device_id>/telemetry
```

D2E topic:

```text
djua/test/<device_id>/geofence/events
```

D2T adds `protocol`, `message_id`, `sequence`, `uptime_ms`, `gateway_received_at`, `validity`, and `auth_status` while retaining the current business groups `kit_id`, legacy `timestamp_ms`, optional `timestamp/timezone`, `interval_seconds`, `latitude/longitude`, `battery`, `solar`, and `ac_load`.

D2 uses JSON `null` for unavailable measurement values; a valid measured zero remains numeric zero. D1 keeps its historical normalization unchanged.

D2E emits `protocol`, `message_id`, `sequence`, `kit_id`, `uptime_ms`, optional `timestamp/timezone`, `gateway_received_at`, `event`, derived `state`, `position_usable`, nullable `latitude/longitude`, nullable `distance_m`, `validity`, and `auth_status`.

The real backend has not yet been validated against this D2 JSON contract. Do not claim end-to-end compatibility until that validation occurs.

## 13. Size proof

D2T worst-case field lengths including signed SE and AE sum to 139 characters. There are 21 commas:

```text
139 + 21 = 160 septets
```

D2T maximum authenticated length is exactly 160 septets.

D2E worst-case field lengths sum to 87 characters plus 10 commas:

```text
87 + 10 = 97 septets
```

D2E maximum authenticated length is 97 septets.

A valid encoder must reject any constructed message >160 septets; it must never truncate or concatenate it.

## 14. Conformance vectors

Machine-readable vectors live in:

```text
tests/vectors/d2_conformance.json
```

Official public test key (tests only, never production):

```text
000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F
```

Vectors contain exact signed bytes, final SMS, GSM-7 length, expected HMAC, decoded values, expected backend topic/payload or expected validation error.
