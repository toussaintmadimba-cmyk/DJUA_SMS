# Protocole SMS DJUA — D1

## 1. Statut

Ce document définit le protocole conceptuel de télémétrie SMS `D1` pour DJUA_SMS.

```text
D = DJUA telemetry
1 = version 1 du protocole
```

**CHOIX D'ARCHITECTURE DJUA_SMS**

Le protocole est conçu pour être :

- compact ;
- versionné ;
- simple à produire sur ESP32 ;
- simple à parser ;
- compatible avec le transport SMS ;
- multi-device ;
- identifiable immédiatement comme un message DJUA.

Le firmware DJUA n'est pas modifié dans cette phase.

## 2. Séparation transport / backend

`D1` est un protocole de transport.

Il n'est pas le contrat backend.

```text
SMS D1
  |
  v
objet interne DJUA_SMS
  |
  v
normalizer
  |
  v
payload MQTT DJUA existant
```

Des champs propres au transport peuvent exister dans D1 sans être publiés vers le backend :

- version ;
- séquence ;
- flags de validité ;
- tag d'authentification.

## 3. Encodage général

**CHOIX D'ARCHITECTURE DJUA_SMS**

Format retenu : CSV positionnel ASCII.

Règles :

- séparateur : virgule `,` ;
- aucun espace ;
- aucun guillemet ;
- aucun retour à la ligne ;
- pas d'accents ;
- décimales avec point `.` ;
- message sensible à la position des champs ;
- valeurs absentes représentées par `-` lorsque la validité correspondante est fausse ;
- version toujours en première position.

Objectif : rester dans l'alphabet simple compatible GSM-7 et éviter autant que possible les SMS concaténés.

## 4. Forme D1

```text
D1,<device_id>,<seq>,<rtc>,<tz_min>,<uptime36>,<interval>,
<lat>,<lon>,
<batt_v>,<batt_a>,<batt_w>,
<solar_v>,<solar_a>,<solar_w>,<solar_wh>,
<ac_v>,<ac_a>,<ac_w>,<ac_va>,<ac_wh>,
<flags>,<auth>
```

Le message réel ne contient aucun retour à la ligne.

## 5. Ordre des champs

| # | Champ | Type / encodage | Unité | Obligatoire | Règle structurelle | Mapping MQTT |
|---:|---|---|---|---|---|---|
| 1 | protocol | texte | — | oui | exactement `D1` | non publié |
| 2 | device_id | ASCII | — | oui | `[A-Z0-9-]{1,32}` | `kit_id` |
| 3 | seq | base36 majuscule | — | oui | compteur transport | non publié |
| 4 | rtc | `YYYYMMDDhhmmss` ou `-` | heure locale | oui | 14 chiffres si RTC valide | `timestamp` |
| 5 | tz_min | entier signé ou `-` | minutes UTC | oui | requis si RTC valide | `timezone` via normalisation |
| 6 | uptime36 | base36 majuscule | ms depuis boot | oui | entier uint32 encodé base36 | `timestamp_ms` |
| 7 | interval | entier décimal | s | oui | entier non négatif | `interval_seconds` |
| 8 | lat | décimal ou `-` | degrés | oui | -90..90 si GPS valide | `latitude` |
| 9 | lon | décimal ou `-` | degrés | oui | -180..180 si GPS valide | `longitude` |
| 10 | batt_v | décimal ou `-` | V | oui | nombre fini si batterie valide | `battery.voltage_v` |
| 11 | batt_a | décimal ou `-` | A | oui | nombre fini si batterie valide | `battery.current_a` |
| 12 | batt_w | décimal ou `-` | W | oui | nombre fini si batterie valide | `battery.power_w` |
| 13 | solar_v | décimal ou `-` | V | oui | nombre fini si solaire valide | `solar.voltage_v` |
| 14 | solar_a | décimal ou `-` | A | oui | nombre fini si solaire valide | `solar.current_a` |
| 15 | solar_w | décimal ou `-` | W | oui | nombre fini si solaire valide | `solar.power_w` |
| 16 | solar_wh | décimal ou `-` | Wh | oui | nombre fini si solaire valide | `solar.energy_interval_wh` |
| 17 | ac_v | décimal ou `-` | V RMS | oui | nombre fini si AC valide | `ac_load.voltage_v` |
| 18 | ac_a | décimal ou `-` | A RMS | oui | nombre fini si AC valide | `ac_load.current_a` |
| 19 | ac_w | décimal ou `-` | W actif | oui | nombre fini si AC valide | `ac_load.active_power_w` |
| 20 | ac_va | décimal ou `-` | VA | oui | nombre fini si AC valide | `ac_load.apparent_power_va` |
| 21 | ac_wh | décimal ou `-` | Wh | oui | nombre fini si AC valide | `ac_load.energy_interval_wh` |
| 22 | flags | hexadécimal | bits | oui | deux chiffres hex | non publié |
| 23 | auth | base64url ou `-` | — | oui | voir section sécurité | non publié |

## 6. Flags de validité

**CHOIX D'ARCHITECTURE DJUA_SMS**

Le champ `flags` contient au moins cinq bits :

| Bit | Masque | Signification si 1 |
|---:|---:|---|
| 0 | 0x01 | RTC valide |
| 1 | 0x02 | GPS valide |
| 2 | 0x04 | batterie valide |
| 3 | 0x08 | solaire valide |
| 4 | 0x10 | AC valide |

Avec toutes les mesures valides :

```text
flags = 1F
```

Les bits supérieurs sont réservés pour une évolution future de version. Ils ne doivent pas changer silencieusement la signification de D1.

## 7. Valeurs invalides et reconstruction du contrat actuel

**CONFIRMÉ PAR DJUA**

Le code actuel ne traite pas toutes les invalidités de la même manière dans le payload MQTT :

- RTC invalide : `timestamp` et `timezone` ne sont pas ajoutés au MQTT ;
- GPS invalide : latitude et longitude deviennent `0.0` ;
- batterie invalide : les champs publiés restent à `0.0` via l'initialisation de la télémétrie ;
- solaire invalide : les quatre champs solaires sont publiés à `null` ;
- AC invalide : les champs publiés restent à `0.0`.

D1 ne doit pas perdre l'information de validité. Le SMS peut donc utiliser `-` pour les valeurs indisponibles et laisser le normalizer reconstruire exactement la convention MQTT observée.

Exemple conceptuel avec GPS et solaire invalides :

```text
D1,DJUA-KIN-000001,9J0,20260927163500,60,21I6X0,1800,-,-,12.40,0.500,6.20,-,-,-,-,230.1,1.250,244.5,287.6,122.25,15,-
```

Le normalizer convertirait ensuite :

- GPS invalide -> `latitude: 0.0`, `longitude: 0.0` ;
- solaire invalide -> valeurs solaires `null`.

## 8. Séquence

**CHOIX D'ARCHITECTURE DJUA_SMS**

`seq` est un compteur de transport distinct du contrat backend.

Il est encodé en base36 afin de réduire la taille.

Exemple :

```text
12345 décimal -> 9IX en base36
```

Sa politique exacte de persistance côté futur firmware émetteur reste **À VALIDER**. DJUA_SMS ne doit pas supposer que la séquence est globalement unique à elle seule.

## 9. Uptime / timestamp_ms

**CONFIRMÉ PAR DJUA**

Le champ MQTT `timestamp_ms` actuel est produit avec `millis()` sur l'ESP32. Il ne s'agit pas d'un timestamp Unix.

D1 transporte donc cette valeur sous `uptime36` afin que la gateway puisse la décoder puis la recopier dans `timestamp_ms`.

Exemple :

```text
123456789 décimal -> 21I3V9 base36
```

## 10. RTC et timezone

**CONFIRMÉ PAR DJUA**

Lorsque le DS1302 est valide, le firmware actuel produit un timestamp ISO 8601 et publie également le label de timezone configuré.

**CHOIX D'ARCHITECTURE DJUA_SMS**

D1 transporte :

- la date locale compacte : `YYYYMMDDhhmmss` ;
- le décalage UTC en minutes : `tz_min`.

Exemple :

```text
20260927163000,60
```

devient :

```text
timestamp = 2026-09-27T16:30:00+01:00
timezone  = GMT+1
```

pour le contrat actuellement observé.

Si le RTC n'est pas valide :

```text
rtc = -
tz_min = -
flag RTC = 0
```

et le normalizer n'ajoute pas `timestamp` ni `timezone` au payload MQTT.

## 11. Authentification et intégrité

**CHOIX D'ARCHITECTURE DJUA_SMS**

Premier niveau envisagé :

1. numéro expéditeur autorisé ;
2. association numéro <-> `device_id` ;
3. HMAC standard lorsque la gestion des clés sera disponible.

Aucune cryptographie propriétaire ne doit être créée.

Proposition D1 pour `auth` :

- `-` tant que l'authentification cryptographique n'est pas activée ;
- sinon HMAC-SHA-256 sur les champs 1 à 22 joints par des virgules ;
- troncature à 8 octets ;
- encodage base64url sans padding, soit 11 caractères.

La troncature et la gestion des clés devront être validées avant activation en production.

Un CRC séparé n'est pas retenu dans D1 à ce stade : lorsqu'un HMAC est actif, il couvre déjà l'intégrité du message en plus de l'authenticité. Si le HMAC n'est pas activé, l'absence de CRC doit rester documentée plutôt que remplacée par une cryptographie maison.

Les secrets ne doivent jamais être versionnés dans Git.

## 12. Taille SMS

**CHOIX D'ARCHITECTURE DJUA_SMS**

Message représentatif :

```text
D1,DJUA-KIN-000001,9IX,20260927163000,60,21I3V9,1800,-4.325100,15.322200,12.40,0.500,6.20,18.20,1.230,22.39,11.20,230.1,1.250,244.5,287.6,122.25,1F,AbCdEf12345
```

Longueur : **159 caractères**.

Avec `auth=-`, le même exemple fait environ **149 caractères**.

Ces valeurs montrent que D1 peut tenir dans un SMS GSM-7 simple pour un cas nominal représentatif, mais elles ne prouvent pas que tous les cas possibles resteront sous 160 caractères.

Facteurs pouvant augmenter la taille :

- identifiant de boîtier plus long ;
- valeurs négatives ;
- nombres avec plus de chiffres ;
- précision décimale supérieure ;
- futures extensions.

**À VALIDER AVEC LE FUTUR ÉMETTEUR ET LE RÉSEAU GSM**

L'implémentation devra calculer la longueur réellement encodée et détecter un message dépassant la capacité d'un SMS simple au lieu de supposer qu'il tient toujours.

## 13. Précision numérique

D1 reste lisible et utilise des décimaux afin d'éviter une convention de mise à l'échelle implicite.

Précisions représentatives recommandées, à confirmer lors de l'implémentation émetteur :

- GPS : jusqu'à 6 décimales ;
- tension batterie/solaire : 2 décimales ;
- courant : jusqu'à 3 décimales ;
- tension AC : 1 décimale ;
- puissances et énergies : précision adaptée au calcul existant.

La gateway ne doit pas appliquer des seuils métier arbitraires à ces valeurs. Une valeur inhabituelle peut représenter une panne réelle.

## 14. Fréquence

Règle explicite :

```text
fréquence de mesure
!=
fréquence d'envoi SMS
```

Le firmware DJUA de référence mesure actuellement selon sa propre cadence réseau, mais cette cadence ne devient pas automatiquement une cadence SMS.

La politique d'envoi SMS sera décidée dans une tâche séparée. D1 ne fixe aucune fréquence.

## 15. Évolutions

Une modification incompatible de l'ordre, du sens ou de l'encodage des champs exige une nouvelle version de protocole.

D1 ne doit pas être étendu silencieusement.

Les événements geofence ne sont pas inclus dans D1 pendant cette phase.
