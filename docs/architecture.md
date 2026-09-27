# Architecture DJUA_SMS

## 1. Objet du système

DJUA_SMS est la passerelle de transport entre les boîtiers terrain DJUA et le backend existant.

```text
BOÎTIER DJUA
    |
    v
SIM800L émetteur
    |
    v
SMS
    |
    v
RÉSEAU GSM
    |
    v
SIM800L récepteur
    |
    v
DJUA_SMS
    |
    +--> validation
    +--> persistance
    +--> déduplication
    +--> normalisation
    +--> outbox
    |
    v
MQTT
    |
    v
BROKER
    |
    v
BACKEND DJUA
```

Le SMS est le transport cible officiel du boîtier terrain. Il n'est pas un mécanisme de secours au Wi-Fi.

## 2. Architecture DJUA actuelle — référence uniquement

**CONFIRMÉ PAR DJUA**

La branche `main` du dépôt `toussaintmadimba-cmyk/DJUA` contient encore une architecture où l'ESP32 utilise directement Internet :

```text
ESP32
  |
  +--> Wi-Fi --> MQTT --> broker --> API DJUA
  |
  +--> Wi-Fi --> HTTP  --> backend
```

Le firmware construit `TelemetryData`, publie un JSON MQTT et peut également effectuer un POST HTTP.

Cette architecture sert uniquement de source pour comprendre le contrat existant.

```text
DJUA = READ ONLY
```

DJUA_SMS ne modifie ni ce firmware, ni le backend, ni les topics existants.

## 3. Architecture cible

**CHOIX D'ARCHITECTURE DJUA_SMS**

```text
CAPTEURS
  |
  v
ESP32
  |
  v
construction de la télémétrie
  |
  v
encodage protocole SMS DJUA
  |
  v
SIM800L émetteur
  |
  v
SMS
  |
  v
réseau GSM
  |
  v
SIM800L récepteur
  |
  v
driver modem
  |
  v
SMS receiver
  |
  v
raw SMS storage
  |
  v
parser
  |
  v
validator
  |
  v
deduplicator
  |
  v
normalizer
  |
  v
MQTT outbox
  |
  v
MQTT publisher
  |
  v
broker
  |
  v
backend DJUA
```

La gateway masque la différence de transport au backend : elle reconstruit le contrat MQTT déjà utilisé par DJUA.

## 4. Responsabilités

### Boîtier DJUA

**Architecture future — hors périmètre de cette phase**

Responsabilités futures :

- mesurer les grandeurs physiques ;
- calculer les valeurs dérivées ;
- horodater ;
- encoder un message SMS DJUA ;
- envoyer le SMS via le SIM800L.

L'adaptation du firmware n'est pas réalisée dans DJUA_SMS.

### SIM800L émetteur

**À VALIDER DANS UNE TÂCHE FUTURE**

Il transportera le message produit par l'ESP32 vers le réseau GSM. Le comportement exact d'émission ne doit pas être supposé avant validation matérielle.

### Réseau GSM

Transport externe entre le boîtier et le poste récepteur. La gateway ne contrôle ni le délai, ni l'ordre d'arrivée, ni une éventuelle retransmission opérateur.

### SIM800L récepteur

**À VALIDER AVEC SIM800L RÉEL**

Il reçoit les SMS et les expose au poste récepteur via une liaison série et des commandes AT.

Le principe de sûreté retenu exige que le SMS ne soit supprimé du modem qu'après persistance locale réussie.

### Driver modem

Responsable uniquement de :

- ouverture/fermeture de la liaison série ;
- commandes AT ;
- détection du modem ;
- interrogation SIM/réseau ;
- lecture des SMS ;
- suppression explicite d'un SMS lorsque le service l'autorise ;
- timeouts et reconnexion série.

Il ne parse pas le protocole DJUA et ne publie pas MQTT.

### SMS receiver

Transforme les événements du modem en objets de réception bruts comprenant au minimum :

- identifiant local ;
- numéro expéditeur ;
- horodatage fourni par le modem si disponible ;
- contenu brut ;
- horodatage local de réception.

Il transmet ensuite le message au stockage brut.

### Raw SMS storage

Persiste le SMS original avant toute suppression du modem.

Objectif : disposer d'une copie durable et diagnostiquable même si le parsing, MQTT ou Internet échoue ensuite.

### Parser

Convertit le texte SMS conforme au protocole `D1` en objet interne structuré.

Il ne décide pas si la donnée est physiquement plausible et n'effectue aucune publication MQTT.

### Validator

Vérifie notamment :

- version de protocole ;
- nombre et ordre des champs ;
- formats numériques ;
- identifiant de boîtier ;
- timestamp ;
- coordonnées ;
- cohérence des flags ;
- authentification si activée.

Il distingue erreur de format et valeur métier suspecte.

### Deduplicator

Détermine si le message logique a déjà été accepté.

Il ne repose jamais uniquement sur l'index mémoire du SIM800L.

### Normalizer

Transforme l'objet interne DJUA_SMS en payload MQTT compatible avec le contrat réellement publié par DJUA.

Il applique les conventions du contrat existant, par exemple les champs absents ou `null` lorsque cela est requis par le code actuel.

### MQTT outbox

Conserve de manière persistante les publications à effectuer.

Une coupure Internet ou MQTT ne doit pas faire perdre un message déjà validé.

### MQTT publisher

Responsable uniquement de :

- connexion au broker ;
- reconnexion ;
- publication ;
- attente de la confirmation broker lorsque le QoS le permet ;
- journalisation des erreurs ;
- mise à jour de l'outbox.

### Backend DJUA

**CONFIRMÉ PAR DJUA**

Le backend actuel consomme les topics structurés DJUA, dont la télémétrie `.../<device_id>/telemetry`.

DJUA_SMS ne remplace pas le backend et ne lui ajoute pas automatiquement de nouveaux champs.

## 5. Flux principal sécurisé

**CHOIX D'ARCHITECTURE DJUA_SMS**

```text
SMS reçu par le modem
        |
        v
lecture du SMS
        |
        v
persistance brute SQLite
        |
        v
COMMIT SQLite
        |
        v
suppression du SMS désormais possible dans le modem
        |
        v
parsing D1
        |
        v
validation
        |
        v
déduplication
        |
        v
normalisation vers contrat DJUA
        |
        v
création entrée outbox MQTT
        |
        v
publication MQTT
        |
        v
confirmation broker
        |
        v
PUBLISHED
```

## 6. Pourquoi persister avant de supprimer du modem

Le modem constitue la première copie du message reçu.

Supprimer ce SMS avant d'avoir obtenu un `COMMIT` local créerait une fenêtre de perte :

```text
SMS supprimé du modem
        |
crash PC / panne application
        |
aucune copie durable
        |
donnée perdue
```

La règle est donc :

```text
lecture SMS
-> écriture locale
-> COMMIT réussi
-> seulement ensuite suppression modem
```

La publication MQTT intervient après. Une panne Internet ne doit donc jamais conditionner la conservation initiale du SMS.

## 7. Frontières entre modules

Aucun module ne doit mélanger ces responsabilités :

```text
commandes AT
parsing protocole SMS
validation
SQLite
déduplication
normalisation MQTT
publication MQTT
```

Exemples de dépendances autorisées :

```text
gsm -> modèles de réception
protocol/parser -> modèles D1
validator -> modèles D1
storage -> modèles persistables
normalizer -> modèles validés
mqtt publisher -> entrées outbox
service gateway -> orchestration
```

Le service d'orchestration coordonne les modules mais ne réimplémente pas leur logique.

## 8. Multi-device

DJUA_SMS doit traiter plusieurs boîtiers.

Le `device_id` est porté dans le protocole SMS et sert à reconstruire :

```text
<MQTT_TOPIC_PREFIX>/<device_id>/telemetry
```

La gateway ne doit pas contenir une logique codée en dur pour un seul boîtier.

## 9. Geofencing

**CONFIRMÉ PAR DJUA**

DJUA publie actuellement aussi des topics `geofence` et `geofence/events`.

**CHOIX D'ARCHITECTURE DJUA_SMS**

Le protocole `D1` défini pendant cette phase couvre la télémétrie principale. Le transport SMS des événements geofence devra être défini explicitement séparément si cette fonction entre dans le périmètre futur. Il ne faut pas étendre silencieusement `D1`.

## 10. Limites de validation de cette phase

Cette phase est documentaire.

Non validé à ce stade :

- réception physique d'un SMS ;
- comportement réel des commandes AT ;
- conservation effective du SMS dans la mémoire modem ;
- reconnexion série ;
- publication vers un broker réel depuis DJUA_SMS ;
- chaîne complète SMS -> backend.

Ces éléments restent respectivement **À VALIDER AVEC SIM800L RÉEL** ou **À VALIDER END-TO-END**.
