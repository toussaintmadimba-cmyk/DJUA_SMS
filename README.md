# DJUA_SMS

Passerelle **SMS -> MQTT** du projet DJUA.

## Architecture cible

```text
CAPTEURS DJUA
      |
     ESP32
      |
construction de la télémétrie
      |
encodage protocole SMS DJUA
      |
    SIM800L
      |
      SMS
      |
 RÉSEAU GSM
      |
SIM800L POSTE RÉCEPTEUR
      |
DJUA_SMS GATEWAY
      |
validation / stockage / déduplication
      |
reconstruction du contrat MQTT DJUA
      |
     MQTT
      |
BROKER MQTT
      |
BACKEND DJUA
```

Le SMS est le transport cible du boîtier terrain. Il n'est pas conçu comme un fallback Wi-Fi.

## Règle absolue

Le dépôt `toussaintmadimba-cmyk/DJUA` est **READ ONLY** pour ce projet.

Il peut être consulté afin de comprendre le contrat existant, mais aucune écriture, branche, modification, commit, push ou pull request ne doit y être réalisée depuis ce projet.

Toutes les conceptions, documentations, simulations, tests et implémentations de la gateway doivent rester dans :

```text
toussaintmadimba-cmyk/DJUA_SMS
```

## Principe de compatibilité

La gateway sépare strictement :

```text
PROTOCOLE SMS COMPACT
        |
        v
DJUA_SMS GATEWAY
        |
        v
CONTRAT MQTT DJUA EXISTANT
```

Les métadonnées propres au SMS — version de protocole, numéro de séquence, flags de validité, checksum ou authentification — peuvent exister dans le SMS sans être ajoutées au payload MQTT du backend.

## Documentation d'architecture

Cette phase stabilise la conception avant toute implémentation applicative importante.

- [Règles du projet et garde-fous](AGENTS.md)
- [Architecture complète](docs/architecture.md)
- [Protocole SMS D1](docs/sms_protocol.md)
- [Contrat MQTT observé](docs/mqtt_contract.md)
- [Fiabilité, déduplication et reprise](docs/reliability.md)

## État du projet

La phase documentaire est terminée et le **noyau logiciel D1** est maintenant implémenté.

Implémenté dans cette phase :

- modèles `SmsTelemetry`, `ValidationResult` et `DjuaMqttPayload` ;
- parser strict des 23 champs D1 ;
- décodage base36 et flags ;
- validation structurelle sans seuil électrique naïf ;
- normalisation vers le contrat MQTT DJUA ;
- fixtures et tests unitaires, dont la taille SMS.

Tests exécutés sans SIM800L, sans port série, sans SQLite et sans broker :

```bash
PYTHONPATH=src:. python -m unittest discover -s tests -p 'test_*.py'
```

Résultat de cette phase :

```text
58 tests
58 PASS
0 FAIL
0 SKIP
```

Le test de taille confirme qu'un D1 typique avec auth compact peut atteindre 159 caractères, et que certains cas réalistes dépassent 160 caractères. Le protocole n'a pas été modifié automatiquement : ce point reste à arbitrer avant l'émetteur réel.

Toujours hors périmètre :

- SIM800L réel et commandes AT ;
- SQLite fonctionnel ;
- publisher MQTT réel ;
- daemon/service ;
- adaptation du firmware DJUA.

L'adaptation future du firmware émetteur DJUA au SMS reste une tâche séparée explicitement autorisée.
