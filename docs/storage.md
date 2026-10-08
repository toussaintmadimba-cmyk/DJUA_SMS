# Stockage SQLite et outboxes de livraison

## 1. Statut

DJUA_SMS utilise la bibliothèque standard Python `sqlite3`.

Le chemin de base reste configurable :

```text
DATABASE_PATH=data/djua_sms_gateway.db
```

SQLite conserve le SMS brut, les métadonnées de validation/déduplication et les livraisons réseau encore à effectuer.

## 2. Version de schéma

Version actuelle :

```text
PRAGMA user_version = 3
```

Historique :

```text
v1 -> inbound_sms + mqtt_outbox
v2 -> métadonnées D2 ajoutées à inbound_sms
v3 -> http_outbox
```

`Database.initialize()` :

- crée le schéma complet pour une base neuve ;
- migre v1 -> v2 -> v3 ;
- migre v2 -> v3 ;
- préserve les lignes existantes ;
- refuse une base plus récente que la version supportée.

Alembic n'est pas utilisé.

## 3. Table inbound_sms

Champs principaux :

```text
id
sender
modem_timestamp
gateway_received_at
raw_body
raw_dedupe_key
logical_dedupe_key
protocol_version
device_id
sequence
message_id
d2_content_hash
auth_status
security_status
conflict_with_sms_id
status
validation_status
validation_warning
validation_error
created_at
updated_at
```

Statuts :

```text
RECEIVED
INVALID
VALIDATED
QUEUED
PUBLISHED
FAILED
```

`raw_body` reste la preuve d'audit du SMS reçu.

## 4. Table mqtt_outbox

```text
id
sms_id UNIQUE
topic
payload_json
qos
retain
status
attempt_count
next_attempt_at
last_error
created_at
updated_at
published_at
```

Relation :

```text
mqtt_outbox.sms_id -> inbound_sms.id
```

Statuts :

```text
PENDING
PUBLISHED
FAILED
```

## 5. Table http_outbox

```text
id
sms_id UNIQUE
url
payload_json
status
attempt_count
next_attempt_at
last_error
created_at
updated_at
published_at
```

Relation :

```text
http_outbox.sms_id -> inbound_sms.id
```

La table ne contient pas de secret HTTP. Les éventuelles clés API restent dans la configuration locale.

## 6. Création atomique des sorties

Après validation et normalisation, la transaction de mise en file dépend de `DELIVERY_MODE`.

```text
MQTT_ONLY

UPDATE inbound_sms -> QUEUED
INSERT mqtt_outbox -> PENDING
COMMIT
```

```text
HTTP_ONLY

UPDATE inbound_sms -> QUEUED
INSERT http_outbox -> PENDING
COMMIT
```

```text
MQTT_AND_HTTP

UPDATE inbound_sms -> QUEUED
INSERT mqtt_outbox -> PENDING
INSERT http_outbox -> PENDING
COMMIT
```

Si l'une des insertions échoue, la transaction entière est rollbackée.

Cette frontière permet à `SmsReceiver` de supprimer ensuite le SMS du modem sans dépendre de la disponibilité immédiate du broker ou de l'API HTTP.

## 7. Même payload backend

Lorsque les deux sorties sont activées :

```text
mqtt_outbox.payload_json
==
http_outbox.payload_json
```

La gateway ne construit pas deux contrats métier différents.

MQTT ajoute seulement son topic/QoS/retain. HTTP ajoute seulement l'URL et les en-têtes de transport.

## 8. Déduplication

### Brute

`compute_raw_dedupe_key()` utilise une représentation déterministe de :

```text
sender
modem_timestamp si disponible
raw_body exact
```

### D1 logique

`compute_logical_dedupe_key()` protège la télémétrie D1 normalisée contre une seconde mise en file.

### D2 / D2T2 / D2E

`message_id = D2:<device_id>:<sequence_base36>` et `d2_content_hash` distinguent replay légitime et conflit.

Un doublon logique ne crée pas de seconde outbox, quel que soit le mode de livraison.

## 9. Reprise

Les méthodes :

```text
list_pending_outbox()
list_pending_http_outbox()
```

retrouvent les livraisons `PENDING` après redémarrage.

Les retries conservent le même `payload_json`.

## 10. Statut global du SMS

Le statut `inbound_sms` reflète toutes les sorties réellement créées pour ce SMS :

```text
au moins une sortie FAILED
-> inbound_sms = FAILED

toutes les sorties existantes PUBLISHED
-> inbound_sms = PUBLISHED

sinon
-> inbound_sms = QUEUED
```

Ainsi, en `MQTT_AND_HTTP`, un PUBACK MQTT seul ne suffit pas à marquer le SMS `PUBLISHED`.

## 11. Échecs et retries

MQTT et HTTP possèdent leurs propres :

```text
attempt_count
next_attempt_at
last_error
```

Un échec temporaire laisse la ligne `PENDING`.

Un échec terminal conserve la ligne en `FAILED`; aucune preuve durable n'est supprimée.

## 12. Tests à protéger

La suite doit couvrir au minimum :

- création et réouverture du schéma v3 ;
- migration v1 -> v3 ;
- migration v2 -> v3 ;
- préservation des lignes MQTT existantes ;
- rollback atomique ;
- déduplication ;
- reprise des outboxes PENDING ;
- HTTP_ONLY ;
- MQTT_AND_HTTP ;
- même payload sur les deux sorties ;
- statut global `QUEUED/PUBLISHED/FAILED`.
