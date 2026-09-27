# Contrat MQTT DJUA observé

## 1. Source et statut

Ce document décrit le contrat MQTT observé en lecture seule dans :

```text
toussaintmadimba-cmyk/DJUA
branche main
```

```text
DJUA = READ ONLY
```

Les faits issus du firmware ou de l'API sont marqués **CONFIRMÉ PAR DJUA**. Les décisions propres à la gateway sont marquées **CHOIX D'ARCHITECTURE DJUA_SMS**.

## 2. Topics actuels

**CONFIRMÉ PAR DJUA**

Le firmware construit les topics à partir de :

```text
MQTT_TOPIC_PREFIX = djua/test
DEVICE_ID         = DJUA-KIN-000001
```

Formes observées :

```text
djua/test/<device_id>/telemetry
djua/test/<device_id>/status
djua/test/<device_id>/geofence
djua/test/<device_id>/geofence/events
```

Pour le boîtier actuellement configuré :

```text
djua/test/DJUA-KIN-000001/telemetry
```

L'API DJUA s'abonne par défaut à :

```text
djua/test/+/#
```

et reconnaît explicitement les formes `telemetry`, `geofence` et `geofence/events`.

## 3. Payload télémétrie réellement publié

**CONFIRMÉ PAR DJUA**

Structure MQTT observée :

```json
{
  "kit_id": "DJUA-KIN-000001",
  "timestamp_ms": 123456,
  "timestamp": "2026-09-27T16:30:00+01:00",
  "timezone": "GMT+1",
  "interval_seconds": 1800,
  "latitude": -4.3251,
  "longitude": 15.3222,
  "battery": {
    "voltage_v": 12.4,
    "current_a": 0.5,
    "power_w": 6.2
  },
  "solar": {
    "voltage_v": 18.2,
    "current_a": 1.23,
    "power_w": 22.39,
    "energy_interval_wh": 11.195
  },
  "ac_load": {
    "voltage_v": 230.1,
    "current_a": 1.25,
    "active_power_w": 244.5,
    "apparent_power_va": 287.6,
    "energy_interval_wh": 122.25
  }
}
```

## 4. Champs et unités

| JSON | Source interne | Unité | Publication MQTT |
|---|---|---|---|
| `kit_id` | `DEVICE_ID` | — | toujours |
| `timestamp_ms` | `millis()` | ms depuis boot | toujours |
| `timestamp` | DS1302 formaté | ISO 8601 | seulement si RTC valide |
| `timezone` | `RTC_TIMEZONE_LABEL` | label | seulement si RTC valide |
| `interval_seconds` | `TelemetryData.intervalSeconds` | s | toujours |
| `latitude` | GPS / TelemetryData | degrés | toujours |
| `longitude` | GPS / TelemetryData | degrés | toujours |
| `battery.voltage_v` | batterie INA219 | V | toujours |
| `battery.current_a` | batterie INA219 | A | toujours |
| `battery.power_w` | batterie INA219 | W | toujours |
| `solar.voltage_v` | solaire INA219 | V | toujours, valeur ou `null` |
| `solar.current_a` | solaire INA219 | A | toujours, valeur ou `null` |
| `solar.power_w` | solaire INA219 | W | toujours, valeur ou `null` |
| `solar.energy_interval_wh` | calcul intervalle | Wh | toujours, valeur ou `null` |
| `ac_load.voltage_v` | ZMPT101B | V RMS | toujours |
| `ac_load.current_a` | ACS712 | A RMS | toujours |
| `ac_load.active_power_w` | calcul v(t)*i(t) | W | toujours |
| `ac_load.apparent_power_va` | calcul RMS | VA | toujours |
| `ac_load.energy_interval_wh` | puissance active * durée | Wh | toujours |

## 5. timestamp_ms n'est pas un timestamp Unix

**CONFIRMÉ PAR DJUA**

Le firmware publie :

```cpp
doc["timestamp_ms"] = millis();
```

Il s'agit donc du temps écoulé depuis le démarrage de l'ESP32.

**CHOIX D'ARCHITECTURE DJUA_SMS**

D1 transporte cette valeur sous forme compacte en base36 puis DJUA_SMS la restitue en entier dans `timestamp_ms`.

La gateway ne doit pas remplacer cette valeur par son heure locale de réception.

## 6. RTC invalide

**CONFIRMÉ PAR DJUA**

Pour MQTT, lorsque `TelemetryData.timestampValid == false` :

- `timestamp` n'est pas ajouté ;
- `timezone` n'est pas ajouté ;
- `timestamp_ms` reste présent.

Le transport HTTP actuel possède un comportement de repli différent et peut construire un timestamp historique basé sur `millis()`.

**CHOIX D'ARCHITECTURE DJUA_SMS**

La gateway cible MQTT. Elle reproduit donc le comportement MQTT, pas le fallback HTTP.

## 7. GPS invalide

**CONFIRMÉ PAR DJUA**

`buildTelemetry()` place :

```text
latitude  = 0.0
longitude = 0.0
```

lorsqu'aucun fix GPS valide/récent n'est disponible.

Aucun champ `gps_valid` n'est publié dans MQTT.

**CHOIX D'ARCHITECTURE DJUA_SMS**

D1 conserve un bit de validité GPS pour éviter l'ambiguïté pendant le transport, mais le normalizer publie `0.0/0.0` afin de rester compatible avec le contrat actuel.

## 8. Solaire invalide

**CONFIRMÉ PAR DJUA**

La structure interne actuelle contient :

```text
solarVoltage
solarCurrent
solarPower
solarEnergyIntervalWh
solarMeasurementValid
```

Lorsque la mesure solaire est invalide, le firmware MQTT publie explicitement :

```json
"solar": {
  "voltage_v": null,
  "current_a": null,
  "power_w": null,
  "energy_interval_wh": null
}
```

Les tests backend distinguent explicitement un solaire indisponible (`null`) d'une mesure valide égale à zéro (`0.0`).

DJUA_SMS doit préserver cette distinction.

## 9. Batterie et AC invalides

**CONFIRMÉ PAR DJUA**

`TelemetryData` est initialisé à zéro.

Les champs batterie et AC ne sont renseignés que si leurs mesures sont valides. Le JSON MQTT publie toutefois toujours leurs objets.

Conséquence observée lorsqu'une mesure est invalide :

- batterie : valeurs numériques à zéro ;
- AC : valeurs numériques à zéro.

Les flags `batteryMeasurementValid` et `acMeasurementValid` existent en interne mais ne sont pas publiés.

**CHOIX D'ARCHITECTURE DJUA_SMS**

D1 conserve ces validités dans ses flags, puis le normalizer reproduit les zéros attendus sans ajouter de nouveaux champs backend.

## 10. TelemetryData vs MQTT

**CONFIRMÉ PAR DJUA**

La structure interne actuelle possède plus de données que le contrat MQTT.

| Élément interne | Dans TelemetryData | Dans MQTT télémétrie |
|---|---:|---:|
| timestamp | oui | oui si valide |
| timestampValid | oui | non |
| latitude / longitude | oui | oui |
| batterie V/A/W | oui | oui |
| batteryMeasurementValid | oui | non |
| solaire V/A/W/Wh | oui | oui |
| solarMeasurementValid | oui | non |
| AC V/A/W/VA/Wh | oui | oui |
| acPowerFactor | oui | non |
| acEnergyIntervalVAh | oui | non |
| acMeasurementValid | oui | non |
| intervalSeconds | oui | oui |

Règle de la gateway :

```text
reproduire ce qui est réellement publié sur MQTT
!=
exposer automatiquement tout TelemetryData
```

## 11. Mapping D1 -> MQTT

**CHOIX D'ARCHITECTURE DJUA_SMS**

```text
D1.device_id     -> kit_id
D1.uptime36      -> timestamp_ms
D1.rtc + tz_min  -> timestamp + timezone si RTC valide
D1.interval      -> interval_seconds
D1.lat/lon       -> latitude/longitude ou 0.0/0.0 si GPS invalide

D1 batt_*        -> battery.*
D1 solar_*       -> solar.*
D1 ac_*          -> ac_load.*

D1.protocol      -> non publié
D1.seq           -> non publié
D1.flags         -> non publié
D1.auth          -> non publié
```

Aucun nouveau champ backend n'est créé par défaut.

## 12. MQTT actuel du firmware

**CONFIRMÉ PAR DJUA**

Le firmware actuel :

- utilise PubSubClient ;
- se connecte au broker configuré dans `config.h` ;
- utilise un Client ID de la forme `djua-<DEVICE_ID>` ;
- publie la télémétrie avec retain = false ;
- utilise le QoS de publication par défaut de PubSubClient, donc QoS 0 ;
- publie `online` / Last Will `offline` sur le topic `status`.

Ces faits décrivent le firmware de référence et ne sont pas automatiquement les choix de la gateway.

## 13. MQTT de DJUA_SMS

**CHOIX D'ARCHITECTURE DJUA_SMS**

### Client ID

La gateway doit posséder son propre Client ID, par exemple :

```text
djua-sms-gateway-<instance_id>
```

Elle ne doit jamais utiliser :

```text
djua-<device_id>
```

car deux clients MQTT portant le même Client ID peuvent se déconnecter mutuellement.

### Topic de télémétrie

```text
djua/test/<device_id>/telemetry
```

tant que le contrat de référence utilise ce préfixe.

Le préfixe devra être configurable dans la gateway, mais sa valeur par défaut de compatibilité restera celle observée pendant cette phase.

### QoS

Proposition :

```text
QoS 1
```

pour la publication gateway -> broker.

Objectif : obtenir une confirmation broker et rendre l'outbox persistante exploitable.

### Retain

Pour la télémétrie :

```text
retain = false
```

comme le comportement actuel.

### PUBACK

Avec QoS 1, une confirmation signifie que le broker a accepté la publication.

Elle ne prouve pas que le backend DJUA a traité ou persisté le message.

La terminologie doit donc rester précise :

```text
PUBLISHED = confirmé par le broker
!=
confirmé end-to-end par le backend
```

### Reconnexion

Le publisher doit pouvoir se reconnecter sans perdre les entrées de l'outbox.

La stratégie temporelle exacte de backoff sera définie lors de l'implémentation et ne doit pas être figée arbitrairement dans cette phase.

## 14. Topic status

**CONFIRMÉ PAR DJUA**

Le topic :

```text
djua/test/<device_id>/status
```

décrit actuellement la connexion MQTT du boîtier lui-même.

**CHOIX D'ARCHITECTURE DJUA_SMS**

La gateway ne doit pas publier artificiellement :

```text
<device_id>/status = online
```

car cela ferait croire que l'ESP32 est connecté directement à Internet.

La santé de la gateway doit être exposée séparément si un contrat dédié est créé ultérieurement.

## 15. Contrats hors télémétrie

**CONFIRMÉ PAR DJUA**

Des topics geofence existent également.

Ils sont documentés comme faits observés mais ne sont pas inclus dans le protocole SMS D1 de cette phase.

Toute prise en charge future doit être spécifiée séparément sans modifier silencieusement le contrat D1.
