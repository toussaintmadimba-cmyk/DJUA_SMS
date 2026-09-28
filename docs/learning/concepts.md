# Concepts structurants — DJUA_SMS

Ce document décrit uniquement des concepts réellement présents dans DJUA_SMS. Il ne constitue pas une encyclopédie générale.

## Séparation des responsabilités

**Rencontré dans :**

```text
gsm/
protocol/
storage/
mqtt/
services/
```

**Pourquoi il existe ici :**

Le projet sépare le dialogue avec le modem, le protocole D1, la base SQLite, MQTT et l'orchestration. Cela évite qu'un même fichier sache tout faire.

**À retenir :**

Lorsqu'un problème apparaît, commencer par identifier la couche concernée.

**Exemple DJUA_SMS :**

`gsm/sms_receiver.py` ne parse pas D1. Il remet le SMS à `SmsIngestionService`, qui lui-même s'appuie sur les modules `protocol/` et `storage/`.

---

## Port série et pyserial

**Rencontré dans :**

`gsm/serial_transport.py`

**Pourquoi il existe ici :**

Le SIM800L est accessible depuis le poste récepteur par un port série. `pyserial==3.5` fournit l'accès portable au port.

**À retenir :**

Cette couche transporte des lignes entre Python et le modem. Elle ne connaît pas le sens métier du SMS.

**Exemple DJUA_SMS :**

`PySerialTransport.write_line("AT")` ajoute le retour chariot et écrit sur le port configuré.

---

## Commande AT

**Rencontré dans :**

`gsm/at_protocol.py`, `gsm/modem.py`

**Pourquoi il existe ici :**

Le SIM800L se contrôle avec des commandes textuelles comme :

```text
AT
AT+CPIN?
AT+CREG?
AT+CSQ
AT+CMGR=7
AT+CMGD=7
```

**À retenir :**

Une commande produit des lignes de réponse puis normalement `OK`, `ERROR` ou une erreur spécialisée.

**Exemple DJUA_SMS :**

`Sim800Modem.read_sms()` utilise `AT+CMGR=<index>` pour obtenir le sender, le timestamp modem et le body.

---

## URC

**Rencontré dans :**

`gsm/at_protocol.py`

**Pourquoi il existe ici :**

Le modem peut parler spontanément sans attendre une commande. Ces messages sont des URC.

**À retenir :**

Une URC ne doit pas être confondue avec la réponse à la commande AT en cours.

**Exemple DJUA_SMS :**

`+CMTI: "SM",4` peut arriver pendant `AT+CSQ`. `AtProtocol` la met alors dans une petite file interne.

---

## CMTI, CMGR, CMGL et CMGD

**Rencontré dans :**

`gsm/modem.py`, `gsm/sms_receiver.py`

**Pourquoi ils existent ici :**

Ils structurent le cycle de vie d'un SMS dans le modem.

**À retenir :**

```text
+CMTI  -> indique qu'un SMS existe
CMGR   -> lit un SMS précis
CMGL   -> liste les SMS déjà stockés
CMGD   -> supprime un SMS précis
```

**Exemple DJUA_SMS :**

Au démarrage, `CMGL="ALL"` permet de récupérer des SMS arrivés lorsque la gateway était arrêtée.

---

## Persistance durable

**Rencontré dans :**

`storage/database.py`, `storage/repository.py`, `gsm/sms_receiver.py`

**Pourquoi elle existe ici :**

Le modem ne doit pas être la seule copie d'un SMS important.

**À retenir :**

La règle centrale est :

```text
CMGR
→ SQLite COMMIT
→ CMGD autorisé
```

**Exemple DJUA_SMS :**

Si `SmsIngestionService.ingest()` échoue avant confirmation durable, `SmsReceiver` n'appelle pas la suppression du SMS.

---

## Transaction SQLite

**Rencontré dans :**

`storage/database.py`

**Pourquoi elle existe ici :**

Une transaction regroupe des écritures qui doivent réussir ensemble ou être annulées ensemble.

**À retenir :**

`commit` rend les changements durables. Une exception provoque un `rollback`.

**Exemple DJUA_SMS :**

Pour une télémétrie valide, le passage de `inbound_sms` à `QUEUED` et la création de `mqtt_outbox` se font dans la même transaction.

---

## Modèle inbound_sms

**Rencontré dans :**

`storage/database.py`, `storage/models.py`

**Pourquoi il existe ici :**

Cette table conserve la preuve de ce qui a été reçu par SMS.

**À retenir :**

Elle contient notamment :

```text
sender
modem_timestamp
raw_body
raw_dedupe_key
logical_dedupe_key
device_id
sequence
status
validation_error
```

**Exemple DJUA_SMS :**

Même un SMS invalide comme un texte non D1 peut rester archivé avec le statut `INVALID`.

---

## Parsing D1

**Rencontré dans :**

`protocol/parser.py`

**Pourquoi il existe ici :**

Le SMS D1 est une ligne compacte à 23 champs positionnels. Le parser transforme cette chaîne en `SmsTelemetry`.

**À retenir :**

Parser signifie ici transformer la représentation texte en données structurées, pas encore décider si toutes les données sont acceptables métier.

**Exemple DJUA_SMS :**

La séquence et l'uptime sont décodés en base36, les flags sont décodés depuis l'hexadécimal.

---

## Validation D1

**Rencontré dans :**

`protocol/validator.py`

**Pourquoi elle existe ici :**

Une chaîne peut être syntaxiquement parsable tout en étant incohérente.

**À retenir :**

Le validator contrôle notamment :

- version D1 ;
- forme du `device_id` ;
- flags ;
- plage de `millis()` ;
- date RTC ;
- latitude/longitude ;
- cohérence entre flags de validité et valeurs présentes.

**Exemple DJUA_SMS :**

Un groupe marqué `solar_valid = true` doit contenir les valeurs solaires attendues.

---

## Normalisation

**Rencontré dans :**

`protocol/normalizer.py`

**Pourquoi elle existe ici :**

Le format compact du SMS n'est pas le format attendu par le backend MQTT.

**À retenir :**

La normalisation transforme une télémétrie D1 validée vers `DjuaMqttPayload`.

**Exemple DJUA_SMS :**

Solaire invalide devient des valeurs JSON `null`, tandis qu'un solaire valide à zéro reste `0.0`.

---

## Déduplication brute

**Rencontré dans :**

`storage/repository.py`

**Pourquoi elle existe ici :**

Un SMS peut être relu du modem après un crash survenu avant CMGD.

**À retenir :**

La clé brute dépend du sender, du timestamp modem s'il existe et du body exact, puis est hashée en SHA-256.

**Exemple DJUA_SMS :**

Un SMS déjà persisté puis relu produit `DUPLICATE_RAW` et ne crée pas une deuxième outbox.

---

## Déduplication logique et idempotence

**Rencontré dans :**

`storage/repository.py`

**Pourquoi elle existe ici :**

Deux SMS textuellement différents peuvent représenter la même télémétrie logique.

**À retenir :**

L'idempotence signifie qu'une répétition du même événement logique ne doit pas multiplier son effet.

**Exemple DJUA_SMS :**

La clé logique tient compte du `device_id`, de la séquence, du RTC, de l'uptime et d'une représentation D1 canonique.

---

## Outbox pattern

**Rencontré dans :**

`mqtt_outbox`, `storage/repository.py`, `services/outbox_worker.py`

**Pourquoi il existe ici :**

Réception SMS et disponibilité MQTT ne se produisent pas forcément au même moment.

**À retenir :**

La gateway enregistre d'abord ce qui devra être publié. MQTT peut échouer sans perdre la télémétrie.

**Exemple DJUA_SMS :**

Une ligne `mqtt_outbox.status = PENDING` reste en SQLite jusqu'à une publication confirmée.

---

## MQTT

**Rencontré dans :**

`mqtt/client.py`, `mqtt/publisher.py`, `services/outbox_worker.py`

**Pourquoi il existe ici :**

MQTT est le transport entre DJUA_SMS et le système backend externe.

**À retenir :**

La gateway publie un `topic` et un JSON, par exemple :

```text
djua/test/<device_id>/telemetry
```

**Exemple DJUA_SMS :**

`MqttOutboxWorker` récupère les lignes PENDING et les remet à `MqttPublisher`.

---

## QoS 1 et PUBACK

**Rencontré dans :**

`mqtt/publisher.py`

**Pourquoi ils existent ici :**

Avec QoS 1, la gateway attend une confirmation du broker.

**À retenir :**

Le retour de `publish()` ne suffit pas. Le callback PUBACK portant un `mid` doit être associé à la bonne outbox.

**Exemple DJUA_SMS :**

Le publisher maintient un mapping `mid → outbox_id`, puis appelle `mark_outbox_published()`.

---

## Retry et backoff

**Rencontré dans :**

`mqtt/publisher.py`, `services/outbox_worker.py`, `storage/repository.py`

**Pourquoi ils existent ici :**

Le broker peut être indisponible temporairement.

**À retenir :**

Une erreur n'entraîne pas la suppression de l'outbox. Une prochaine tentative est planifiée.

**Exemple DJUA_SMS :**

Le délai utilise un backoff exponentiel plafonné basé sur `attempt_count`.

---

## At-least-once

**Rencontré dans :**

le comportement de récupération MQTT et `tests/integration/test_mqtt_recovery.py`

**Pourquoi il existe ici :**

Une confirmation réseau et un commit local ne sont pas une seule opération atomique.

**À retenir :**

Le système préfère parfois republier un message plutôt que risquer de le perdre.

**Exemple DJUA_SMS :**

Si le broker envoie PUBACK puis que l'application plante avant le commit `PUBLISHED`, l'outbox reste PENDING et peut être republiée.

---

## Injection de dépendances et fakes

**Rencontré dans :**

`SerialTransportProtocol`, `MqttClientProtocol`, `tests/unit/gsm/fakes.py`, `tests/unit/mqtt/fakes.py`

**Pourquoi ils existent ici :**

Le code doit être testable sans modem physique et sans broker réel.

**À retenir :**

Le composant reçoit une interface compatible plutôt que de créer toujours lui-même le matériel/réseau réel.

**Exemple DJUA_SMS :**

Les tests donnent un `ScriptedTransport` à `AtProtocol` pour simuler les réponses du SIM800L.

---

## Configuration par environnement

**Rencontré dans :**

`config.py`, `.env.example`

**Pourquoi elle existe ici :**

Le port série, le broker, les délais et les credentials changent selon la machine.

**À retenir :**

Le code lit `os.environ`. Le fichier `.env.example` documente les noms mais n'est pas chargé automatiquement.

**Exemple DJUA_SMS :**

`SERIAL_PORT`, `MQTT_HOST`, `MQTT_QOS`, `MQTT_TLS`.

---

## Tests unitaires, intégration et CI

**Rencontré dans :**

`tests/unit/`, `tests/integration/`, `.github/workflows/tests.yml`

**Pourquoi ils existent ici :**

Le projet doit vérifier séparément les composants et les flux complets simulés.

**À retenir :**

Un test avec FakeSerial valide la logique logicielle, pas le matériel SIM800L réel.

**Exemple DJUA_SMS :**

Le CI sur Python 3.11 installe `paho-mqtt==2.1.0` et `pyserial==3.5`, compile puis exécute actuellement 177 tests.

---

## Authentification D1 actuelle

**Rencontré dans :**

`protocol/models.py`, `protocol/validator.py`

**Pourquoi elle existe ici :**

D1 réserve un champ `auth`, mais la sécurité complète n'est pas encore implémentée.

**À retenir :**

La gateway peut vérifier la forme du token, mais son statut reste :

```text
AUTH_NOT_VERIFIED
```

Il ne faut pas confondre validation syntaxique et authentification.

**Exemple DJUA_SMS :**

Un token de 11 caractères base64url peut être accepté en forme tout en générant l'avertissement `AUTH_NOT_VERIFIED`.

---

## TLS et credentials MQTT

**Rencontré dans :**

`config.py`, `mqtt/client.py`

**Pourquoi ils existent ici :**

Un broker peut demander une authentification et une connexion chiffrée.

**À retenir :**

Username/password et TLS sont optionnels et proviennent de l'environnement.

**Exemple DJUA_SMS :**

`MQTT_TLS=true` déclenche `tls_set()` dans le client Paho.

---

## Recovery

**Rencontré dans :**

`services/gateway.py`, `gsm/sms_receiver.py`, `services/outbox_worker.py`

**Pourquoi il existe ici :**

Le poste peut redémarrer alors que des SMS ou publications attendent encore.

**À retenir :**

Il existe deux récupérations principales :

```text
modem : CMGL -> SMS stockés -> ingestion
SQLite : mqtt_outbox PENDING -> nouvelle publication
```

**Exemple DJUA_SMS :**

`DjuaSmsGateway.startup()` récupère les SMS modem stockés avant de poursuivre la boucle normale.
