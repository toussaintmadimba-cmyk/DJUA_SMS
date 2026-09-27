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

Trois couches sont maintenant implémentées :

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
   - reprise après redémarrage.

3. **transport MQTT**
   - `paho-mqtt==2.1.0` ;
   - client gateway indépendant des Client ID ESP32 ;
   - QoS 1 et suivi PUBACK par `mid` ;
   - mapping `mid -> outbox_id` ;
   - retry exponentiel plafonné ;
   - reprise des outbox `PENDING` après coupure/redémarrage ;
   - `mark_outbox_published()` seulement après ACK correspondant.

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

Le publisher réel est implémenté. Les tests automatisés utilisent des doubles sans broker ; un script séparé permet un test manuel avec un broker réel.

### Tests

Commande :

```bash
PYTHONPATH=src:. python -m unittest discover -s tests -p 'test_*.py'
```

Résultat actuel :

```text
123 tests
123 PASS
0 FAIL
0 SKIP
```

Les 96 tests précédents restent verts. 27 tests supplémentaires couvrent MQTT, PUBACK, deux publications en vol, déconnexion/reconnexion, retry/backoff et récupération après crash.

## Hors périmètre actuel

Toujours non implémentés :

- SIM800L réel ;
- pyserial ;
- commandes AT ;
- suppression réelle des SMS modem ;
- daemon/service Windows ;
- Docker ;
- modification du firmware DJUA.

### Installation MQTT

```bash
python -m pip install -r requirements.txt
```

La configuration est fournie par variables d'environnement ; `.env.example` documente les noms attendus. Aucun secret réel n'est versionné.

Test manuel broker :

```bash
PYTHONPATH=src python scripts/mqtt_test.py
```

Le script publie uniquement un message `DJUA_SMS_MQTT_CONNECTIVITY_TEST` sur un topic de diagnostic, jamais une fausse télémétrie terrain. Voir `docs/mqtt_transport.md`.

La phase suivante ne doit pas commencer sans autorisation explicite.
