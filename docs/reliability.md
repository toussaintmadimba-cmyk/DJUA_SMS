# Fiabilité, non-perte et reprise

> `toussaintmadimba-cmyk/DJUA` est **READ ONLY**. Cette documentation décrit uniquement DJUA_SMS.

## 1. Garantie locale visée

Principe :

```text
un SMS déjà commit dans SQLite
ne dépend plus de la disponibilité d'Internet ou MQTT
pour être conservé
```

La persistance, la reprise et la chaîne GSM simulée sont maintenant **TESTÉES AUTOMATIQUEMENT**. Le SIM868 physique et le SMS réel restent non validés.

## 2. Ordre de non-perte

L'ordre obligatoire reste :

```text
lecture future depuis modem
-> store_raw_sms()
-> COMMIT SQLite
-> seulement ensuite suppression modem autorisable
```

La partie `store_raw_sms() -> COMMIT -> autorisation CMGD` est implémentée et testée avec modem simulé. L'exécution de CMGD sur un SIM868 physique reste **À VALIDER AVEC SIM800L RÉEL**.

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

La représentation canonique utilise les valeurs déjà parsées, exclut le texte `auth` et remplace par `null` les valeurs appartenant à un groupe déclaré invalide par ses flags. Ainsi, deux encodages différents d'une donnée volontairement ignorée par le normalizer restent la même télémétrie logique.

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

**TESTÉ AUTOMATIQUEMENT, y compris jusqu'au transport MQTT simulé**

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

Le transport MQTT utilise maintenant un backoff exponentiel simple `base * 2^attempt_count`, plafonné par une valeur configurable.

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

**TESTÉ AUTOMATIQUEMENT avec transport série simulé** :

- `AT+CNMI` ;
- `+CMTI` ;
- `AT+CMGR` ;
- `AT+CMGL` ;
- `AT+CMGD=<index>` ;
- disparition/reconnexion série ;
- reconfiguration modem ;
- persistance avant suppression.

**NON VALIDÉ MATÉRIELLEMENT** :

- mémoire réelle du SIM800L ;
- port COM réel ;
- vrai SMS ;
- comportement CNMI réel ;
- SMS concaténés ;
- broker réel dans cet environnement ;
- PUBACK réel ;
- exactly-once end-to-end.


## 15. PUBACK et persistance

**TESTÉ AUTOMATIQUEMENT**

Le mapping en mémoire est :

```text
mid -> outbox_id
```

Un PUBACK ne modifie que l'outbox associée à ce `mid`. Deux ACK reçus dans un ordre différent sont correctement associés.

Le code protège également le cas où le callback `on_publish` arrive avant que le thread appelant ait terminé d'enregistrer le `mid`.

## 16. Déconnexion et reconnexion

Une coupure MQTT ne modifie pas le statut durable du message : tant qu'aucun PUBACK n'a été confirmé en SQLite, la ligne reste `PENDING`.

Les lignes dues sont retrouvées après reconnexion ou redémarrage par `list_pending_outbox()`.

## 17. Retry

Les champs existants sont utilisés :

```text
attempt_count
last_error
next_attempt_at
```

Le calcul est exponentiel et plafonné. Aucun payload n'est supprimé sur échec.

## 18. Crash autour du PUBACK

### Avant PUBACK

Après redémarrage, la ligne reste `PENDING` et est republiable.

### Après PUBACK mais avant commit SQLite

Une republication est possible. C'est une conséquence assumée de la garantie **at least once**. DJUA_SMS ne prétend pas offrir exactly-once end-to-end.

## 19. Validation réseau restante

Le comportement logique du client, du worker et des callbacks est testé avec doubles MQTT. Le test contre un broker réel est séparé dans `scripts/mqtt_test.py` et dépend de l'environnement d'exécution.


## 20. Contrat de suppression GSM

**TESTÉ AUTOMATIQUEMENT**

```text
CMGR
-> ingestion
-> SQLite durable
-> CMGD autorisé
```

Si SQLite échoue, CMGD n'est jamais appelé.

Un SMS invalide peut être supprimé après archivage durable de son `raw_body`.

Un `DUPLICATE_RAW` peut également être supprimé puisque sa copie existe déjà durablement.

## 21. Crash avant CMGD

Le test intégré couvre :

```text
CMGR
-> SQLite COMMIT
-> échec/crash avant CMGD
-> relecture même SMS
-> DUPLICATE_RAW
-> une seule outbox
-> CMGD réussi au second passage
```

## 22. Perte du port série

Une perte du port pendant CMGR remonte à l'orchestrateur sans suppression.

Une perte pendant CMGD intervient après persistance ; la base reste donc la source durable.

Après reconnexion :

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

sont rejoués.

## 23. MQTT indisponible

Le SMS modem peut être supprimé lorsque SQLite a durablement créé l'outbox, même si MQTT est hors ligne.

```text
SQLite durable
-> CMGD
-> mqtt_outbox PENDING
-> retry MQTT plus tard
```

## 24. Tests

État actuel :

```text
208 tests
208 PASS
0 FAIL
0 SKIP
```

Le CI installe `pyserial==3.5` et `paho-mqtt==2.1.0`, compile les sources puis exécute toute la suite.

## 25. Fiabilité D2

D2 conserve la frontière `CMGR -> SQLite durable -> CMGD précis`.

Un rejet HMAC, un sender/device incohérent ou un conflit de message_id reste archivé sans outbox backend. Après persistance locale durable, le SMS peut être supprimé précisément du modem.

Déduplication D2 :

```text
même message_id + même signed_part
-> DUPLICATE_LOGICAL
-> pas de seconde outbox

même message_id + signed_part différent
-> MESSAGE_ID_CONFLICT
-> conflit archivé
-> pas de seconde outbox
```

Le `d2_content_hash` n'est utilisé comme identité fiable qu'après validation de sécurité ; un message non authentifié ne peut donc pas réserver à lui seul un message_id.

La migration SQLite v1 -> v2 est testée avec une ligne D1 et une outbox préexistantes, qui restent intactes.

`gateway_received_at` est conservé dans le JSON durable de l'outbox. Les retries MQTT republient exactement le même payload.

Le récepteur matériel confirmé est SIM868. La réception D2T/D2E, SQLite, CMGD et publication MQTT sont testés automatiquement avec des doubles modem/MQTT, pas avec un nouveau vrai SMS D2.
