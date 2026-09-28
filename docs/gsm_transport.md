# Transport GSM/SMS du poste récepteur DJUA_SMS

> `toussaintmadimba-cmyk/DJUA` reste strictement **READ ONLY**.

## 1. Statut

La chaîne logicielle de réception GSM est maintenant implémentée :

```text
SIM800L
   ↓
UART / USB série
   ↓
PySerialTransport
   ↓
AtProtocol
   ↓
Sim800Modem
   ↓
+CMTI / CMGR
   ↓
SmsReceiver
   ↓
SmsIngestionService
   ↓
SQLite
   ↓
mqtt_outbox
   ↓
MqttOutboxWorker
```

**TESTÉ AUTOMATIQUEMENT** :

- transport série avec double injecté ;
- protocole AT ;
- timeout ;
- `ERROR`, `+CME ERROR`, `+CMS ERROR` ;
- séparation simple réponses / URC ;
- `+CMTI` reçu pendant une autre commande ;
- initialisation modem ;
- CPIN ;
- CREG ;
- CSQ ;
- CMGF ;
- CPMS ;
- CNMI ;
- CMGR ;
- CMGL ;
- CMGD précis ;
- persistance avant suppression ;
- `DUPLICATE_RAW` ;
- SMS non D1 ;
- récupération au démarrage ;
- déconnexion/reconnexion série ;
- revalidation du modem après reconnexion ;
- flux simulé complet SMS -> SQLite -> outbox -> MQTT -> PUBACK.

**NON VALIDÉ MATÉRIELLEMENT DANS CET ENVIRONNEMENT** :

- port COM réel ;
- SIM800L physique ;
- SMS réellement reçu par le réseau GSM ;
- comportement réel du stockage `SM` / `ME` du module utilisé ;
- comportement réel du mode CNMI choisi ;
- SMS concaténés.

## 2. Dépendance série

La dépendance est fixée dans `requirements.txt` :

```text
pyserial==3.5
```

Elle s'ajoute à :

```text
paho-mqtt==2.1.0
```

Aucune couche système Windows spécifique n'est utilisée.

Le même code série est destiné à fonctionner avec les noms de ports fournis par l'utilisateur sous Windows, Linux ou Raspberry Pi.

## 3. Configuration

Variables disponibles :

```text
SERIAL_PORT=
SERIAL_BAUD_RATE=9600
SERIAL_TIMEOUT_SECONDS=0.5
SERIAL_WRITE_TIMEOUT_SECONDS=2

GSM_INIT_RETRIES=3
GSM_COMMAND_TIMEOUT_SECONDS=5
GSM_RECONNECT_SECONDS=5

GSM_SMS_STORAGE=
GSM_CNMI=2,1,0,0,0
```

Aucun port tel que `COM16`, `COM19` ou `/dev/ttyUSB0` n'est codé en dur dans le code applicatif.

Le port réel doit être fourni par configuration ou explicitement à un script de diagnostic.

## 4. Baudrate

Valeur par défaut de test :

```text
9600
```

Cette valeur correspond au SIM800L déjà testé auparavant dans le projet, mais elle reste configurable.

Elle ne constitue pas une garantie que tous les modules SIM800L répondront à 9600.

## 5. Câblage logique

La gateway suppose uniquement la chaîne logique suivante :

```text
PC / Linux / Raspberry Pi
        ↓
interface série accessible par pyserial
        ↓
SIM800L
```

Le câblage électrique exact USB/UART, l'alimentation du module, l'adaptation de niveau et le modèle précis de convertisseur ne sont pas définis dans cette phase parce que le matériel réel du poste récepteur n'a pas été spécifié.

Aucun brochage inventé n'est donc documenté ici.

## 6. PySerialTransport

`PySerialTransport` est responsable uniquement de :

- ouverture du port ;
- fermeture ;
- écriture d'une ligne AT terminée par `\r` ;
- lecture ligne par ligne ;
- timeout fourni par pyserial ;
- vidage raisonnable des buffers ;
- détection des erreurs d'E/S ;
- reconnexion.

Il ne connaît pas :

- D1 ;
- SMS ;
- SQLite ;
- MQTT.

Une erreur série ferme l'objet pyserial et remonte sous forme de :

```text
SerialTransportError
```

afin que l'orchestrateur puisse réinitialiser la chaîne modem.

## 7. AtProtocol

Le protocole AT exécute :

```text
commande
↓
lignes réponse
↓
OK / ERROR / timeout
```

Le résultat est un `AtResponse` contenant :

```text
command
lines
ok
error
timed_out
```

Les erreurs terminales distinguées incluent :

```text
ERROR
+CME ERROR: ...
+CMS ERROR: ...
TIMEOUT
```

Le timeout ne crée pas de boucle bloquée indéfiniment.

## 8. URC asynchrones

Une petite file interne conserve les indications spontanées.

Sont notamment séparés des réponses de commande :

```text
+CMTI
RDY
Call Ready
SMS Ready
```

Exemple testé :

```text
AT+CSQ
↓
+CMTI: "SM",4
↓
+CSQ: 26,0
↓
OK
```

Résultat :

- `+CSQ` reste la réponse de `AT+CSQ` ;
- `+CMTI` reste disponible ensuite dans la file URC.

La V1 ne construit pas un moteur AT concurrent complexe.

## 9. Initialisation SIM800L

La séquence logicielle utilise :

```text
AT
AT+CMEE=2
AT+CPIN?
AT+CREG?
AT+CSQ
AT+CMGF=1
AT+CPMS?
AT+CNMI=...
```

Si un stockage explicite est configuré, `AT+CPMS="<storage>"` est envoyé avant la requête d'état.

Sinon, DJUA_SMS n'impose pas silencieusement `SM` ou `ME`.

## 10. États distingués

Le rapport d'initialisation ne confond pas les niveaux suivants :

```text
MODEM_PRESENT
SIM_READY
NETWORK_REGISTERED
SMS_READY
```

Un simple :

```text
AT
OK
```

ne signifie donc pas automatiquement que la SIM est prête ou que le réseau GSM est enregistré.

## 11. CPIN

`AT+CPIN?` distingue au minimum :

```text
READY
SIM PIN
SIM PUK
UNKNOWN
```

DJUA_SMS n'envoie jamais automatiquement un PIN ou un PUK.

Aucun code secret n'est présent dans Git.

## 12. Enregistrement réseau

`AT+CREG?` distingue notamment :

```text
0 -> non enregistré
1 -> HOME
2 -> recherche réseau
3 -> refusé
4 -> inconnu
5 -> ROAMING
```

`HOME` et `ROAMING` sont considérés comme enregistrés.

Un état non enregistré est diagnostiqué mais n'est pas transformé en crash permanent.

Après une reconnexion du port, l'initialisation complète relit CREG.

## 13. Qualité du signal

`AT+CSQ` est conservé comme :

```text
rssi
ber
```

La valeur :

```text
rssi = 99
```

est marquée comme inconnue.

Aucune précision de couverture supplémentaire n'est inventée.

## 14. Mode SMS texte

La gateway demande :

```text
AT+CMGF=1
```

et conserve le résultat.

D1 reste un format ASCII compact ; cette phase ne modifie pas D1.

## 15. Stockage SMS / CPMS

Par défaut, DJUA_SMS interroge :

```text
AT+CPMS?
```

afin d'obtenir le stockage réellement sélectionné et :

```text
used
total
```

Si `GSM_SMS_STORAGE` est renseigné, le stockage est sélectionné explicitement.

Lorsqu'une notification `+CMTI` indique une autre mémoire, le modem sélectionne cette mémoire avant `CMGR` / `CMGD`.

La gateway journalise un WARNING lorsque l'utilisation atteint au moins 80 % de la capacité annoncée.

Elle ne supprime jamais un SMS non persisté pour libérer de la place.

## 16. Choix CNMI V1

Valeur par défaut :

```text
AT+CNMI=2,1,0,0,0
```

**CHOIX D'ARCHITECTURE DJUA_SMS À VALIDER SUR LE SIM800L RÉEL**

Le but est d'obtenir une notification d'index :

```text
+CMTI: "<mem>",<index>
```

plutôt que de dépendre du mode de livraison directe utilisé auparavant avec `2,2,0,0,0`.

Le réglage reste configurable par :

```text
GSM_CNMI
```

La phase ne prétend pas que chaque firmware SIM800L réagit exactement de la même manière avant le test matériel.

## 17. +CMTI

Exemples testés :

```text
+CMTI: "SM",1
+CMTI: "SM",42
+CMTI: "ME", 42
```

Ils deviennent :

```text
storage
index
```

Une notification malformée est ignorée avec diagnostic et ne tue pas le service.

## 18. CMGR

Après une notification :

```text
+CMTI: "SM",7
```

DJUA_SMS exécute :

```text
AT+CMGR=7
```

et construit un `ModemSms` avec :

```text
storage
index
status
sender
modem_timestamp
raw_body
```

Le sender est conservé tel que fourni par le modem avec uniquement un `strip()` extérieur.

Aucune conversion automatique vers un format international n'est imposée.

## 19. Timestamp modem

`modem_timestamp` est une métadonnée de transport.

Il reste séparé de :

```text
D1.rtc
MQTT.timestamp
MQTT.timestamp_ms
```

Le normalizer continue d'utiliser les valeurs du boîtier DJUA.

L'heure de réception gateway et l'heure modem ne remplacent pas le timestamp terrain.

## 20. SMS multiligne

Le body lu après `+CMGR` est conservé en joignant les lignes avec `\n`.

D1 attendu reste une ligne.

Les tests couvrent :

- D1 valide ;
- texte non D1 ;
- body vide ;
- body multiligne ;
- `+CMS ERROR` ;
- `+CMTI` intercalé pendant `CMGR`.

Limitation V1 : une ligne de contenu humain exactement égale à un terminal AT comme `OK` ou `ERROR` reste intrinsèquement ambiguë avec une réponse AT textuelle générique. D1 n'utilise pas cette forme.

## 21. SmsReceiver

`SmsReceiver` est responsable de :

```text
+CMTI
↓
CMGR
↓
ModemSms
↓
RawSmsInput
↓
SmsIngestionService
↓
résultat durable
↓
CMGD autorisé
```

Il ne :

- parse pas D1 ;
- ne manipule pas directement SQLite ;
- ne publie pas MQTT.

## 22. Règle exacte de suppression

La règle non négociable est :

```text
CMGR réussi
↓
SmsIngestionService
↓
SQLite durable
↓
seulement ensuite CMGD=<index>
```

`CMGD` est interdit si l'ingestion lève une erreur avant confirmation durable.

Aucune commande globale telle que :

```text
AT+CMGD=1,4
```

n'est utilisée dans le fonctionnement normal.

## 23. SMS D1 valide

Cas :

```text
D1 valide
↓
inbound_sms durable
↓
mqtt_outbox PENDING durable
↓
CMGD exact
↓
MQTT peut avoir lieu plus tard
```

CMGD n'attend jamais un PUBACK MQTT.

## 24. SMS invalide / non D1

Exemple :

```text
BONJOUR
```

Résultat :

```text
inbound_sms créé
status = INVALID
raw_body conservé
aucune outbox
↓
CMGD autorisé après commit
```

Un SMS inconnu ne reste donc pas éternellement dans la SIM une fois archivé durablement.

## 25. DUPLICATE_RAW

Cas critique :

```text
SQLite commit
↓
crash avant CMGD
↓
même SMS relu
↓
DUPLICATE_RAW
↓
pas de deuxième inbound logique
↓
pas de deuxième outbox
↓
CMGD autorisé
```

Ce scénario est couvert par test d'intégration.

## 26. Échec SQLite

Si :

```text
CMGR OK
↓
ingestion / SQLite échoue
```

alors :

```text
CMGD jamais appelé
```

Ce comportement est protégé par test.

## 27. Échec CMGD

Si SQLite a déjà confirmé la persistance mais que CMGD échoue :

- la transaction SQLite n'est jamais annulée ;
- le SMS peut rester dans le modem ;
- une relecture ultérieure produit `DUPLICATE_RAW` ;
- aucune seconde outbox n'est créée.

Une perte physique du port pendant CMGD remonte vers l'orchestrateur pour reconnexion.

## 28. Déconnexion série

Une erreur d'E/S pyserial devient :

```text
SerialTransportError
```

Le port est fermé et l'orchestrateur peut exécuter :

```text
reconnect
↓
AT
↓
CPIN
↓
CREG
↓
CSQ
↓
CMGF
↓
CPMS
↓
CNMI
↓
CMGL recovery
```

Un test vérifie que la séquence de configuration est réellement rejouée après reconnexion.

## 29. Startup recovery

La gateway ne dépend pas uniquement des `+CMTI` reçus pendant qu'elle fonctionne.

Après initialisation, elle exécute :

```text
AT+CMGL="ALL"
```

puis traite les SMS déjà présents avec le même contrat :

```text
ingestion durable
↓
CMGD précis
```

Ainsi, un SMS arrivé pendant l'arrêt de la gateway peut être récupéré au prochain démarrage, sous réserve du comportement réel de stockage du SIM800L.

## 30. Gateway orchestrator

`DjuaSmsGateway` coordonne :

```text
Sim800Modem
SmsReceiver
MqttOutboxWorker
```

La logique métier reste dans les composants spécialisés.

La V1 est synchrone côté GSM.

La boucle réseau interne de Paho reste la seule concurrence déjà fournie par la bibliothèque MQTT.

## 31. Ordre GSM vs MQTT

Le pipeline voulu est :

```text
SMS
↓
SQLite COMMIT
↓
CMGD
↓
MQTT éventuellement plus tard
```

et non :

```text
SMS
↓
attendre Internet
↓
attendre PUBACK
↓
CMGD
```

C'est précisément le rôle de l'outbox persistante.

## 32. Scripts matériels

### Probe série

```bash
PYTHONPATH=src python scripts/serial_probe.py --port <PORT> --baud 9600
```

Envoie uniquement `AT` et affiche la réponse.

### Diagnostic modem

```bash
PYTHONPATH=src python scripts/modem_test.py --port <PORT> --baud 9600
```

Vérifie :

```text
AT
CMEE
CPIN
CREG
CSQ
CMGF
CPMS
CNMI
```

Aucun SMS n'est supprimé.

### Réception interactive

```bash
PYTHONPATH=src python scripts/sms_receive_test.py --port <PORT> --baud 9600
```

Le script :

1. initialise le modem ;
2. attend `+CMTI` ;
3. lit le SMS ;
4. affiche les métadonnées ;
5. demande explicitement si l'utilisateur veut l'ingérer ;
6. si oui, utilise SQLite et ne supprime qu'après confirmation durable.

## 33. Logging

Événements disponibles notamment :

```text
GSM_PORT_OPEN
GSM_PORT_LOST
MODEM_DETECTED
SIM_READY
NETWORK_REGISTERED
NETWORK_NOT_REGISTERED
GSM_SIGNAL
SMS_STORAGE
SMS_NOTIFICATION
SMS_READ
SMS_STORED
SMS_DUPLICATE
SMS_INVALID
SMS_DELETE_OK
SMS_DELETE_FAILED
```

Le contenu complet du SMS n'est pas journalisé par défaut dans les services.

Le script de diagnostic interactif peut l'afficher explicitement à l'utilisateur.

## 34. Sécurité

Cette phase ne met pas en place :

- whitelist sender ;
- liaison sender <-> device_id ;
- HMAC.

Le sender et le champ D1 `auth` sont conservés pour une phase ultérieure.

Le statut actuel reste :

```text
AUTH_NOT_VERIFIED
```

Un numéro expéditeur connu n'est pas considéré automatiquement comme preuve d'authenticité.

## 35. SMS concaténés

Le receiver ne prétend pas reconstruire automatiquement les SMS concaténés.

Le problème déjà documenté où certains D1 peuvent dépasser 160 caractères reste une décision de protocole/émetteur séparée.

Cette phase ne modifie pas D1 pour masquer cette limite.

## 36. Tests automatisés

État de référence avant GSM :

```text
123 PASS
```

État après cette phase :

```text
177 tests
177 PASS
0 FAIL
0 SKIP
```

Les 54 nouveaux tests couvrent les couches GSM et les intégrations simulées.

Le CI installe réellement :

```text
paho-mqtt==2.1.0
pyserial==3.5
```

puis exécute :

```text
compileall
unittest discover
```

## 37. Tests matériels à faire sur le poste réel

Ordre recommandé :

```text
1. serial_probe.py
2. modem_test.py
3. vérifier CPMS réel
4. vérifier CNMI réel
5. envoyer un vrai SMS
6. observer +CMTI
7. CMGR
8. ingestion SQLite
9. CMGD après persistance
10. vérifier mqtt_outbox
11. ensuite seulement tester MQTT/backend
```

Ne pas sauter directement au test complet.

## 38. Validation matérielle

À ce stade :

```text
TEST MOCK / SÉRIE SIMULÉ : EFFECTUÉ
TEST SIM800L RÉEL          : NON EFFECTUÉ
TEST SMS RÉEL              : NON EFFECTUÉ
```

L'environnement GitHub/ChatGPT ne possède pas le port COM physique du poste récepteur.

Aucune validation matérielle n'est donc revendiquée.
