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
MQTT publisher
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

**TESTÉ AUTOMATIQUEMENT**

Le transport est séparé en trois responsabilités :

```text
PahoMqttClient
    ↓
MqttPublisher
    ↓
MqttOutboxWorker
```

- `PahoMqttClient` gère connexion, déconnexion, reconnexion et callbacks Paho ;
- `MqttPublisher` publie exactement `topic` et `payload_json` de l'outbox et associe `mid -> outbox_id` ;
- `MqttOutboxWorker` charge les lignes `PENDING` dues par ordre d'id et déclenche les publications.

Le worker ne parse pas D1 et ne renormalise pas la télémétrie.

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

## 8. Publication MQTT

**TESTÉ AUTOMATIQUEMENT avec client simulé**

La publication suit maintenant :

```text
mqtt_outbox PENDING
-> publish(topic, payload_json, qos, retain)
-> mid
-> PUBACK correspondant
-> mark_outbox_published(outbox_id)
```

Un simple retour de `publish()` ne suffit jamais à marquer la ligne `PUBLISHED`.

En cas d'échec immédiat ou de timeout PUBACK, `record_publish_failure()` incrémente `attempt_count`, conserve le payload et planifie `next_attempt_at`.

## 9. Hors périmètre

Non implémentés :

- SIM800L ;
- pyserial ;
- AT commands ;
- daemon ;
- service Windows ;
- Docker.

Les comportements modem et end-to-end restent à valider dans les phases correspondantes.


## 10. Client ID et multi-device

Le Client ID par défaut de la gateway est :

```text
djua-sms-gateway-001
```

Il est indépendant du `device_id` des SMS. Un seul client gateway peut publier les topics de plusieurs boîtiers.

## 11. Limite de garantie

QoS 1 fournit une livraison **at least once** vers le broker. Si le broker a accepté un message mais que le processus meurt avant le commit SQLite de `PUBLISHED`, l'outbox reste `PENDING` et une republication est possible.
