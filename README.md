# DJUA_SMS

Passerelle **SMS -> SQLite -> MQTT** du projet DJUA.

## Règle absolue

Le dépôt :

```text
toussaintmadimba-cmyk/DJUA
```

reste **READ ONLY**.

Toutes les implémentations de la gateway sont réalisées uniquement dans :

```text
toussaintmadimba-cmyk/DJUA_SMS
```

## Architecture

```text
SIM800L récepteur
    |
    v
pyserial
    |
    v
AT protocol
    |
    v
+CMTI / CMGR
    |
    v
SmsReceiver
    |
    v
SmsIngestionService
    |
    +--> SQLite inbound_sms
    +--> déduplication
    +--> parser / validator / normalizer D1
    +--> mqtt_outbox PENDING
    |
    v
MqttOutboxWorker
    |
    v
MQTT QoS 1 / PUBACK
    |
    v
backend DJUA
```

La règle de non-perte côté modem est :

```text
CMGR
-> SQLite COMMIT durable
-> seulement ensuite CMGD=<index>
```

CMGD n'attend pas MQTT.

## Documentation

- [Règles du projet](AGENTS.md)
- [Architecture](docs/architecture.md)
- [Protocole SMS D1](docs/sms_protocol.md)
- [Transport GSM/SMS](docs/gsm_transport.md)
- [Stockage SQLite](docs/storage.md)
- [Fiabilité et reprise](docs/reliability.md)
- [Contrat MQTT](docs/mqtt_contract.md)
- [Transport MQTT](docs/mqtt_transport.md)

## Composants implémentés

1. **D1**
   - parser ;
   - validator ;
   - normalizer.

2. **Persistance**
   - SQLite `sqlite3` ;
   - `inbound_sms` ;
   - déduplication brute et logique ;
   - `mqtt_outbox` persistante ;
   - recovery.

3. **MQTT**
   - `paho-mqtt==2.1.0` ;
   - QoS 1 ;
   - mapping `mid -> outbox_id` ;
   - PUBACK ;
   - retry/backoff ;
   - reconnexion.

4. **GSM/SMS récepteur**
   - `pyserial==3.5` ;
   - transport série portable ;
   - commandes AT ;
   - CPIN / CREG / CSQ / CMGF / CPMS / CNMI ;
   - `+CMTI` ;
   - CMGR / CMGL / CMGD précis ;
   - startup recovery ;
   - reconnexion série ;
   - suppression seulement après persistance durable.

## Installation

```bash
python -m pip install -r requirements.txt
```

La configuration de référence est dans `.env.example`.

Aucun port COM ni secret n'est codé en dur.

## Tests

Le dépôt possède un workflow GitHub Actions qui exécute :

```text
python -m compileall -q src tests scripts
PYTHONPATH=src:. python -m unittest discover -s tests -p 'test_*.py'
```

État actuel :

```text
TOTAL : 177
PASS  : 177
FAIL  : 0
SKIP  : 0
```

Les 123 tests précédents restent verts et 54 tests supplémentaires couvrent GSM/SMS.

## Diagnostics matériels

Probe série :

```bash
PYTHONPATH=src python scripts/serial_probe.py --port <PORT> --baud 9600
```

Diagnostic modem :

```bash
PYTHONPATH=src python scripts/modem_test.py --port <PORT> --baud 9600
```

Réception SMS interactive et sûre :

```bash
PYTHONPATH=src python scripts/sms_receive_test.py --port <PORT> --baud 9600
```

Le dernier script ne supprime un SMS qu'après confirmation durable par SQLite.

## Validation matérielle

```text
TEST MOCK / SÉRIE SIMULÉ : EFFECTUÉ
TEST SIM800L RÉEL          : NON EFFECTUÉ
TEST SMS RÉEL              : NON EFFECTUÉ
```

Les scripts sont prêts pour le poste physique, mais l'environnement GitHub/ChatGPT n'a pas accès à son port COM.

## Hors périmètre après cette phase

Ne pas commencer automatiquement :

- modification du firmware `DJUA` ;
- émetteur SMS ESP32 ;
- modification D1 ;
- HMAC ;
- service Windows ;
- Docker.

Attendre une autorisation explicite pour l'étape suivante.
