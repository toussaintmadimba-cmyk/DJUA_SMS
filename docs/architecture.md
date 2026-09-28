# Architecture DJUA_SMS

> `toussaintmadimba-cmyk/DJUA` reste strictement **READ ONLY**.

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
PySerialTransport
    |
    v
AtProtocol
    |
    v
Sim800Modem
    |
    v
SmsReceiver
    |
    v
SmsIngestionService
    |
    +--> inbound_sms
    +--> parser / validator D1
    +--> déduplication
    +--> normalizer
    +--> mqtt_outbox PENDING
    |
    v
MqttOutboxWorker
    |
    v
PahoMqttClient
    |
    v
broker
    |
    v
backend DJUA
```

Le boîtier terrain cible SMS comme transport. DJUA_SMS transforme ensuite le SMS en contrat MQTT compatible.

## 2. DJUA comme référence

Le dépôt DJUA peut être lu pour comprendre :

- le contrat de télémétrie ;
- les topics ;
- les noms de champs ;
- les unités.

Il n'est jamais modifié par ce projet.

## 3. Couche GSM

### serial_transport

**TESTÉ AUTOMATIQUEMENT**

Responsable uniquement du port série :

```text
open
close
write
read
timeouts
buffers
reconnect
```

Il ne connaît ni SMS, ni D1, ni SQLite, ni MQTT.

### at_protocol

**TESTÉ AUTOMATIQUEMENT**

Responsable de :

```text
AT command
response lines
OK
ERROR
+CME ERROR
+CMS ERROR
timeout
URC queue
```

Les notifications `+CMTI` intercalées pendant une commande sont conservées.

### modem

**TESTÉ AUTOMATIQUEMENT avec transport simulé**

Responsable de :

- AT ;
- CMEE ;
- CPIN ;
- CREG ;
- CSQ ;
- CMGF ;
- CPMS ;
- CNMI ;
- CMTI ;
- CMGR ;
- CMGL ;
- CMGD.

Le comportement physique du SIM800L reste **À VALIDER AVEC SIM800L RÉEL**.

### sms_receiver

**TESTÉ AUTOMATIQUEMENT**

Pipeline :

```text
+CMTI
-> CMGR
-> ModemSms
-> RawSmsInput
-> SmsIngestionService
-> durable ?
-> CMGD exact
```

Il ne manipule pas directement les tables SQLite.

## 4. Frontière de non-perte

La première frontière est :

```text
SMS brut
-> inbound_sms
-> COMMIT
```

Pour un D1 valide, l'ingestion ajoute atomiquement :

```text
inbound_sms = QUEUED
+
mqtt_outbox = PENDING
```

Le receiver n'exécute `AT+CMGD=<index>` qu'après le retour durable de l'ingestion.

Une panne SQLite interdit donc la suppression modem.

## 5. CMGD et MQTT sont indépendants

```text
SMS
-> SQLite durable
-> CMGD
-> MQTT plus tard
```

CMGD n'attend pas PUBACK.

Une coupure Internet ne force donc pas le SIM800L à conserver indéfiniment un SMS déjà archivé localement.

## 6. Déduplication et crash avant CMGD

Scénario :

```text
SQLite COMMIT
-> crash
-> CMGD non exécuté
-> redémarrage
-> SMS relu
-> DUPLICATE_RAW
-> aucune seconde outbox
-> CMGD autorisé
```

Ce scénario est testé.

## 7. Startup recovery

Après initialisation modem :

```text
AT+CMGL="ALL"
```

récupère les SMS déjà stockés.

Ils passent par exactement le même `SmsReceiver`.

La gateway ne dépend donc pas seulement des notifications reçues en temps réel.

## 8. Déconnexion série

Une erreur pyserial devient `SerialTransportError`.

La reconnexion rejoue :

```text
AT
CPIN
CREG
CSQ
CMGF
CPMS
CNMI
CMGL
```

afin de ne pas supposer que les réglages du modem ont survécu.

## 9. Orchestrateur

`DjuaSmsGateway` coordonne :

- `Sim800Modem` ;
- `SmsReceiver` ;
- `MqttOutboxWorker`.

Il ne réimplémente pas leur logique métier.

La V1 GSM reste synchrone.

## 10. MQTT

Le transport MQTT reste :

```text
mqtt_outbox PENDING
-> publish exact topic/payload
-> QoS 1
-> mid
-> PUBACK
-> mark_outbox_published()
```

Garantie :

```text
at least once
```

et non exactly-once end-to-end.

## 11. Multi-device

Le même récepteur peut ingérer plusieurs :

```text
DJUA-KIN-000001
DJUA-KIN-000002
DJUA-KIN-000003
```

Le numéro expéditeur GSM reste distinct du `device_id` D1.

La liaison sender <-> device_id appartient à une future phase sécurité.

## 12. État de validation

```text
D1                    : TESTÉ AUTOMATIQUEMENT
SQLite                : TESTÉ AUTOMATIQUEMENT
MQTT logique          : TESTÉ AUTOMATIQUEMENT
GSM/AT simulé         : TESTÉ AUTOMATIQUEMENT
SIM800L réel          : NON TESTÉ
SMS réel              : NON TESTÉ
backend end-to-end    : NON TESTÉ DANS CETTE PHASE
```

Suite actuelle :

```text
177 PASS
0 FAIL
0 SKIP
```

## 13. Hors périmètre

Cette phase n'implémente pas :

- émetteur SMS ESP32 ;
- modification du firmware DJUA ;
- modification D1 ;
- HMAC ;
- service Windows ;
- Docker.
