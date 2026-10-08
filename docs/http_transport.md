# Transport HTTP configurable

DJUA_SMS peut maintenant livrer le même payload backend par MQTT, par HTTP, ou par les deux.

## Configuration

```text
DELIVERY_MODE=MQTT_ONLY
```

Valeurs autorisées :

```text
MQTT_ONLY
HTTP_ONLY
MQTT_AND_HTTP
```

Comportement :

```text
MQTT_ONLY
SMS -> SQLite -> mqtt_outbox -> MQTT

HTTP_ONLY
SMS -> SQLite -> http_outbox -> HTTP POST

MQTT_AND_HTTP
SMS -> SQLite
    -> mqtt_outbox -> MQTT
    -> http_outbox -> HTTP POST
```

Les deux outboxes sont créées dans la même transaction que le passage du SMS à l'état `QUEUED`.

## Variables HTTP

```text
HTTP_BACKEND_URL=http://host/api/iot/telemetry
HTTP_EVENT_URL=
HTTP_TIMEOUT_SECONDS=10
HTTP_RETRY_BASE_SECONDS=2
HTTP_RETRY_MAX_SECONDS=300
HTTP_API_KEY_HEADER=x-device-token
HTTP_API_KEY=
```

`HTTP_BACKEND_URL` est obligatoire lorsque le mode inclut HTTP.

`HTTP_EVENT_URL` est optionnel. S'il est vide, D2E utilise aussi `HTTP_BACKEND_URL`.

La clé API est optionnelle. Aucun secret réel ne doit être committé.

## Sémantique HTTP

La gateway envoie un `POST` avec :

```text
Content-Type: application/json
Accept: application/json
```

et exactement le `payload_json` normalisé déjà utilisé par la sortie MQTT.

Réponses :

```text
2xx            -> PUBLISHED
408/425/429    -> retry
5xx            -> retry
autres 4xx     -> FAILED terminal
erreur réseau  -> retry
```

Le backoff est exponentiel et plafonné, comme pour MQTT.

## Persistance

`http_outbox` contient notamment :

```text
sms_id
url
payload_json
status
attempt_count
next_attempt_at
last_error
published_at
```

Une coupure réseau ou un redémarrage de la gateway ne supprime pas une livraison HTTP en attente.

En mode double, `inbound_sms.status=PUBLISHED` seulement lorsque les deux sorties existantes sont publiées. Un échec terminal d'une sortie place le SMS en `FAILED`.

## Doublons

`MQTT_AND_HTTP` signifie deux livraisons indépendantes. Si MQTT et HTTP arrivent au même backend métier, ce backend doit traiter la possibilité de recevoir deux fois le même message logique.

Pour D2T/D2T2/D2E, le `message_id` normalisé permet la déduplication lorsqu'il est présent dans le contrat backend. Ne pas supposer une garantie exactly-once.

## D2E

Les messages D2E utilisent `HTTP_EVENT_URL` lorsqu'il est configuré. Cela permet de séparer par exemple :

```text
telemetry -> /api/iot/telemetry
D2E       -> /api/iot/geofence/events
```

sans changer le protocole SMS.
