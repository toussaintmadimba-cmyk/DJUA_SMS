# DJUA_SMS

Passerelle **SMS -> MQTT** du projet DJUA.

## Architecture cible

```text
BOÎTIER DJUA
    |
    v
SMS
    |
    v
DJUA_SMS
    |
    +--> persistance SQLite
    +--> déduplication
    +--> parsing / validation
    +--> normalisation
    +--> MQTT outbox persistante
    |
    v
MQTT
    |
    v
BACKEND DJUA
```

Le SMS est le transport cible du boîtier terrain. Il n'est pas conçu comme un fallback Wi-Fi.

## Règle absolue

Le dépôt `toussaintmadimba-cmyk/DJUA` est **READ ONLY** pour ce projet.

Toutes les conceptions, documentations, simulations, tests et implémentations de la gateway restent dans :

```text
toussaintmadimba-cmyk/DJUA_SMS
```

## Documentation

- [Règles du projet et garde-fous](AGENTS.md)
- [Architecture complète](docs/architecture.md)
- [Protocole SMS D1](docs/sms_protocol.md)
- [Contrat MQTT observé](docs/mqtt_contract.md)
- [Fiabilité et reprise](docs/reliability.md)
- [Stockage SQLite et outbox](docs/storage.md)

## État du projet

Deux couches sont maintenant implémentées et testées sans matériel ni réseau :

1. **noyau protocolaire D1**
   - `SmsTelemetry`, `ValidationResult`, `DjuaMqttPayload` ;
   - parser strict des 23 champs ;
   - base36 et flags ;
   - validation ;
   - normalisation MQTT.

2. **persistance fiable**
   - SQLite via la bibliothèque standard `sqlite3` ;
   - stockage du SMS brut avant traitement ;
   - déduplication brute et logique ;
   - conservation des SMS invalides ;
   - outbox MQTT persistante ;
   - reprise après redémarrage ;
   - APIs futures `mark_outbox_published()` et `record_publish_failure()`.

Le pipeline simulé est :

```text
RawSmsInput
    |
    v
SQLite COMMIT du brut
    |
    v
parse D1
    |
    v
validation
    |
    v
normalisation
    |
    v
transaction atomique :
  inbound_sms -> QUEUED
  + mqtt_outbox -> PENDING
```

La phase ne publie rien sur le réseau.

### Tests

Commande :

```bash
PYTHONPATH=src:. python -m unittest discover -s tests -p 'test_*.py'
```

Résultat actuel :

```text
95 tests
95 PASS
0 FAIL
0 SKIP
```

Les 58 tests du noyau D1 restent verts et 37 tests supplémentaires couvrent SQLite, déduplication, crash/reprise, multi-device, `uint32 millis()` et la distinction solaire `null` / `0.0`.

## Hors périmètre actuel

Toujours non implémentés :

- SIM800L réel ;
- pyserial ;
- commandes AT ;
- suppression réelle des SMS modem ;
- paho-mqtt ;
- connexion à un broker ;
- publication MQTT réelle ;
- daemon/service Windows ;
- Docker ;
- modification du firmware DJUA.

La phase suivante ne doit pas commencer sans autorisation explicite.
