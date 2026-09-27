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

La phase documentaire couvre :

1. lecture de DJUA sans modification ;
2. cartographie du contrat de télémétrie actuel ;
3. identification des topics et payloads MQTT ;
4. identification des données disponibles côté boîtier ;
5. conception du protocole SMS D1 ;
6. conception de l'architecture de DJUA_SMS ;
7. mapping SMS -> MQTT ;
8. stockage, déduplication, outbox, retry et reprise après panne.

Aucun driver SIM800L complet, service principal, stockage SQLite fonctionnel ou publisher MQTT complet n'est créé pendant cette phase.

L'adaptation future du firmware émetteur DJUA au SMS est hors périmètre de ce dépôt et doit faire l'objet d'une tâche séparée explicitement autorisée.
