# AGENTS.md

## Périmètre

DJUA_SMS est une passerelle légère :

```text
SIM800L/SMS
-> persistance
-> validation D1
-> outbox
-> MQTT
```

Elle n'est pas le backend DJUA, une IA ou un moteur de maintenance prédictive.

## Protection absolue de DJUA

```text
toussaintmadimba-cmyk/DJUA
= READ ONLY
```

Interdiction de créer, modifier, supprimer, déplacer, committer, pousser ou ouvrir une PR contenant des modifications dans DJUA.

DJUA peut uniquement être lu comme source de référence.

Toute écriture de ce projet vise :

```text
toussaintmadimba-cmyk/DJUA_SMS
```

Si une évolution du firmware DJUA semble nécessaire, la documenter mais ne pas l'implémenter.

## Règle de preuve

Toujours distinguer :

- **CONFIRMÉ PAR DJUA**
- **CHOIX D'ARCHITECTURE DJUA_SMS**
- **TESTÉ AUTOMATIQUEMENT**
- **À VALIDER AVEC SIM800L RÉEL**
- **À VALIDER AVEC SMS RÉEL**
- **À VALIDER END-TO-END**

Ne jamais appeler un mock ou un FakeSerial un test matériel.

## Non-perte SMS

Règle obligatoire :

```text
CMGR
-> SmsIngestionService
-> SQLite COMMIT durable
-> CMGD=<index> autorisé
```

Si l'ingestion échoue :

```text
CMGD INTERDIT
```

Un SMS `INVALID` ou `DUPLICATE_RAW` peut être supprimé du modem si sa copie brute est déjà durable en SQLite.

Ne jamais utiliser `AT+CMGD=1,4` dans le fonctionnement normal.

## Séparation des responsabilités

- `gsm/serial_transport.py` : octets / port série ;
- `gsm/at_protocol.py` : commandes AT, terminaux, URC ;
- `gsm/modem.py` : opérations SIM800L ;
- `gsm/sms_receiver.py` : CMGR -> ingestion -> CMGD ;
- `services/ingestion.py` : persistance / D1 / outbox ;
- `mqtt/` : transport broker ;
- `services/gateway.py` : orchestration.

Ne pas déplacer la logique D1 dans les couches GSM.

## État stable actuel

**TESTÉ AUTOMATIQUEMENT**

Sont implémentés :

- D1 parser / validator / normalizer ;
- SQLite ;
- déduplication ;
- outbox ;
- MQTT QoS 1 / PUBACK / retry ;
- pyserial ;
- protocole AT ;
- initialisation SIM800L ;
- CMTI / CMGR / CMGL / CMGD ;
- persistance avant suppression ;
- startup recovery ;
- reconnexion série ;
- gateway orchestrator.

Suite actuelle :

```text
177 PASS
0 FAIL
0 SKIP
```

## Matériel

À ce stade :

```text
SIM800L RÉEL : NON VALIDÉ
SMS RÉEL     : NON VALIDÉ
```

Ne pas inventer le résultat des scripts matériels.

## Arrêt de phase

Ne pas commencer automatiquement :

- modification du firmware DJUA ;
- émetteur SMS ESP32 ;
- modification du protocole D1 ;
- HMAC ;
- service Windows ;
- Docker.

Attendre une autorisation explicite.
