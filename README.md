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

## État du projet

La première phase consiste à :

1. lire DJUA sans le modifier ;
2. cartographier le contrat de télémétrie actuel ;
3. identifier les topics et payloads MQTT ;
4. identifier les données disponibles côté boîtier ;
5. concevoir le protocole SMS ;
6. concevoir l'architecture de DJUA_SMS ;
7. définir le mapping SMS -> MQTT ;
8. définir stockage, déduplication, retry et reprise après panne.

L'adaptation future du firmware émetteur DJUA au SMS est hors périmètre de ce dépôt et doit faire l'objet d'une tâche séparée explicitement autorisée.
