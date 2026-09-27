# Fiabilité, non-perte et reprise

> `toussaintmadimba-cmyk/DJUA` est **READ ONLY**. Cette documentation décrit uniquement DJUA_SMS.

## 1. Garantie locale visée

Principe :

```text
un SMS déjà commit dans SQLite
ne dépend plus de la disponibilité d'Internet ou MQTT
pour être conservé
```

La persistance et la reprise sont maintenant **TESTÉES AUTOMATIQUEMENT** sans SIM800L et sans broker.

## 2. Ordre de non-perte

L'ordre obligatoire reste :

```text
lecture future depuis modem
-> store_raw_sms()
-> COMMIT SQLite
-> seulement ensuite suppression modem autorisable
```

La partie `store_raw_sms() -> COMMIT` est implémentée.

La suppression SIM800L reste **À VALIDER AVEC SIM800L RÉEL**.

## 3. Déduplication brute

**TESTÉ AUTOMATIQUEMENT**

`raw_dedupe_key` est un SHA-256 déterministe d'une sérialisation JSON canonique contenant :

```text
version = raw-v1
sender
modem_timestamp ou chaîne vide
raw_body exact
```

La clé ne dépend pas d'un index mémoire SIM.

Si `modem_timestamp` est absent, un replay exact `sender + raw_body` reste dédupliqué.

La contrainte SQLite :

```text
UNIQUE(raw_dedupe_key)
```

est la garde finale contre les courses.

Un doublon brut retourne le SMS déjà existant et ne crée ni seconde ligne `inbound_sms`, ni seconde outbox.

## 4. Déduplication logique

**TESTÉ AUTOMATIQUEMENT**

Après parsing/validation, la clé logique est un SHA-256 portant notamment sur :

```text
device_id
sequence
rtc
uptime_ms
représentation sémantique D1 canonique
```

La représentation canonique utilise les valeurs déjà parsées et exclut le texte `auth`.

Conséquences testées :

- `12.40` et `12.400` donnent la même identité sémantique ;
- le même message avec `auth=-` ou un tag de forme correcte ne crée pas deux publications ;
- la même séquence sur deux `device_id` reste distincte ;
- une séquence réutilisée après reboot/wrap reste distincte si RTC/uptime/contenu changent.

La contrainte SQLite :

```text
UNIQUE(logical_dedupe_key)
```

empêche une seconde télémétrie logique d'obtenir une seconde outbox.

Le deuxième SMS brut reste conservé pour audit, marqué `VALIDATED` avec un avertissement `DUPLICATE_LOGICAL:<id>`.

## 5. Transactions

Deux frontières existent volontairement.

### Transaction A — conservation brute

```text
INSERT inbound_sms(RECEIVED)
COMMIT
```

Elle a lieu avant parsing.

Un SMS invalide reste donc conservé.

### Transaction B — mise en file atomique

Pour un SMS valide :

```text
UPDATE inbound_sms -> QUEUED
+
INSERT mqtt_outbox -> PENDING
COMMIT
```

Les deux opérations sont atomiques.

Un test force une violation de contrainte outbox : l'état `QUEUED` est alors rollbacké et aucune outbox partielle n'existe.

## 6. SMS invalides

**TESTÉ AUTOMATIQUEMENT**

Une erreur de parsing ou un `INVALID_FORMAT` produit :

```text
inbound_sms.status = INVALID
raw_body conservé
validation_error conservée
aucune mqtt_outbox
```

L'invalidité ne supprime pas la preuve brute.

## 7. MQTT outbox

**TESTÉ AUTOMATIQUEMENT sans réseau**

Chaque publication future contient :

```text
sms_id
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

Valeurs par défaut actuelles du pipeline :

```text
qos = 1
retain = false
status = PENDING
```

`payload_json` est sérialisé de manière déterministe avec `sort_keys=True`, sans ajout de `protocol`, `sequence`, `flags` ou `auth`.

## 8. Reprise

**TESTÉ AUTOMATIQUEMENT**

Après fermeture/réouverture de la base :

```text
list_pending_outbox()
```

retrouve les publications `PENDING` et leur `payload_json` identique.

Le test end-to-end simulé couvre :

```text
raw D1
-> SQLite
-> parse
-> validate
-> normalize
-> outbox
-> nouvelle instance repository
-> reload pending
```

sans réseau.

## 9. Crash avant suppression modem

**TESTÉ AUTOMATIQUEMENT côté logiciel**

Simulation :

```text
SMS stocké
-> processus supposé mort avant suppression modem
-> même SMS réinjecté
```

Résultat :

```text
1 inbound_sms
1 mqtt_outbox
DUPLICATE_RAW au second passage
```

La suppression réelle du modem n'est pas encore testée.

## 10. Crash après création outbox

**TESTÉ AUTOMATIQUEMENT**

Une outbox `PENDING` reste présente après réouverture du fichier SQLite.

Aucune purge automatique n'est effectuée.

## 11. Publication future

L'API `mark_outbox_published()` effectue dans une transaction :

```text
mqtt_outbox.status = PUBLISHED
published_at = ...
inbound_sms.status = PUBLISHED
```

L'API `record_publish_failure()` :

```text
attempt_count += 1
last_error = ...
next_attempt_at = ...
```

et conserve toujours `payload_json`.

Un échec temporaire laisse l'outbox `PENDING`.

Un échec explicitement terminal peut passer à `FAILED`, sans suppression de la ligne.

Aucune stratégie de backoff numérique n'est encore imposée.

## 12. Horodatage

Les temps gateway :

- `gateway_received_at`
- `created_at`
- `updated_at`
- `published_at`

sont séparés des temps boîtier :

- `timestamp`
- `timestamp_ms`.

La gateway ne remplace jamais l'horodatage DJUA avec son heure locale de traitement.

## 13. Cas contractuels protégés

**TESTÉ AUTOMATIQUEMENT**

- solaire invalide -> JSON `null` ;
- solaire valide à zéro -> JSON `0.0` ;
- trois devices -> trois topics et identités distinctes ;
- même séquence sur devices différents -> aucune collision ;
- `timestamp_ms = 4294967295` -> stocké sans correction du wrap.

## 14. Limites

Non validé dans cette phase :

- mémoire réelle du SIM800L ;
- `AT+CNMI`, `+CMTI`, `AT+CMGR`, `AT+CMGD` ;
- disparition/reconnexion du port série ;
- broker réel ;
- PUBACK réel ;
- exactly-once end-to-end.

La garantie actuelle est une garantie de **persistance locale et d'idempotence de la gateway simulée**, pas une validation matérielle ou réseau.
