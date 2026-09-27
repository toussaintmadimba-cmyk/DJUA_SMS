# Architecture DJUA_SMS

> `toussaintmadimba-cmyk/DJUA` reste **READ ONLY**.

## 1. Architecture cible

```text
CAPTEURS DJUA
    |
    v
ESP32
    |
    v
SIM800L émetteur
    |
    v
SMS / réseau GSM
    |
    v
SIM800L récepteur
    |
    v
DJUA_SMS
    |
    +--> stockage brut SQLite
    +--> déduplication brute
    +--> parser D1
    +--> validator
    +--> déduplication logique
    +--> normalizer
    +--> MQTT outbox SQLite
    |
    v
MQTT publisher (phase future)
    |
    v
broker
    |
    v
backend DJUA
```

Le SMS est le transport cible officiel du boîtier. Il n'est pas un fallback du Wi-Fi.

## 2. Architecture DJUA actuelle — référence uniquement

**CONFIRMÉ PAR DJUA**

Le dépôt de référence contient encore un chemin direct :

```text
ESP32 -> Wi-Fi -> MQTT / HTTP -> backend
```

DJUA_SMS utilise ce code uniquement pour comprendre le contrat existant. Il ne le modifie pas.

## 3. Frontières de modules

### protocol

**TESTÉ AUTOMATIQUEMENT**

Responsable de :

- parsing D1 ;
- base36 ;
- flags ;
- validation ;
- normalisation vers le contrat MQTT.

Il ne connaît ni SQLite, ni port série, ni broker.

### storage

**TESTÉ AUTOMATIQUEMENT**

Responsable de :

- création/version du schéma SQLite ;
- stockage durable des SMS bruts ;
- contraintes UNIQUE ;
- clés de déduplication ;
- outbox ;
- reprise des éléments `PENDING` ;
- transitions `PUBLISHED` / échecs futurs.

Il ne connaît ni le modem ni le broker.

### services/ingestion

**TESTÉ AUTOMATIQUEMENT**

Orchestre :

```text
RawSmsInput
-> store_raw_sms()
-> parse_d1()
-> validate_telemetry()
-> normalize_to_mqtt()
-> queue_valid_sms()
```

Il ne publie aucun paquet réseau.

### modem / SMS receiver

**À VALIDER AVEC SIM800L RÉEL**

Non implémentés dans cette phase.

### MQTT publisher

**PHASE FUTURE**

Non implémenté. Il consommera l'outbox persistante.

## 4. Frontière de non-perte

**TESTÉ AUTOMATIQUEMENT côté SQLite**

La première transaction est indépendante du parsing :

```text
SMS brut
    |
    v
INSERT inbound_sms
    |
    v
COMMIT
```

`store_raw_sms()` ne retourne `STORED` qu'après la réussite de cette transaction.

Le futur driver SIM800L pourra donc interpréter :

```text
STORED ou DUPLICATE
= une copie durable existe déjà
```

et seulement ensuite envisager la suppression dans le modem.

La suppression modem réelle reste à tester matériellement.

## 5. Pipeline d'ingestion implémenté

```text
RawSmsInput
    |
    v
persistance brute
    |
    +--> DUPLICATE_RAW : arrêt sans seconde ligne
    |
    v
parse
    |
    +--> erreur : inbound_sms = INVALID
    |
    v
validation
    |
    +--> INVALID_FORMAT : inbound_sms = INVALID
    |
    v
déduplication logique
    |
    +--> DUPLICATE_LOGICAL : pas de seconde outbox
    |
    v
normalisation MQTT
    |
    v
transaction atomique
    |
    +--> inbound_sms = QUEUED
    +--> mqtt_outbox = PENDING
```

Pour un SMS valide, la mise à jour de `inbound_sms` et l'insertion dans `mqtt_outbox` sont effectuées dans la même transaction SQLite. Un échec d'insertion outbox provoque le rollback de l'état `QUEUED`.

## 6. Multi-device

**TESTÉ AUTOMATIQUEMENT**

Le `device_id` est inclus dans l'identité logique et dans le topic :

```text
djua/test/<device_id>/telemetry
```

Des séquences identiques sur plusieurs boîtiers ne créent pas de collision.

## 7. Reprise après redémarrage

**TESTÉ AUTOMATIQUEMENT**

Une nouvelle instance de `SmsRepository` ouverte sur le même fichier SQLite retrouve les outbox :

```text
status = PENDING
```

via `list_pending_outbox()`.

Aucune entrée `PENDING` n'est supprimée automatiquement au démarrage.

## 8. Publication future

Le repository expose déjà :

- `mark_outbox_published()` ;
- `record_publish_failure()`.

Mais aucun broker n'est contacté dans cette phase.

Le futur publisher devra utiliser ces APIs après résultat réseau réel, notamment après confirmation broker lorsque QoS 1 sera utilisé.

## 9. Hors périmètre

Non implémentés :

- SIM800L ;
- pyserial ;
- AT commands ;
- MQTT réseau ;
- paho-mqtt ;
- daemon ;
- service Windows ;
- Docker.

Les comportements modem et end-to-end restent à valider dans les phases correspondantes.
