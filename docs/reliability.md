# Fiabilité, non-perte et reprise

> Règle de projet : `toussaintmadimba-cmyk/DJUA` est **READ ONLY**. Toutes les stratégies décrites ici concernent exclusivement `DJUA_SMS`.

## 1. Objectif

DJUA_SMS doit privilégier la conservation des données avant la rapidité de publication.

Principe :

```text
un SMS reçu et persisté localement
ne doit pas être perdu
par une panne Internet, MQTT ou un redémarrage du PC
```

Cette phase décrit la stratégie. Elle n'implémente pas encore SQLite ni le driver SIM800L.

## 2. Ordre de non-perte

**CHOIX D'ARCHITECTURE DJUA_SMS**

Ordre obligatoire :

```text
SMS présent dans le modem
        |
        v
lecture SMS
        |
        v
INSERT du message brut
        |
        v
COMMIT SQLite réussi
        |
        v
suppression du SMS autorisée dans le modem
        |
        v
parsing
        |
        v
validation
        |
        v
déduplication logique
        |
        v
normalisation
        |
        v
INSERT outbox MQTT
        |
        v
COMMIT outbox
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

Règle fondamentale :

```text
lecture SMS
-> SQLite COMMIT
-> suppression modem
```

Jamais l'inverse.

## 3. Pourquoi supprimer après COMMIT

Cas dangereux :

```text
lecture
-> suppression modem
-> crash avant stockage
= perte définitive
```

Cas retenu :

```text
lecture
-> stockage durable
-> COMMIT
-> suppression modem
-> crash éventuel
= reprise possible depuis SQLite
```

Une panne Internet n'intervient donc pas dans la décision initiale de conserver le SMS.

## 4. Réception SIM800L

**À VALIDER AVEC SIM800L RÉEL**

L'architecture privilégie un fonctionnement où le SMS reste stocké dans le modem/SIM jusqu'à ce que DJUA_SMS confirme sa persistance locale.

Une séquence de type :

```text
+CMTI
-> AT+CMGR=<index>
-> COMMIT SQLite
-> AT+CMGD=<index>
```

est conceptuellement adaptée.

Le choix exact de `AT+CNMI`, de la mémoire SMS et des commandes supportées ne doit pas être considéré comme validé avant essais avec le modem réel.

## 5. Modèle conceptuel de stockage

**CHOIX D'ARCHITECTURE DJUA_SMS**

Deux ensembles persistants sont nécessaires.

### inbound_sms

Conserve la preuve brute de réception.

Champs conceptuels :

```text
id
sender_number
modem_message_index
modem_timestamp
gateway_received_at
raw_body
raw_hash
protocol_version
device_id
logical_message_key
state
validation_error
created_at
updated_at
```

`modem_message_index` est une information de diagnostic, pas une identité durable.

### mqtt_outbox

Conserve ce qui doit être publié.

Champs conceptuels :

```text
id
inbound_sms_id
topic
payload
qos
retain
state
attempt_count
last_error
next_attempt
created_at
published_at
```

Le schéma final sera défini pendant l'implémentation.

## 6. États de traitement

**CHOIX D'ARCHITECTURE DJUA_SMS**

États conceptuels :

```text
RECEIVED
INVALID
VALIDATED
PENDING_MQTT
PUBLISHED
FAILED
```

Transitions normales :

```text
RECEIVED
   |
   +--> INVALID
   |
   +--> VALIDATED
            |
            v
       PENDING_MQTT
            |
            +--> PENDING_MQTT  (retry)
            |
            +--> PUBLISHED
            |
            +--> FAILED        (erreur non récupérable / intervention)
```

Signification :

- `RECEIVED` : SMS brut durablement stocké ;
- `INVALID` : message archivé mais non publiable ;
- `VALIDATED` : protocole et identité acceptés ;
- `PENDING_MQTT` : publication persistée dans l'outbox ;
- `PUBLISHED` : broker a confirmé la publication selon le QoS choisi ;
- `FAILED` : traitement impossible sans correction/intervention.

Une indisponibilité temporaire d'Internet ou MQTT ne doit pas faire passer immédiatement le message en `FAILED`.

## 7. Déduplication

### Règle

Ne jamais utiliser uniquement :

```text
index mémoire SIM
```

comme identifiant de message.

Cet index appartient au stockage du modem et peut être réutilisé ou changer après suppression/redémarrage.

### Clé logique

**CHOIX D'ARCHITECTURE DJUA_SMS**

La clé logique doit utiliser plusieurs éléments :

```text
device_id
+
sequence
+
timestamp RTC si disponible
+
uptime
+
empreinte canonique du message
```

Proposition :

```text
message_fingerprint =
SHA-256(
  device_id |
  sequence |
  rtc |
  uptime_ms |
  canonical_D1
)
```

Une contrainte d'unicité persistante sur cette empreinte empêche qu'un même message logique crée plusieurs entrées de télémétrie dans l'outbox.

### Déduplication du brut avant parsing

Un message peut être relu après un crash survenu entre :

```text
COMMIT SQLite
et
suppression modem
```

La gateway doit donc aussi pouvoir reconnaître une relecture brute, par exemple à partir de :

```text
sender_number
+
raw_body
+
métadonnées de réception disponibles
+
raw_hash
```

Le mécanisme exact sera testé lors de l'implémentation.

### Séquence seule insuffisante

La séquence D1 ne doit pas être considérée comme globalement unique tant que sa persistance et son comportement après reboot du futur émetteur n'ont pas été validés.

## 8. Messages hors ordre

Le réseau GSM peut retarder des SMS.

DJUA_SMS ne doit pas supposer :

```text
ordre d'arrivée = ordre de mesure
```

La séquence, le RTC et l'uptime servent au diagnostic et à la déduplication.

La gateway ne doit pas réécrire arbitrairement les timestamps pour forcer un ordre.

## 9. MQTT outbox

**CHOIX D'ARCHITECTURE DJUA_SMS**

La publication ne part jamais directement d'un objet transitoire uniquement en mémoire.

Ordre :

```text
message validé
-> payload MQTT construit
-> INSERT outbox
-> COMMIT
-> tentative publication
```

Si le broker est indisponible, l'entrée reste persistée.

Au redémarrage :

```text
SELECT publications non PUBLISHED
-> reprise des tentatives
```

## 10. QoS et garantie réelle

**CHOIX D'ARCHITECTURE DJUA_SMS**

QoS 1 est proposé pour la liaison gateway -> broker.

Il apporte une sémantique de livraison au moins une fois vers le broker.

Important :

```text
PUBACK
= broker a accepté la publication
```

Ce n'est pas :

```text
backend a persisté la télémétrie
```

### Fenêtre de duplication inévitable

Exemple :

```text
gateway publie
-> broker accepte
-> PC plante avant COMMIT PUBLISHED
-> gateway redémarre
-> message republié
```

Le broker/backend peut alors voir un doublon malgré la déduplication interne précédente.

Donc, sans identifiant idempotent reconnu par le backend ou protocole end-to-end supplémentaire :

```text
exactly-once end-to-end
n'est pas garanti
```

DJUA_SMS vise :

- non-perte locale ;
- déduplication interne ;
- livraison au moins une fois au broker.

Ne pas prétendre davantage avant validation end-to-end.

## 11. Retry MQTT

**CHOIX D'ARCHITECTURE DJUA_SMS**

Chaque entrée en attente doit conserver :

```text
attempt_count
last_error
next_attempt
```

Le retry utilise un backoff progressif.

Cette phase ne fixe pas arbitrairement :

- délai initial ;
- délai maximum ;
- nombre maximum d'essais.

Ces valeurs seront choisies pendant l'implémentation en fonction du contexte réel du poste récepteur.

Une coupure Internet prolongée ne doit pas faire supprimer l'entrée.

## 12. Reprise après panne

### PC redémarre

Les SMS déjà en SQLite sont relus selon leur état.

Les entrées `PENDING_MQTT` sont reprises.

### Application plante après COMMIT brut mais avant suppression modem

Le SMS peut encore être présent dans le modem.

À la relance, sa relecture est détectée comme doublon brut/logique.

### Application plante après suppression modem mais avant parsing

Le SMS brut est déjà dans SQLite : le traitement reprend depuis la copie locale.

### MQTT indisponible

Les messages restent en `PENDING_MQTT`.

### Internet disparaît

Même comportement que MQTT indisponible : aucune suppression de l'outbox.

### SIM800L redémarre

Les messages déjà commités localement restent disponibles.

Les messages uniquement présents dans le modem dépendent du comportement de sa mémoire SMS et doivent être validés matériellement.

### Port série disparaît

Le service MQTT/outbox peut continuer à vider les données déjà locales.

La partie modem passe en état de reconnexion sans faire tomber tout le service.

## 13. Messages invalides

Un SMS invalide doit être :

```text
archivé
marqué INVALID
journalisé
non publié MQTT
```

Une erreur sur un SMS ne doit pas arrêter le processus global.

Exemples :

- version inconnue ;
- nombre de champs incorrect ;
- device_id invalide ;
- numérique non parsable ;
- coordonnées hors plage structurelle ;
- incohérence entre flags et champs ;
- authentification incorrecte si activée.

Les valeurs métier inhabituelles mais syntaxiquement valides ne doivent pas être supprimées automatiquement. Une panne réelle pourrait produire une valeur anormale.

## 14. Sécurité

**CHOIX D'ARCHITECTURE DJUA_SMS**

Niveaux envisagés :

1. filtrage du numéro expéditeur ;
2. association numéro <-> `device_id` ;
3. validation de version/structure ;
4. HMAC-SHA-256 standard si une gestion sûre des clés est mise en place.

Ne pas inventer de cryptographie propriétaire.

Les secrets :

- ne sont jamais stockés dans Git ;
- ne sont jamais affichés dans les logs ;
- doivent être injectés par configuration locale sécurisée.

Le numéro expéditeur seul ne constitue pas une authentification cryptographique forte.

## 15. Journalisation

Les logs doivent pouvoir indiquer sans secret :

- modem disponible/indisponible ;
- SMS reçu ;
- identifiant local ;
- expéditeur éventuellement masqué ;
- device_id après parsing ;
- validation acceptée/refusée ;
- doublon détecté ;
- COMMIT effectué ;
- suppression modem réussie/échouée ;
- MQTT connecté/déconnecté ;
- tentative de publication ;
- PUBACK ;
- retry ;
- erreur série.

Le corps SMS brut peut contenir des informations opérationnelles. Sa présence dans les logs doit être contrôlée ; la copie diagnostique de référence reste SQLite.

## 16. Points à valider matériellement

**À VALIDER AVEC SIM800L RÉEL**

- mode de stockage SMS utilisé ;
- commandes `AT+CPMS` réellement supportées/configurées ;
- comportement `AT+CNMI` ;
- notification `+CMTI` ;
- lecture `AT+CMGR` ;
- suppression `AT+CMGD` ;
- persistence des SMS après redémarrage modem ;
- encodage réel reçu ;
- numéro expéditeur retourné ;
- timestamp fourni par le modem ;
- comportement lorsque plusieurs SMS arrivent rapidement ;
- comportement mémoire pleine ;
- reconnexion après disparition du port série.

## 17. Points à valider end-to-end

**À VALIDER END-TO-END**

- D1 réel -> parser ;
- flags -> normalisation exacte ;
- SQLite -> outbox ;
- QoS/PUBACK ;
- payload reçu par le broker ;
- acceptation par l'API DJUA ;
- absence de régression du contrat MQTT ;
- comportement des doublons après crash au moment critique publication/PUBACK.
