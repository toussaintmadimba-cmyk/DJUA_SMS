# AGENTS.md

## Périmètre

DJUA_SMS est une passerelle légère :

```text
SMS -> validation -> stockage -> MQTT
```

Elle n'est pas :

- un backend ;
- une IA ;
- un moteur de maintenance prédictive ;
- un remplacement de l'API DJUA.

Le transport cible du boîtier terrain est le SMS. DJUA_SMS reçoit ces SMS, les persiste, les valide, les déduplique, reconstruit le contrat MQTT DJUA existant et les publie vers le broker.

## Protection absolue de DJUA

```text
toussaintmadimba-cmyk/DJUA
= READ ONLY
```

Interdiction absolue de :

- modifier un fichier dans DJUA ;
- créer, supprimer, renommer ou déplacer un fichier dans DJUA ;
- créer une branche dans DJUA ;
- créer un commit ou pousser dans DJUA ;
- ouvrir une pull request contenant des modifications de DJUA ;
- corriger ou refactorer le firmware DJUA ;
- modifier le backend contenu dans DJUA ;
- modifier TelemetryData, config.h, les topics ou les transports du firmware.

DJUA peut uniquement être lu afin de comprendre le contrat actuel.

Si une évolution de DJUA paraît nécessaire :

```text
la documenter
mais ne pas l'implémenter
```

Toute implémentation du présent projet doit viser exclusivement :

```text
toussaintmadimba-cmyk/DJUA_SMS
```

Avant toute écriture GitHub, vérifier explicitement le dépôt cible. Si la cible est DJUA, arrêter l'opération.

## Règle de preuve

Toujours distinguer clairement :

- **CONFIRMÉ PAR DJUA** : observé dans le code de la branche main de DJUA ;
- **CHOIX D'ARCHITECTURE DJUA_SMS** : décision prise dans ce dépôt ;
- **HYPOTHÈSE** : choix ou comportement non encore vérifié ;
- **TESTÉ AUTOMATIQUEMENT** : couvert par un test logiciel exécuté ;
- **À VALIDER AVEC SIM800L RÉEL** : dépend du modem, de la SIM, du réseau ou du port série ;
- **À VALIDER END-TO-END** : nécessite toute la chaîne SMS -> gateway -> MQTT -> backend.

Ne jamais présenter un test simulé comme une validation matérielle.

## Discipline de modification

Avant une modification locale :

```bash
git status
git diff
```

Après modification :

```bash
git status
git diff --check
git diff
```

Règles supplémentaires :

- préférer les modifications petites et vérifiables ;
- ne pas effectuer de refactor global hors périmètre ;
- ne pas ajouter de dépendance sans justification ;
- ne pas mélanger commandes AT, parsing SMS, SQLite, normalisation MQTT et publication MQTT dans un même module ;
- ne jamais versionner de secret réel ;
- ne jamais inventer un comportement du SIM800L ;
- documenter les écarts entre code DJUA, documentation et hypothèses sans corriger DJUA.

## Phase actuelle

La phase actuelle est documentaire. Ne pas créer encore :

- driver SIM800L complet ;
- base SQLite fonctionnelle ;
- publisher MQTT complet ;
- service principal complet ;
- service Windows ;
- interface graphique ;
- Docker ;
- API web.

Les documents de référence de cette phase sont :

- `docs/architecture.md`
- `docs/sms_protocol.md`
- `docs/mqtt_contract.md`
- `docs/reliability.md`

Ne pas commencer automatiquement la phase d'implémentation suivante sans validation explicite.
