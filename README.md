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
SIM868 récepteur (pilote historique SIM800)
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
    +--> dispatch D1 / D2T / D2T2 / D2E
    +--> parsing / validation / sécurité
    +--> normalisation backend
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
- [Protocole SMS D2](docs/sms_protocol_v2.md)\n- [Protocole SMS D2T2 compact + charge DC](docs/sms_protocol_d2t2.md)
- [Contrat de données backend](docs/backend_data_contract.md)
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

La suite couvre D1/GSM/MQTT ainsi que D2T/D2T2/D2E, HMAC, GSM-7, migration SQLite, déduplication/conflits et flux GSM/MQTT simulés. Le résultat exact du dernier run CI doit être utilisé comme preuve, plutôt qu'un compteur statique dans ce fichier.

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
TEST MOCK / SÉRIE SIMULÉ D2 : EFFECTUÉ
RÉCEPTEUR MATÉRIEL            : SIM868 CONFIRMÉ PAR LE PROJET
AT/SMS PILOTE HISTORIQUE      : A DÉJÀ FONCTIONNÉ AVEC SIM868
VRAI SMS D2                   : NON TESTÉ DANS CETTE PHASE
BACKEND RÉEL D2               : NON VALIDÉ
```

Les scripts sont prêts pour le poste physique, mais l'environnement GitHub/ChatGPT n'a pas accès à son port COM.

## Hors périmètre après cette phase

Ne pas commencer automatiquement :

- modification du firmware `DJUA` ;
- émetteur SMS ESP32 ;
- modification D1 ;
- service Windows ;
- Docker.

Attendre une autorisation explicite pour l'étape suivante.

## D2T / D2T2 / D2E

D2 étend la gateway existante ; il ne crée pas une deuxième chaîne de réception.

```text
D1,   -> comportement historique
D2T,  -> télémétrie périodique legacy
D2T2, -> télémétrie compacte + charge DC
D2E,  -> événement urgent GX/GE
```

D2T contient exactement 22 champs et son maximum authentifié est 160 septets GSM-7. D2T2 conserve les mesures D2T, ajoute tension/courant/puissance/énergie de charge DC dans un payload compact de 60 octets, et son maximum authentifié est 130 septets. D2E contient 11 champs et son maximum est 97 septets.

Le `message_id` est dérivé côté gateway sous la forme `D2:<device_id>:<sequence_base36>`. Un même message_id avec le même contenu signé est un replay ; avec un contenu signé différent, il devient `MESSAGE_ID_CONFLICT` et aucune seconde outbox n'est créée.

La configuration D2 utilise `D2_AUTH_MODE`, `D2_HMAC_KEYS_JSON` et `D2_SENDER_BINDINGS_JSON`. Aucun secret réel ne doit être committé.

Le script `sms_receive_test.py` charge cette configuration depuis l'environnement.


## Automatisation Windows temporaire

Pour la phase de test, DJUA_SMS peut fonctionner sans commande quotidienne et sans service Windows.

Double-cliquer une seule fois sur :

\`\`\`text
setup_windows_test.bat
\`\`\`

Le script :

1. crée \`.venv\` si nécessaire ;
2. installe/vérifie les dépendances ;
3. crée \`config/gateway.env\` à partir du modèle local ;
4. ouvre ce fichier dans le Bloc-notes si une configuration est nécessaire ;
5. vérifie la configuration sans ouvrir le modem ni MQTT ;
6. installe la tâche Windows \`DJUA SMS Gateway Test\` ;
7. démarre immédiatement la gateway en arrière-plan.

Au prochain logon Windows, la tâche relance automatiquement DJUA_SMS.

Le lanceur permanent est \`scripts/run_gateway.py\` et réutilise directement :

\`\`\`text
SIM868 -> SmsReceiver -> SQLite -> D1/D2T/D2T2/D2E -> mqtt_outbox -> MQTT
\`\`\`

La console est masquée par \`start_djua_gateway_hidden.vbs\`. Le lanceur batch redémarre le processus après une erreur fatale avec un délai de 10 secondes.

La configuration locale est \`config/gateway.env\`. Le modèle propose déjà \`COM16\`, 9600 bauds et \`D2_AUTH_MODE=development\`. \`MQTT_HOST\` doit être renseigné avec le broker utilisé pour les essais.

Les logs sont écrits dans \`logs/gateway.log\`, avec rotation à 5 MiB et cinq sauvegardes.

Pour arrêter proprement la gateway sans CMD, double-cliquer sur \`stop_djua_gateway.bat\`.

Pour arrêter et retirer le démarrage automatique, double-cliquer sur \`disable_windows_test_autostart.bat\`.

Les vrais secrets D2/MQTT restent uniquement dans \`config/gateway.env\`, qui est ignoré par Git.
