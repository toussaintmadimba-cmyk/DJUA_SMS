# Architecture DJUA_SMS

> `toussaintmadimba-cmyk/DJUA` reste strictement **READ ONLY**.

## 1. Architecture cible

```text
CAPTEURS DJUA
    |
    v
ESP32 + modem GSM émetteur
    |
    v
SMS / réseau GSM
    |
    v
SIM868 récepteur
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
    +--> dispatch D1 / D2T / D2T2 / D2E
    +--> parsing / validation / sécurité
    +--> déduplication
    +--> normalisation backend
    |
    +--> mqtt_outbox PENDING --> MqttOutboxWorker --> MQTT QoS 1 --> broker
    |
    +--> http_outbox PENDING --> HttpOutboxWorker --> HTTP POST
                                              |
                                              v
                                         backend DJUA
```

La sortie backend est configurable :

```text
MQTT_ONLY
HTTP_ONLY
MQTT_AND_HTTP
```

Le boîtier terrain continue d'utiliser le SMS comme transport vers la gateway. Le choix MQTT/HTTP concerne uniquement la sortie de **DJUA_SMS vers le backend**.

## 2. DJUA comme référence

Le dépôt DJUA peut être lu pour comprendre le contrat historique, les noms de champs et les unités. Il n'est jamais modifié par ce projet.

## 3. Couche GSM

### serial_transport

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

Il ne connaît ni SMS, ni protocole métier, ni SQLite, ni MQTT/HTTP.

### at_protocol

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

Responsable de l'initialisation et des opérations haut niveau :

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

Le nom `Sim800Modem` est historique ; le récepteur matériel utilisé par le projet est un SIM868.

### sms_receiver

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

La première frontière reste :

```text
SMS brut
-> inbound_sms
-> COMMIT
```

Pour un SMS valide, l'ingestion réalise ensuite atomiquement :

```text
inbound_sms = QUEUED
+
outbox(es) activée(s) = PENDING
```

Selon `DELIVERY_MODE`, la même transaction crée :

```text
MQTT_ONLY      -> mqtt_outbox
HTTP_ONLY      -> http_outbox
MQTT_AND_HTTP  -> mqtt_outbox + http_outbox
```

Le receiver n'exécute `AT+CMGD=<index>` qu'après le retour durable de l'ingestion. Une panne SQLite interdit donc la suppression modem.

## 5. CMGD et sorties réseau sont indépendants

```text
SMS
-> SQLite durable
-> CMGD
-> livraison réseau plus tard
```

CMGD n'attend ni PUBACK MQTT ni réponse HTTP 2xx. Une coupure Internet ne force donc pas le SIM868 à conserver un SMS déjà archivé localement.

## 6. Déduplication et crash avant CMGD

```text
SQLite COMMIT
-> crash
-> CMGD non exécuté
-> redémarrage
-> SMS relu
-> DUPLICATE_RAW
-> aucune seconde paire d'outboxes
-> CMGD autorisé
```

La déduplication logique D2 repose sur `message_id` et le hash du contenu signé ; D1 conserve sa déduplication historique.

## 7. Startup recovery

Après initialisation modem :

```text
AT+CMGL="ALL"
```

récupère les SMS déjà stockés. Ils passent par le même `SmsReceiver`.

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
- `MqttOutboxWorker` lorsque MQTT est activé ;
- `HttpOutboxWorker` lorsque HTTP est activé.

L'orchestrateur ne réimplémente pas le parsing, la persistance ou les transports.

## 10. Sortie MQTT

```text
mqtt_outbox PENDING
-> publish exact topic/payload
-> QoS 1
-> mid
-> PUBACK
-> mqtt_outbox PUBLISHED
```

Garantie : **at least once**, pas exactly-once end-to-end.

## 11. Sortie HTTP

```text
http_outbox PENDING
-> POST exact payload_json
-> réponse HTTP
-> 2xx : http_outbox PUBLISHED
-> 408/425/429/5xx ou erreur réseau : retry
-> autre 4xx : FAILED terminal
```

Le retry utilise un backoff exponentiel plafonné. Le payload durable n'est pas recalculé pendant les retries.

En mode double, `inbound_sms` devient `PUBLISHED` seulement lorsque les deux outboxes existantes sont `PUBLISHED`.

## 12. Multi-device

Le même récepteur peut ingérer plusieurs devices. Le numéro expéditeur GSM reste distinct du `device_id`. Pour D2 en production, la liaison E.164 sender <-> device_id est vérifiée après le HMAC.

## 13. Schéma SQLite

Historique :

```text
v1 -> base D1 + mqtt_outbox
v2 -> métadonnées D2 :
      message_id
      d2_content_hash
      auth_status
      security_status
      conflict_with_sms_id

v3 -> ajout de http_outbox
```

La migration v2 -> v3 est additive et ne modifie pas les lignes MQTT existantes.

## 14. Extension D2

```text
D1   -> parser/validator/normalizer historique
D2T  -> codec D2 legacy -> HMAC/binding -> telemetry
D2T2 -> codec compact -> HMAC/binding -> telemetry + dc_load
D2E  -> codec D2 -> HMAC/binding -> geofence/events
```

D2T et D2T2 utilisent le canal télémétrie MQTT lorsqu'il est activé. D2E utilise le canal événement MQTT. Pour HTTP, la télémétrie utilise `HTTP_BACKEND_URL` et D2E peut utiliser `HTTP_EVENT_URL`.

`gateway_received_at` est l'heure UTC de la première ingestion locale durable et reste figée dans le payload pendant les retries.

## 15. État de validation

État déjà observé sur le poste physique avant l'ajout HTTP :

```text
SIM868 réel                          : VALIDÉ
vrai SMS D2T2                       : VALIDÉ
SMS -> SQLite -> MQTT PUBACK         : VALIDÉ
MQTT -> API FastAPI -> D2T2/DC LOAD : VALIDÉ en environnement de test
```

L'authentification du test D2T2 était en mode développement. Le backend FastAPI de test stocke en mémoire.

Pour la nouvelle sortie HTTP :

```text
configuration / outbox / retries / mode double : couverts par tests automatisés ajoutés
POST HTTP matériel/réseau réel                 : à valider séparément
```

Le résultat exact de la suite doit toujours être pris dans le dernier run CI ; aucun compteur statique n'est une preuve permanente.
