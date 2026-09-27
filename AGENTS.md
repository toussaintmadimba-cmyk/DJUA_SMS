# AGENTS.md

## Périmètre

DJUA_SMS est une passerelle légère :

```text
SMS -> validation -> stockage -> MQTT
```

Elle n'est pas un backend, une IA, un moteur de maintenance prédictive ni un remplacement de l'API DJUA.

## Protection absolue de DJUA

```text
toussaintmadimba-cmyk/DJUA
= READ ONLY
```

Interdiction absolue de modifier, créer, supprimer, renommer ou déplacer un fichier dans DJUA, de créer une branche/commit/push/PR dans DJUA, de corriger le firmware, le backend, `TelemetryData`, `config.h` ou les topics.

DJUA peut uniquement être lu comme source de référence.

Si une évolution paraît nécessaire :

```text
la documenter
mais ne pas l'implémenter
```

Toute écriture du présent projet doit viser exclusivement :

```text
toussaintmadimba-cmyk/DJUA_SMS
```

## Règle de preuve

Toujours distinguer :

- **CONFIRMÉ PAR DJUA**
- **CHOIX D'ARCHITECTURE DJUA_SMS**
- **HYPOTHÈSE**
- **TESTÉ AUTOMATIQUEMENT**
- **À VALIDER AVEC SIM800L RÉEL**
- **À VALIDER END-TO-END**

Ne jamais présenter un test simulé comme une validation matérielle.

## Discipline

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

Si l'intégration GitHub ne permet pas ces commandes littéralement, utiliser l'équivalent disponible et le signaler.

Règles :

- modifications petites et vérifiables ;
- pas de refactor global hors périmètre ;
- pas de dépendance sans justification ;
- pas de secret réel dans Git ;
- ne pas mélanger commandes AT, protocole, SQLite, normalisation et publication MQTT ;
- ne pas inventer le comportement du SIM800L.

## État stable actuel

**TESTÉ AUTOMATIQUEMENT**

Sont maintenant implémentés dans DJUA_SMS :

- noyau protocolaire D1 ;
- SQLite `sqlite3` ;
- `inbound_sms` ;
- `mqtt_outbox` ;
- déduplication brute et logique SHA-256 ;
- `SmsIngestionService` synchrone ;
- reprise des outbox `PENDING` après redémarrage ;
- API de marquage `PUBLISHED` ;
- API d'enregistrement des échecs futurs de publication.

La suite complète compte actuellement :

```text
96 PASS
0 FAIL
0 SKIP
```

## Arrêt de phase

Ne pas commencer automatiquement :

- SIM800L ;
- pyserial ;
- commandes AT ;
- paho-mqtt ;
- connexion broker ;
- publication MQTT réelle ;
- daemon/service Windows ;
- Docker.

Attendre une autorisation explicite pour la phase suivante.
