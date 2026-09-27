# Stockage SQLite et MQTT outbox

## 1. Statut

**TESTÉ AUTOMATIQUEMENT**

Cette couche utilise uniquement la bibliothèque standard Python `sqlite3`.

Aucun ORM, Redis, PostgreSQL ou broker MQTT n'est nécessaire.

Le chemin de base est configurable via :

```python
Database(path)
```

Le futur déploiement pourra fournir par exemple :

```text
DATABASE_PATH=data/djua_sms_gateway.db
```

sans que cette phase ajoute une configuration réseau complète.

## 2. Version de schéma

Version actuelle :

```text
PRAGMA user_version = 1
```

`Database.initialize()` :

- crée les tables/index si nécessaires ;
- accepte la réouverture d'une base version 1 ;
- met une base version 0 à version 1 ;
- refuse une base dont la version est supérieure à celle connue.

Une future évolution devra ajouter explicitement une migration/version supplémentaire. Alembic n'est pas utilisé.

## 3. Table inbound_sms

Schéma logique implémenté :

```text
id INTEGER PRIMARY KEY
sender TEXT NOT NULL
modem_timestamp TEXT NULL
gateway_received_at TEXT NOT NULL
raw_body TEXT NOT NULL
raw_dedupe_key TEXT NOT NULL UNIQUE
logical_dedupe_key TEXT NULL UNIQUE
protocol_version TEXT NULL
device_id TEXT NULL
sequence INTEGER NULL
status TEXT NOT NULL
validation_status TEXT NULL
validation_warning TEXT NULL
validation_error TEXT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

Statuts autorisés :

```text
RECEIVED
INVALID
VALIDATED
QUEUED
PUBLISHED
FAILED
```

`raw_body` reste la source d'audit. Les valeurs électriques individuelles ne sont pas dupliquées dans cette table.

## 4. Table mqtt_outbox

```text
id INTEGER PRIMARY KEY
sms_id INTEGER NOT NULL UNIQUE
topic TEXT NOT NULL
payload_json TEXT NOT NULL
qos INTEGER NOT NULL
retain INTEGER NOT NULL
status TEXT NOT NULL
attempt_count INTEGER NOT NULL
next_attempt_at TEXT NULL
last_error TEXT NULL
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
published_at TEXT NULL
```

La relation :

```text
mqtt_outbox.sms_id -> inbound_sms.id
```

est protégée par une foreign key SQLite.

Statuts :

```text
PENDING
PUBLISHED
FAILED
```

Une outbox correspond à une publication MQTT future.

## 5. Déduplication brute

Fonction :

```text
compute_raw_dedupe_key()
```

Entrées :

```text
sender
modem_timestamp si disponible
raw_body exact
```

Le tout est sérialisé canoniquement puis hashé en SHA-256.

La contrainte UNIQUE est la garde finale.

## 6. Déduplication logique

Fonction :

```text
compute_logical_dedupe_key()
```

Elle utilise :

```text
device_id
sequence
rtc
uptime_ms
canonical_logical_message
```

Le message canonique contient les valeurs D1 déjà parsées et les flags, mais pas le texte `auth`. Les valeurs appartenant à un groupe déclaré invalide sont canonicalisées à `null`, car le normalizer les ignore également.

Ainsi, des représentations textuelles équivalentes restent idempotentes.

## 7. Transactions

### Stockage brut

`store_raw_sms()` effectue une transaction dédiée.

Succès :

```text
STORED
```

Relecture du même SMS :

```text
DUPLICATE
```

Dans les deux cas, `durably_stored = True` signifie qu'une copie SQLite existe après le retour de la méthode.

### Mise en file

`queue_valid_sms()` place dans une même transaction :

```text
inbound_sms.status = QUEUED
+
INSERT mqtt_outbox(status=PENDING)
```

Un échec outbox rollbacke l'ensemble.

## 8. Pipeline

`SmsIngestionService.ingest()` réalise :

```text
store brut
-> duplicate raw ?
-> parse
-> validate
-> invalid ?
-> normalize
-> duplicate logical ?
-> queue outbox
```

Résultats possibles :

```text
QUEUED
INVALID
DUPLICATE_RAW
DUPLICATE_LOGICAL
```

Aucune publication MQTT n'est effectuée.

## 9. Reprise

`list_pending_outbox()` retourne les publications encore `PENDING`, éventuellement filtrées par `next_attempt_at`.

Elles survivent à la fermeture/réouverture du processus car elles sont stockées dans le fichier SQLite.

## 10. API préparée pour la phase MQTT

`mark_outbox_published()` :

- marque l'outbox `PUBLISHED` ;
- définit `published_at` ;
- marque le SMS `PUBLISHED`.

`record_publish_failure()` :

- incrémente `attempt_count` ;
- conserve `last_error` ;
- conserve `next_attempt_at` ;
- ne supprime jamais le payload.

Ces méthodes sont testées sans broker. Leur utilisation après PUBACK réel appartient à la phase MQTT.

## 11. Tests

La suite couvre notamment :

- création/réouverture du schéma ;
- commit et rollback ;
- contraintes UNIQUE ;
- foreign keys ;
- UTF-8 et NULL SQL ;
- JSON outbox ;
- crash/relecture brute ;
- doublon logique ;
- reprise PENDING ;
- multi-device ;
- même séquence sur devices différents ;
- reboot/wrap ;
- `uint32 millis()` max ;
- solaire `null` vs `0.0`.

Aucune donnée de test ne contient de secret réel.
