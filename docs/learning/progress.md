# Progression d'apprentissage — DJUA_SMS

## Point de départ

Initialisation pédagogique réalisée sur l'état réel du dépôt :

```text
HEAD analysé : 99494fd0455b09cadbda9a0372551ebae97e859f
Tests CI     : 177 PASS / 0 FAIL / 0 SKIP
```

Cette première passe sert à reconstruire la compréhension d'un projet déjà largement développé avec assistance IA.

Aucun concept n'est marqué `COMPRIS` à ce stade. Le fait qu'un concept soit présent dans le code ou qu'il ait déjà été expliqué ne prouve pas qu'il est maîtrisé.

Statuts utilisés :

```text
À VÉRIFIER   : présent dans le projet, compréhension à évaluer
À APPRENDRE  : nécessaire mais probablement à travailler explicitement
COMPRIS      : seulement après démonstration de compréhension
À REVOIR     : déjà travaillé mais encore fragile
```

## Ce que fait actuellement le projet

DJUA_SMS est une passerelle de télémétrie.

Son flux principal est :

```text
SIM800L
→ port série
→ commandes AT
→ lecture SMS
→ stockage durable SQLite
→ parsing / validation D1
→ normalisation
→ MQTT outbox
→ publication MQTT QoS 1
→ broker
→ backend DJUA externe
```

Il n'y a pas de frontend web dans ce dépôt et le backend métier DJUA n'y est pas implémenté.

## Carte pédagogique

### Indispensables maintenant

| Concept | Statut initial | Pourquoi il est prioritaire |
| --- | --- | --- |
| Parcours complet d'une donnée | À VÉRIFIER | Permet de savoir où regarder lorsqu'un SMS n'arrive pas au backend |
| Séparation des responsabilités | À VÉRIFIER | Le projet est volontairement découpé entre GSM, protocole, stockage, services et MQTT |
| Persistance durable et transaction SQLite | À VÉRIFIER | Condition essentielle avant la suppression du SMS du modem |
| Protocole D1 : parser, validator, normalizer | À VÉRIFIER | Transforme le SMS brut en télémétrie exploitable |
| Déduplication et idempotence | À VÉRIFIER | Empêche qu'un même SMS ou message logique produise plusieurs publications |
| Outbox persistante | À VÉRIFIER | Découple la réception SMS de la disponibilité d'Internet/MQTT |

### Importants prochainement

| Concept | Statut initial | Pourquoi il sera bientôt nécessaire |
| --- | --- | --- |
| Commandes AT et URC | À VÉRIFIER | Nécessaire pour diagnostiquer le SIM800L et les notifications +CMTI |
| Port série / pyserial | À VÉRIFIER | Interface physique entre la machine réceptrice et le modem |
| MQTT : topic, QoS 1, PUBACK | À VÉRIFIER | Permet de comprendre quand une outbox devient réellement PUBLISHED |
| Retry / backoff / recovery | À VÉRIFIER | Permet de comprendre le comportement pendant les pannes |
| Configuration par variables d'environnement | À VÉRIFIER | Nécessaire pour lancer le système sur une vraie machine |
| Tests unitaires, intégration, fakes et CI | À VÉRIFIER | Permet de distinguer validation logicielle et validation matérielle |

### Avancés

| Concept | Statut initial | Pourquoi il peut attendre |
| --- | --- | --- |
| Concurrence Paho, callbacks et verrous | À APPRENDRE | Utilisé pour associer les PUBACK aux publications sans course |
| Garantie at-least-once | À VÉRIFIER | Important pour comprendre les doublons possibles autour d'un crash |
| Schéma SQLite versionné et futures migrations | À APPRENDRE | Le schéma actuel est simple et en version 1 |
| Sécurité transport : TLS, credentials MQTT | À VÉRIFIER | Présente mais configurable et non au cœur du premier parcours |
| Authentification future D1 / sender | À APPRENDRE | Le champ auth existe mais n'est pas vérifié |
| Limite SMS 160 caractères / concaténation | À APPRENDRE | Problème réel documenté, mais pas traité par cette phase |

### Non prioritaires pour l'instant

| Sujet | Statut | Raison |
| --- | --- | --- |
| Frontend web | Non prioritaire | Aucun frontend n'existe dans DJUA_SMS |
| Framework web Flask/Django/FastAPI | Non prioritaire | Aucun de ces frameworks n'est utilisé ici |
| Docker | Non prioritaire | Explicitement hors périmètre actuel |
| Service Windows/systemd | Non prioritaire | Pas encore implémenté |
| Firmware émetteur ESP32 | Non prioritaire | Le dépôt DJUA reste READ ONLY |
| IA / maintenance prédictive | Non prioritaire | Hors mission de la gateway |
| Backend métier DJUA interne | Non prioritaire ici | Il est externe à ce dépôt ; DJUA_SMS lui parle via MQTT |

## Fichiers/composants à comprendre en premier

Ordre conseillé :

1. `src/djua_sms_gateway/services/gateway.py` — vue d'orchestration.
2. `src/djua_sms_gateway/gsm/sms_receiver.py` — frontière critique entre SMS et persistance.
3. `src/djua_sms_gateway/services/ingestion.py` — pipeline central SMS brut → outbox.
4. `src/djua_sms_gateway/storage/repository.py` — persistance, déduplication et états.
5. `src/djua_sms_gateway/storage/database.py` — schéma SQLite et transactions.
6. `src/djua_sms_gateway/protocol/parser.py` + `validator.py` + `normalizer.py` — transformation D1.
7. `src/djua_sms_gateway/services/outbox_worker.py` — sélection des publications PENDING.
8. `src/djua_sms_gateway/mqtt/publisher.py` — PUBACK, retry et passage à PUBLISHED.
9. `src/djua_sms_gateway/gsm/modem.py` — opérations SIM800L de haut niveau.
10. `src/djua_sms_gateway/config.py` — paramètres nécessaires au lancement réel.

Le but n'est pas de mémoriser ces fichiers, mais de savoir quel composant porte quelle responsabilité.

## Parcours d'une donnée réelle

### Réception normale

```text
1. Le SIM800L reçoit un SMS.
2. Le modem signale +CMTI.
3. AtProtocol conserve l'URC.
4. Sim800Modem lit le SMS avec CMGR.
5. SmsReceiver construit un RawSmsInput.
6. SmsIngestionService demande d'abord la persistance du SMS brut.
7. SmsRepository crée inbound_sms dans SQLite.
8. Le body est parsé comme D1.
9. Le validator vérifie la cohérence.
10. Le normalizer produit le payload du contrat MQTT.
11. SmsRepository crée mqtt_outbox = PENDING.
12. SmsReceiver sait maintenant que le SMS est durable et autorise CMGD.
13. MqttOutboxWorker récupère plus tard l'outbox PENDING.
14. MqttPublisher publie le topic/payload.
15. Le broker renvoie un PUBACK.
16. SmsRepository marque l'outbox et inbound_sms PUBLISHED.
```

### Si Internet/MQTT est indisponible

```text
SMS
→ SQLite
→ CMGD autorisé
→ mqtt_outbox reste PENDING
→ retry plus tard
```

### Si l'application plante avant CMGD

```text
SMS déjà en SQLite
→ SMS encore dans le modem
→ relecture après redémarrage
→ DUPLICATE_RAW
→ aucune seconde outbox
→ CMGD peut être retenté
```

## Zones fragiles ou encore non validées

Ces éléments ne sont pas des bugs automatiquement ; ce sont des zones à connaître avant la suite :

- le SIM800L physique et un vrai SMS ne sont toujours pas validés par les tests automatisés ;
- le comportement réel de CNMI, CPMS, CMGR et CMGL dépend encore du module physique ;
- le champ D1 `auth` est seulement contrôlé syntaxiquement : `AUTH_NOT_VERIFIED` ;
- aucune liaison de confiance `sender ↔ device_id` n'est implémentée ;
- le projet garantit une publication MQTT `at least once`, pas `exactly once` ;
- un crash après acceptation par le broker mais avant le commit SQLite peut provoquer une republication ;
- le problème des D1 dépassant la taille d'un SMS simple et les SMS concaténés n'est pas résolu ;
- il existe des scripts de diagnostic, mais pas encore de point d'entrée de production unique qui assemble toute la gateway depuis la configuration ;
- il n'existe pas encore de service Windows, unité systemd ou conteneur Docker ;
- la configuration lit directement `os.environ` : `.env.example` est un modèle, mais aucun chargeur `.env` n'est installé ;
- le schéma SQLite est versionné `1`, mais aucun mécanisme de migration au-delà de cette première version n'est encore implémenté ;
- le timezone D1/MQTT est actuellement couplé au contrat GMT+1.

## Premier checkpoint

Répondre sans chercher à réciter du code.

1. Pourquoi DJUA_SMS doit-il enregistrer le SMS dans SQLite avant d'envoyer `AT+CMGD` au modem ?
2. Quelle différence fais-tu entre le rôle de `gsm/sms_receiver.py` et celui de `services/ingestion.py` ?
3. Que devient une télémétrie valide si le broker MQTT est coupé pendant une heure ?
4. Pourquoi le projet possède-t-il à la fois une déduplication brute et une déduplication logique ?
5. Après un `PUBACK`, quel composant doit encore agir pour que le message soit considéré `PUBLISHED` de façon durable ?

Après ce checkpoint, les statuts ci-dessus pourront être mis à jour selon les réponses réellement données.
