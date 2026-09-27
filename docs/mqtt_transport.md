# Transport MQTT de DJUA_SMS

> `toussaintmadimba-cmyk/DJUA` reste strictement **READ ONLY**.

## 1. Statut

La couche de transport MQTT de DJUA_SMS est maintenant implémentée.

**TESTÉ AUTOMATIQUEMENT** :

- chargement des outbox `PENDING` ;
- connexion/déconnexion/reconnexion via l'interface MQTT ;
- publication du topic et du payload déjà stockés ;
- QoS 1 ;
- association `mid -> outbox_id` ;
- PUBACK dans un ordre différent de l'ordre de publication ;
- course possible où le callback PUBACK arrive très vite ;
- timeout PUBACK ;
- retry/backoff ;
- coupure et reprise ;
- crash simulé avant PUBACK ;
- crash simulé après PUBACK mais avant commit SQLite ;
- plusieurs devices publiés par un même Client ID gateway.

**NON VALIDÉ DANS L'ENVIRONNEMENT D'EXÉCUTION DE CETTE PHASE** :

- connexion TCP réelle à un broker MQTT externe ;
- PUBACK provenant d'un broker réel ;
- persistance effective du message par le backend DJUA.

Un script manuel séparé est fourni pour effectuer le test broker réel.

## 2. Dépendance

La dépendance MQTT est fixée dans `requirements.txt` :

```text
paho-mqtt==2.1.0
```

Le code applicatif utilise Paho derrière une couche simple afin que le reste de la gateway et les tests unitaires ne dépendent pas directement de son API.

## 3. Architecture

```text
mqtt_outbox
    |
    v
MqttOutboxWorker
    |
    v
MqttPublisher
    |
    v
MqttClientProtocol
    |
    v
PahoMqttClient
    |
    v
broker MQTT
```

### PahoMqttClient

Responsable de :

- connexion ;
- reconnexion ;
- déconnexion ;
- boucle réseau Paho ;
- authentification username/password optionnelle ;
- TLS optionnel ;
- publication ;
- réception des callbacks `on_publish`.

Il ne connaît ni D1 ni la base métier.

### MqttPublisher

Responsable de :

- publier exactement une entrée outbox ;
- associer `mid` à `outbox_id` ;
- traiter le PUBACK correspondant ;
- appeler `mark_outbox_published()` après confirmation ;
- planifier un retry en cas d'échec ou de timeout.

Il ne renormalise jamais le SMS.

### MqttOutboxWorker

Responsable de :

- charger les outbox `PENDING` dues ;
- respecter `next_attempt_at` ;
- tenter la connexion si nécessaire ;
- lancer les publications dans l'ordre des `id` croissants ;
- laisser les messages durables dans SQLite en cas d'échec.

La V1 reste synchrone et ne crée pas de parallélisme complexe.

## 4. Source de vérité de publication

La publication utilise exactement :

```text
mqtt_outbox.topic
mqtt_outbox.payload_json
mqtt_outbox.qos
mqtt_outbox.retain
```

Le worker ne :

- parse pas D1 ;
- ne valide pas D1 ;
- ne reconstruit pas le topic ;
- ne reconstruit pas le JSON ;
- ne modifie pas le payload.

Le principe est :

```text
OUTBOX = message prêt à publier
```

## 5. Client ID

Valeur par défaut :

```text
djua-sms-gateway-001
```

Le Client ID de la gateway est indépendant de tout `device_id` terrain.

Il ne doit jamais reprendre la forme utilisée par un boîtier ESP32 DJUA.

Un seul client gateway peut publier pour :

```text
DJUA-KIN-000001
DJUA-KIN-000002
DJUA-KIN-000003
...
```

sans changer de Client ID MQTT.

## 6. Topic

Le topic est construit au moment de l'ingestion puis stocké dans l'outbox.

Valeur compatible par défaut :

```text
djua/test/<device_id>/telemetry
```

Le préfixe est configurable :

```text
MQTT_TOPIC_PREFIX=djua/test
```

La validation D1 existante limite `device_id` à :

```text
[A-Z0-9-]{1,32}
```

ce qui exclut notamment les caractères MQTT structurants :

```text
/
+
#
```

Un test d'intégration protège ce comportement.

## 7. Payload

Le transport publie exactement :

```text
mqtt_outbox.payload_json
```

Aucun champ de transport SMS n'est ajouté.

En particulier, le publisher n'ajoute jamais :

```text
protocol
sequence
flags
auth
```

La distinction :

```text
solaire invalide -> null
solaire valide à zéro -> 0.0
```

reste donc intacte jusque dans l'appel de publication.

## 8. QoS et retain

Valeurs par défaut :

```text
MQTT_QOS=1
MQTT_RETAIN=false
```

L'outbox reste toutefois la source de vérité : le publisher respecte les valeurs persistées dans chaque ligne.

## 9. PUBACK et mapping mid

Pour QoS 1 :

```text
publish()
    |
    v
mid
    |
    v
mid -> outbox_id
    |
    v
on_publish(mid)
    |
    v
mark_outbox_published(outbox_id)
```

Un PUBACK ne marque jamais toutes les lignes comme publiées.

Deux messages peuvent être en vol :

```text
outbox 1 -> mid 10
outbox 2 -> mid 11
```

et les ACK peuvent arriver :

```text
mid 11
puis
mid 10
```

sans confusion.

Le publisher gère également le cas où le callback de confirmation survient avant que le thread appelant ait terminé d'enregistrer le mapping du `mid`.

## 10. Timeout PUBACK

Si le PUBACK n'arrive pas avant :

```text
MQTT_PUBLISH_TIMEOUT_SECONDS
```

la ligne reste durablement `PENDING`, une tentative échouée est enregistrée et un prochain essai est planifié.

Un ACK tardif correspondant à une tentative déjà expirée n'est pas utilisé pour marquer la ligne `PUBLISHED`.

## 11. Retry et backoff

La formule actuelle est simple :

```text
delay = min(
    MQTT_RETRY_MAX_SECONDS,
    MQTT_RETRY_BASE_SECONDS * 2^attempt_count
)
```

Valeurs par défaut :

```text
MQTT_RETRY_BASE_SECONDS=2
MQTT_RETRY_MAX_SECONDS=300
```

Aucun jitter n'est ajouté en V1.

À chaque échec :

```text
attempt_count += 1
last_error = ...
next_attempt_at = ...
```

Le payload n'est jamais supprimé.

## 12. Broker indisponible

Les cas suivants doivent rester récupérables :

- DNS impossible ;
- connexion refusée ;
- timeout ;
- authentification refusée ;
- broker hors ligne ;
- connexion perdue.

Si une connexion ne peut pas être établie, les outbox dues restent `PENDING` et reçoivent une date de prochain essai.

SQLite reste la source durable indépendante de l'état réseau.

## 13. Reconnexion

Lorsque MQTT redevient disponible :

```text
list_pending_outbox(due_before=...)
    |
    v
publication reprise
```

Un redémarrage du processus ne crée pas une nouvelle outbox pour un SMS déjà ingéré.

Les éléments déjà `PUBLISHED` ne sont pas renvoyés par le worker normal.

## 14. Arrêt

`MqttOutboxWorker.shutdown()` déconnecte proprement le client MQTT.

Aucune outbox non confirmée n'est supprimée au shutdown.

## 15. Garantie réelle

La garantie de cette architecture est :

```text
at least once
```

et non :

```text
exactly once end-to-end
```

### Crash avant PUBACK

```text
publish
-> crash
-> SQLite reste PENDING
-> republication après redémarrage
```

### Crash après PUBACK mais avant COMMIT PUBLISHED

```text
broker accepte
-> PUBACK
-> crash avant commit SQLite
-> SQLite reste PENDING
-> republication possible
```

Cette duplication potentielle ne peut pas être éliminée parfaitement par la gateway seule sans mécanisme d'idempotence/accusé de réception approprié côté backend.

## 16. Configuration

Variables documentées dans `.env.example` :

```text
MQTT_HOST=
MQTT_PORT=1883
MQTT_CLIENT_ID=djua-sms-gateway-001
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_TOPIC_PREFIX=djua/test
MQTT_QOS=1
MQTT_RETAIN=false
MQTT_KEEPALIVE_SECONDS=60
MQTT_CONNECT_TIMEOUT_SECONDS=10
MQTT_PUBLISH_TIMEOUT_SECONDS=10
MQTT_RETRY_BASE_SECONDS=2
MQTT_RETRY_MAX_SECONDS=300
MQTT_TLS=false
```

La configuration valide notamment :

- host non vide ;
- port valide ;
- Client ID non vide ;
- QoS MQTT valide ;
- préfixe de topic sans wildcard ;
- timeouts positifs ;
- bornes de retry cohérentes.

Aucun mot de passe réel n'est versionné.

## 17. TLS

`MQTT_TLS=true` active la configuration TLS de Paho avec les autorités de certification disponibles sur le système.

Le port reste configurable : un déploiement TLS doit utiliser le port/configuration correspondant au broker.

```text
1883 sans TLS
```

doit être considéré comme un mode de test ou d'environnement contrôlé, pas comme une recommandation de production sur un réseau non fiable.

## 18. Test broker manuel

Installer :

```bash
python -m pip install -r requirements.txt
```

Définir les variables d'environnement nécessaires, puis :

```bash
PYTHONPATH=src python scripts/mqtt_test.py
```

Le script utilise un topic de diagnostic :

```text
<MQTT_TOPIC_PREFIX>/gateway-test/diagnostic
```

et publie un objet clairement identifié :

```text
DJUA_SMS_MQTT_CONNECTIVITY_TEST
```

Il ne prétend jamais être une télémétrie terrain réelle.

Un broker public peut servir à un test ponctuel, mais :

```text
broker public != production
```

Ne jamais y publier secrets, clés, données personnelles ou payload sensible.

## 19. Validation backend

Un PUBACK prouve que le broker a accepté la publication QoS 1.

Il ne prouve pas que :

```text
le backend DJUA a persisté le message
```

La validation backend/end-to-end doit rester une étape distincte.

## 20. Hors périmètre

Toujours non implémentés dans cette phase :

- SIM800L ;
- pyserial ;
- commandes AT ;
- service Windows ;
- interface graphique ;
- Docker ;
- modification du firmware DJUA.
