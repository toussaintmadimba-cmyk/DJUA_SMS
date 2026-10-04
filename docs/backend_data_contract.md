# Contrat de données DJUA_SMS → équipe Backend

## 1. Objet du document

Ce document définit le **contrat de données que l'équipe backend doit recevoir depuis DJUA_SMS via MQTT**.

Il décrit uniquement le payload réellement produit aujourd'hui par la gateway et les règles nécessaires pour l'interpréter correctement.

Source de vérité actuelle :

```text
DJUA_SMS
→ protocol/normalizer.py
→ services/ingestion.py
→ mqtt_outbox
→ MQTT
```

Le dépôt firmware `DJUA` reste une référence historique du contrat mais n'est pas modifié par DJUA_SMS.

---

## 2. Canal de transport

### Topic télémétrie

Format :

```text
djua/test/<device_id>/telemetry
```

Exemple :

```text
djua/test/DJUA-KIN-000001/telemetry
```

Le préfixe `djua/test` est configurable dans DJUA_SMS, mais il constitue la valeur de compatibilité actuelle.

### MQTT

Valeurs utilisées par DJUA_SMS :

```text
QoS    = 1
retain = false
```

Conséquence importante :

```text
QoS 1 = livraison at least once
```

Un même message peut donc être publié plus d'une fois dans certains scénarios de panne.

Le backend ne doit pas considérer MQTT QoS 1 comme une garantie `exactly once`.

---

## 3. Payload de référence

Exemple complet :

```json
{
  "kit_id": "DJUA-KIN-000001",
  "timestamp_ms": 123456789,
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
    "energy_interval_wh": 11.2
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

Le backend ne doit pas dépendre de l'ordre des clés JSON.

---

## 4. Schéma fonctionnel

| Champ | Type JSON | Obligatoire | Nullable | Unité / sens |
| --- | --- | ---: | ---: | --- |
| `kit_id` | string | oui | non | identifiant du boîtier |
| `timestamp_ms` | integer | oui | non | millisecondes depuis le démarrage ESP32 |
| `timestamp` | string | non | — | date/heure RTC au format ISO 8601 |
| `timezone` | string | non | — | actuellement `GMT+1` |
| `interval_seconds` | integer | oui | non | durée de l'intervalle de mesure |
| `latitude` | number | oui | non | degrés |
| `longitude` | number | oui | non | degrés |
| `battery.voltage_v` | number | oui | non | volts |
| `battery.current_a` | number | oui | non | ampères |
| `battery.power_w` | number | oui | non | watts |
| `solar.voltage_v` | number ou null | oui | oui | volts |
| `solar.current_a` | number ou null | oui | oui | ampères |
| `solar.power_w` | number ou null | oui | oui | watts |
| `solar.energy_interval_wh` | number ou null | oui | oui | Wh produits sur l'intervalle |
| `ac_load.voltage_v` | number | oui | non | volts RMS |
| `ac_load.current_a` | number | oui | non | ampères RMS |
| `ac_load.active_power_w` | number | oui | non | watts actifs |
| `ac_load.apparent_power_va` | number | oui | non | voltampères |
| `ac_load.energy_interval_wh` | number | oui | non | Wh consommés sur l'intervalle |

---

## 5. Règles par champ

### 5.1 kit_id

Exemple :

```text
DJUA-KIN-000001
```

Règle actuelle de validation :

```text
[A-Z0-9-]{1,32}
```

Le `kit_id` du payload provient du même `device_id` que celui utilisé dans le topic.

Donc, pour un message conforme :

```text
topic device_id == payload.kit_id
```

Le backend peut vérifier cette cohérence.

---

### 5.2 timestamp_ms

`timestamp_ms` **n'est pas un timestamp Unix**.

Il représente :

```text
ESP32 millis()
```

donc le temps écoulé depuis le démarrage de l'ESP32.

Plage attendue :

```text
0 ... 4294967295
```

Conséquences :

- il peut repartir de zéro après redémarrage ;
- il peut diminuer après wrap de `millis()` ;
- il ne doit pas être utilisé seul comme identifiant unique global ;
- il ne doit pas être converti directement en date UTC.

---

### 5.3 timestamp et timezone

Ces deux champs sont présents uniquement lorsque le RTC terrain est considéré valide.

Exemple :

```json
{
  "timestamp": "2026-09-27T16:30:00+01:00",
  "timezone": "GMT+1"
}
```

Lorsque le RTC est invalide :

```text
timestamp absent
timezone absent
```

Le backend doit donc les considérer comme **optionnels**, et non comme des champs toujours présents à `null`.

À l'état actuel du contrat, DJUA_SMS valide uniquement le fuseau :

```text
GMT+1
+60 minutes
```

---

### 5.4 interval_seconds

Nombre entier strictement positif.

Il représente la durée à laquelle les valeurs d'énergie de type :

```text
energy_interval_wh
```

se rapportent.

Ces valeurs sont des **énergies sur l'intervalle**, pas des compteurs d'énergie cumulée à vie.

---

## 6. GPS

### GPS valide

Exemple :

```json
{
  "latitude": -4.3251,
  "longitude": 15.3222
}
```

### GPS invalide

Le contrat backend actuel publie :

```json
{
  "latitude": 0.0,
  "longitude": 0.0
}
```

Il n'existe actuellement aucun champ :

```text
gps_valid
```

dans le payload backend.

### Limitation importante

Le backend ne peut donc pas distinguer avec certitude :

```text
GPS invalide
```

de :

```text
position réelle 0.0 / 0.0
```

à partir du payload seul.

Ne pas interpréter automatiquement `0.0 / 0.0` comme une position géographique fiable.

---

## 7. Batterie

Objet toujours présent :

```json
"battery": {
  "voltage_v": 12.4,
  "current_a": 0.5,
  "power_w": 6.2
}
```

Si la mesure batterie est invalide, le contrat actuel produit :

```json
"battery": {
  "voltage_v": 0.0,
  "current_a": 0.0,
  "power_w": 0.0
}
```

Il n'existe actuellement aucun champ backend :

```text
battery_valid
```

Le backend ne doit donc pas supposer qu'un triple zéro prouve une mesure valide.

Les valeurs de courant et puissance peuvent être signées. Ne pas rejeter une valeur uniquement parce qu'elle est négative sans règle métier explicitement définie.

---

## 8. Solaire

Objet toujours présent.

### Mesure solaire valide

Exemple :

```json
"solar": {
  "voltage_v": 18.2,
  "current_a": 1.23,
  "power_w": 22.39,
  "energy_interval_wh": 11.2
}
```

### Mesure solaire valide mais production nulle

Exemple :

```json
"solar": {
  "voltage_v": 18.2,
  "current_a": 0.0,
  "power_w": 0.0,
  "energy_interval_wh": 0.0
}
```

Ces valeurs représentent une mesure valide à zéro.

### Mesure solaire invalide / indisponible

Le contrat impose :

```json
"solar": {
  "voltage_v": null,
  "current_a": null,
  "power_w": null,
  "energy_interval_wh": null
}
```

### Règle backend importante

```text
null != 0.0
```

Interprétation :

```text
null
= mesure solaire indisponible / invalide

0.0
= mesure valide dont la valeur est réellement zéro
```

Cette distinction doit être conservée dans la base backend et dans les traitements analytiques.

---

## 9. Charge AC

Objet toujours présent :

```json
"ac_load": {
  "voltage_v": 230.1,
  "current_a": 1.25,
  "active_power_w": 244.5,
  "apparent_power_va": 287.6,
  "energy_interval_wh": 122.25
}
```

Si la mesure AC est invalide, le contrat actuel produit :

```json
"ac_load": {
  "voltage_v": 0.0,
  "current_a": 0.0,
  "active_power_w": 0.0,
  "apparent_power_va": 0.0,
  "energy_interval_wh": 0.0
}
```

Il n'existe actuellement aucun champ backend :

```text
ac_valid
```

Le backend ne doit donc pas considérer automatiquement des zéros comme preuve d'une mesure valide.

Les valeurs peuvent être signées ; DJUA_SMS ne rejette pas une valeur uniquement parce qu'elle est négative.

---

## 10. Champs volontairement absents

Les informations suivantes existent dans le transport D1 ou dans les structures internes, mais **ne sont pas publiées au backend** actuellement :

```text
protocol
sequence
flags
auth
rtc_valid
gps_valid
battery_valid
solar_valid
ac_valid
ac_power_factor
ac_energy_interval_vah
raw SMS
sender GSM
timestamp modem
```

Le backend ne doit pas dépendre de ces champs dans le contrat actuel.

---

## 11. Champs de transport SMS ≠ contrat backend

D1 contient des données nécessaires uniquement pour transporter, valider ou dédupliquer un SMS.

Par exemple :

```text
sequence
flags
auth
```

Ces champs ne sont pas copiés dans le JSON MQTT.

Principe :

```text
contrat SMS
!=
contrat MQTT backend
```

DJUA_SMS agit comme couche de traduction entre les deux.

---

## 12. Sérialisation JSON

DJUA_SMS sérialise l'outbox avec une représentation JSON déterministe :

```text
sort_keys=True
separators=(",", ":")
allow_nan=False
```

Cela signifie notamment que :

- `NaN` et `Infinity` ne sont pas autorisés ;
- le backend doit néanmoins traiter le payload comme un objet JSON, pas comme une chaîne dont l'ordre des clés serait contractuel.

---

## 13. Sémantique de livraison

Pipeline réel :

```text
SMS reçu
→ SQLite durable
→ mqtt_outbox PENDING
→ publication MQTT
→ PUBACK broker
→ mqtt_outbox PUBLISHED
```

La confirmation :

```text
PUBLISHED
```

signifie :

```text
le broker MQTT a accusé réception
```

Elle ne signifie pas :

```text
le backend métier a persisté ou traité le message
```

---

## 14. Doublons possibles côté backend

MQTT QoS 1 fournit une garantie **at least once**.

Scénario possible :

```text
gateway publie
→ broker accepte
→ PUBACK
→ crash gateway avant commit SQLite PUBLISHED
→ redémarrage
→ republication
```

Le backend doit donc être préparé à recevoir occasionnellement deux payloads identiques ou équivalents.

### Limitation actuelle

Le payload backend ne contient actuellement ni :

```text
message_id
sequence
logical_dedupe_key
```

Le backend ne peut donc pas obtenir une idempotence parfaite à partir d'un identifiant de message fourni par DJUA_SMS.

Ne pas utiliser `timestamp_ms` seul comme identifiant unique, car il peut redémarrer à zéro ou wrap.

Si une déduplication backend forte devient nécessaire, elle devra faire l'objet d'une évolution explicite du contrat.

---

## 15. Topic status

Le topic historique :

```text
djua/test/<device_id>/status
```

décrit la connexion MQTT directe d'un boîtier DJUA.

DJUA_SMS ne publie pas artificiellement :

```text
<device_id>/status = online
```

car cela ferait croire que l'ESP32 est connecté directement au broker.

La santé de la gateway nécessite un contrat séparé si elle doit être exposée ultérieurement.

---

## 16. Geofence

Des topics geofence existent dans le système DJUA de référence :

```text
djua/test/<device_id>/geofence
djua/test/<device_id>/geofence/events
```

Ils ne font pas partie du contrat télémétrie D1 actuel de DJUA_SMS.

Ce document ne spécifie donc que :

```text
.../<device_id>/telemetry
```

---

## 17. Contraintes recommandées côté backend

Sans modifier le contrat actuel, l'équipe backend peut valider au minimum :

```text
kit_id                : string non vide
timestamp_ms          : integer >= 0
interval_seconds      : integer > 0
latitude              : number
longitude             : number
battery               : objet présent
solar                 : objet présent
ac_load               : objet présent
timestamp/timezone    : tous les deux présents ou tous les deux absents
topic device_id       : égal à payload.kit_id
```

Pour `solar.*`, accepter :

```text
number
ou
null
```

Pour batterie et AC, accepter les zéros tels que publiés aujourd'hui.

---

## 18. Exemple RTC invalide

Payload valide sans RTC :

```json
{
  "kit_id": "DJUA-KIN-000001",
  "timestamp_ms": 123456789,
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
    "energy_interval_wh": 11.2
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

L'absence de `timestamp` et `timezone` est normale dans ce cas.

---

## 19. Exemple solaire indisponible

```json
{
  "solar": {
    "voltage_v": null,
    "current_a": null,
    "power_w": null,
    "energy_interval_wh": null
  }
}
```

Le backend doit conserver ces `null`.

Il ne doit pas les remplacer automatiquement par `0.0`.

---

## 20. Exemple solaire valide à zéro

```json
{
  "solar": {
    "voltage_v": 18.2,
    "current_a": 0.0,
    "power_w": 0.0,
    "energy_interval_wh": 0.0
  }
}
```

Ici les zéros sont de vraies valeurs mesurées/normalisées.

---

## 21. Contrat minimal à retenir par l'équipe backend

```text
TOPIC
djua/test/<kit_id>/telemetry

DELIVERY
QoS 1
retain false
at least once

IDENTITÉ
kit_id = identifiant boîtier

TEMPS
timestamp_ms = uptime ESP32, pas Unix
timestamp/timezone = optionnels

GPS
toujours numérique
0.0/0.0 = convention d'invalidité actuelle mais ambiguë

BATTERIE
objet toujours présent
mesure invalide -> 0.0

SOLAIRE
objet toujours présent
invalide -> null
valide à zéro -> 0.0

AC
objet toujours présent
mesure invalide -> 0.0

ÉNERGIE
energy_interval_wh = énergie de l'intervalle
pas compteur cumulatif

DOUBLONS
possibles à cause du QoS 1 / crash
pas de message_id backend actuellement
```

---

## 22. Évolution du contrat

Toute évolution nécessitant l'ajout, la suppression ou la modification sémantique d'un champ backend doit être explicite.

Exemples d'évolutions qui nécessiteraient une nouvelle décision de contrat :

- ajout de `gps_valid` ;
- ajout de `battery_valid` ou `ac_valid` ;
- ajout d'un `message_id` ;
- ajout de `sequence` ;
- ajout de `power_factor` ;
- prise en charge geofence via DJUA_SMS ;
- changement de sémantique de `timestamp_ms` ;
- remplacement des zéros invalides batterie/AC par `null`.

Ne pas introduire ces changements silencieusement.

---

## 23. Statut actuel

Ce contrat est aligné avec l'implémentation actuelle de DJUA_SMS :

```text
protocol/models.py
protocol/normalizer.py
services/ingestion.py
mqtt_outbox
```

Les comportements essentiels sont couverts par les tests automatisés existants, notamment :

- payload complet ;
- RTC absent ;
- GPS invalide ;
- batterie invalide ;
- solaire `null` ;
- solaire valide à `0.0` ;
- AC invalide ;
- absence des champs de transport D1 dans le payload backend.

---

# Contrat D2 ajouté

Le contrat précédent décrit le comportement historique D1. D2 l'étend sans modifier D1.

## D2T

Topic : `djua/test/<device_id>/telemetry`.

Le payload D2T conserve `kit_id`, `timestamp_ms` (uptime historique), `timestamp/timezone` optionnels, `interval_seconds`, `latitude/longitude`, `battery`, `solar` et `ac_load`, et ajoute :

- `protocol: D2T` ;
- `message_id` ;
- `sequence` ;
- `uptime_ms` ;
- `gateway_received_at` ;
- `validity` ;
- `auth_status`.

Pour D2, une donnée indisponible est `null` ; une vraie mesure zéro reste numérique zéro. Les énergies solaire et AC sont nettes et signées. La complétude énergétique est indépendante de la validité de la dernière mesure.

## D2E

Topic : `djua/test/<device_id>/geofence/events`.

`GX` devient `event=GEOFENCE_EXIT`, `state=OUTSIDE`. `GE` devient `event=GEOFENCE_ENTER`, `state=INSIDE`.

Le payload contient `protocol`, `message_id`, `sequence`, `kit_id`, `uptime_ms`, `gateway_received_at`, timestamp/timezone si RTC valide, event/state, `position_usable`, latitude/longitude nullable, `distance_m` nullable, `validity` et `auth_status`.

`distance_m` est la distance géodésique entière au centre de la geofence.

## Idempotence et statut

`message_id = D2:<device_id>:<sequence_base36>` doit servir de clé d'idempotence backend. QoS 1 reste at-least-once.

Valeurs auth_status : `VERIFIED` et `NOT_VERIFIED`. `NOT_VERIFIED` n'est publiable qu'en mode développement.

**La compatibilité du backend réel avec ce JSON D2 n'est pas validée.** Les tests actuels couvrent le payload et MQTT avec doubles logiciels.
