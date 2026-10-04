# AGENTS.md

## 1. Mission du projet

`DJUA_SMS` est une passerelle légère de télémétrie.

Flux principal :

```text
SIM800L / SMS
      ↓
lecture SMS
      ↓
persistance durable SQLite
      ↓
dispatch D1 / D2T / D2E
      ↓
parsing / validation / sécurité
      ↓
normalisation
      ↓
MQTT outbox persistante
      ↓
publication MQTT
```

`DJUA_SMS` n'est pas :

- le firmware principal DJUA ;
- le backend DJUA ;
- une IA ;
- un moteur de maintenance prédictive ;
- un système d'analyse énergétique métier.

Le projet doit rester focalisé sur la réception fiable des SMS, leur persistance, leur transformation selon le protocole D1 et leur transmission MQTT.


## SOURCE DE VÉRITÉ D2

Le wire protocol D2 est défini par :

```text
docs/sms_protocol_v2.md
tests/vectors/d2_conformance.json
```

D1 reste historique. Toute correction du contrat D2 doit aligner explicitement spécification, vecteurs, code et tests.

Le récepteur réel est un SIM868 ; préserver le pilote historique SIM800 compatible au lieu de le réécrire uniquement pour son nom.

---

# 2. PROTECTION ABSOLUE DE DJUA

Le dépôt :

```text
toussaintmadimba-cmyk/DJUA
```

est strictement :

```text
READ ONLY
```

Il est interdit de :

- créer ;
- modifier ;
- supprimer ;
- déplacer ;
- renommer ;
- committer ;
- pousser ;
- ouvrir une PR contenant des modifications

dans `DJUA`.

`DJUA` peut uniquement être consulté comme source de référence.

Toute écriture liée à cette passerelle doit viser :

```text
toussaintmadimba-cmyk/DJUA_SMS
```

Si une évolution du firmware DJUA semble nécessaire :

1. identifier le besoin ;
2. l'expliquer ;
3. le documenter ;
4. ne pas l'implémenter dans `DJUA`.

Aucune exception implicite à cette règle.

---

# 3. RÈGLE DE PREUVE

Toujours distinguer explicitement :

- **CONFIRMÉ PAR DJUA**
- **CHOIX D'ARCHITECTURE DJUA_SMS**
- **TESTÉ AUTOMATIQUEMENT**
- **VÉRIFIÉ PAR INSPECTION**
- **À VALIDER AVEC SIM800L RÉEL**
- **À VALIDER AVEC SMS RÉEL**
- **À VALIDER END-TO-END**

Ne jamais présenter une hypothèse comme un fait confirmé.

Ne jamais appeler :

- un mock ;
- un FakeSerial ;
- un test unitaire ;
- un port série simulé

un test matériel réel.

Ne jamais prétendre qu'un test est passé s'il n'a pas réellement été exécuté.

---

# 4. RÈGLE CRITIQUE DE NON-PERTE SMS

Le principe fondamental est :

```text
CMGR
 ↓
SmsIngestionService
 ↓
SQLite COMMIT durable
 ↓
CMGD=<index> autorisé
```

Un SMS ne doit jamais être supprimé du modem avant que sa copie brute soit durablement enregistrée.

Si l'ingestion échoue :

```text
CMGD INTERDIT
```

Un SMS classé :

```text
INVALID
```

ou :

```text
DUPLICATE_RAW
```

peut être supprimé du modem uniquement si sa copie brute est déjà durablement enregistrée dans SQLite.

Ne jamais utiliser :

```text
AT+CMGD=1,4
```

dans le fonctionnement normal de la passerelle.

Toute modification touchant :

- `CMGR` ;
- `CMGL` ;
- `CMGD` ;
- la persistance ;
- la déduplication ;
- la récupération au démarrage

doit être considérée comme sensible à la perte de données.

---

# 5. SÉPARATION DES RESPONSABILITÉS

Respecter les responsabilités existantes.

```text
gsm/serial_transport.py
```

Responsable du port série et du transport d'octets.

```text
gsm/at_protocol.py
```

Responsable des commandes AT, réponses terminales et URC.

```text
gsm/modem.py
```

Responsable des opérations de haut niveau sur le SIM800L.

```text
gsm/sms_receiver.py
```

Responsable du flux :

```text
CMGR
→ ingestion
→ décision
→ CMGD
```

```text
services/ingestion.py
```

Responsable de :

- persistance ;
- dispatch D1/D2T/D2E ;
- parsing/validation D1 ;
- parsing/validation/sécurité D2 ;
- normalisation ;
- déduplication ;
- création de l'outbox.

```text
mqtt/
```

Responsable du transport MQTT.

```text
services/gateway.py
```

Responsable de l'orchestration générale.

Ne pas déplacer la logique métier D1 dans les couches GSM.

Ne pas mélanger inutilement :

```text
transport
protocole
persistance
logique métier
orchestration
```

---

# 6. BASE STABLE ACTUELLE

À la date correspondant à cet état de référence, sont considérés comme implémentés et testés automatiquement :

- parser D1 ;
- validator D1 ;
- normalizer D1 ;
- SQLite ;
- déduplication ;
- MQTT outbox persistante ;
- MQTT QoS 1 ;
- gestion PUBACK ;
- retry MQTT ;
- pyserial ;
- protocole AT ;
- initialisation SIM800L ;
- `CMTI` ;
- `CMGR` ;
- `CMGL` ;
- `CMGD` ;
- persistance avant suppression ;
- startup recovery ;
- reconnexion série ;
- gateway orchestrator.

État de référence :

```text
208 PASS (CI après intégration D2, avant documentation finale)
0 FAIL
0 SKIP
```

Ce nombre n'est pas une vérité permanente.

Après toute modification, utiliser le résultat réellement obtenu par les tests exécutés.

---

# 7. ÉTAT MATÉRIEL

État de référence :

```text
SIM868 RÉCEPTEUR : MATÉRIEL CONFIRMÉ PAR LE PROJET
AT/SMS PILOTE HISTORIQUE : A DÉJÀ FONCTIONNÉ AVEC SIM868
D2 SMS RÉEL : NON VALIDÉ DANS CETTE PHASE
```

Ne jamais inventer un résultat matériel.

Un test utilisant :

```text
FakeSerial
mock
fixture
simulation
```

reste un test logiciel.

Lorsque le matériel sera réellement testé, distinguer clairement :

```text
test logiciel
test série réel
test SIM800L réel
test SMS réel
test end-to-end
```

---

# 8. LIMITES DE PHASE

Ne pas commencer automatiquement :

- modification du firmware `DJUA` ;
- développement de l'émetteur SMS ESP32 ;
- modification du protocole D1 ;
- service Windows ;
- Docker ;
- changement majeur d'architecture ;
- nouvelle infrastructure non demandée.

Ces travaux nécessitent une demande explicite.

Ne pas interpréter :

> « continue »

comme une autorisation générale d'ouvrir de nouvelles phases sans rapport avec l'objectif courant.

---

# 9. PRIORITÉ DE DÉVELOPPEMENT

Quand une tâche est demandée :

1. comprendre l'état réel du dépôt ;
2. inspecter le code concerné ;
3. respecter les invariants existants ;
4. réaliser la modification demandée ;
5. exécuter les tests pertinents ;
6. vérifier les régressions évidentes ;
7. expliquer brièvement le résultat ;
8. mettre en évidence les concepts importants lorsque cela aide l'apprentissage.

Le projet reste prioritaire.

L'apprentissage doit accompagner le développement, pas le remplacer.

---

# 10. NE PAS SUR-ARCHITECTURER

Avant d'ajouter :

- une abstraction ;
- une couche ;
- une dépendance ;
- un framework ;
- un service ;
- un nouveau pattern architectural

vérifier que cela répond à un besoin réel.

Éviter :

- duplication évitable ;
- abstraction prématurée ;
- refactorisation sans rapport ;
- dépendances inutiles ;
- architecture plus complexe que le problème ;
- réécriture massive d'un composant stable sans justification.

Respecter autant que possible les interfaces existantes.

---

# 11. AVANT UNE MODIFICATION IMPORTANTE

Pour une tâche non triviale, déterminer brièvement :

- le besoin ;
- le flux concerné ;
- les composants concernés ;
- les fichiers probablement concernés ;
- les invariants à préserver ;
- les risques.

Exemple :

```text
SMS reçu
→ gsm/sms_receiver.py
→ services/ingestion.py
→ SQLite
→ outbox
→ mqtt/
```

Ne pas produire une longue dissertation avant chaque modification.

---

# 12. MODE FICHIERS ENTIERS

Il est acceptable de créer ou modifier des fichiers entiers lorsque cela est techniquement justifié.

Ne pas limiter artificiellement les changements pour des raisons pédagogiques.

Cependant :

- éviter les réécritures inutiles ;
- préserver les comportements hors périmètre ;
- ne pas effacer des modifications utilisateur non liées ;
- signaler les changements structurels importants ;
- minimiser le rayon d'impact.

L'objectif n'est pas que l'utilisateur écrive manuellement chaque ligne.

L'objectif est qu'il comprenne progressivement le système qu'il pilote.

---

# 13. DIAGNOSTIC AVANT CORRECTION

Lorsqu'une erreur apparaît :

1. observer le symptôme ;
2. lire les logs ;
3. identifier la couche concernée ;
4. reproduire lorsque c'est raisonnable ;
5. suivre le flux d'exécution ;
6. formuler une hypothèse ;
7. vérifier cette hypothèse ;
8. identifier la cause ;
9. corriger ;
10. tester ;
11. vérifier les régressions pertinentes.

Éviter :

```text
erreur
→ modifications aléatoires
→ nouveaux bugs
→ nouvelle modification aléatoire
```

Lorsque pertinent, résumer :

```text
Symptôme
→ Cause
→ Correction
→ Vérification
```

---

# 14. TESTS

Une modification n'est pas considérée comme validée simplement parce que le code paraît correct.

Lorsque possible :

- utiliser les tests existants ;
- ajouter des tests pour les nouveaux comportements ;
- ajouter un test de régression lorsqu'un bug réel est corrigé ;
- exécuter les tests pertinents ;
- exécuter une suite plus large lorsque le changement peut avoir des effets transversaux.

Toujours distinguer :

```text
TESTÉ AUTOMATIQUEMENT
VÉRIFIÉ MANUELLEMENT
NON TESTÉ
À VALIDER SUR MATÉRIEL
```

Ne pas réduire la couverture ou supprimer des tests uniquement pour obtenir du vert.

---

# 15. GIT

Avant des changements importants :

- inspecter `git status` ;
- identifier les modifications existantes ;
- ne pas écraser des changements sans rapport.

Après la tâche, indiquer lorsque pertinent :

- fichiers importants modifiés ;
- comportements modifiés ;
- tests exécutés ;
- résultat des tests ;
- risques ou éléments restant à valider.

Ne pas automatiquement :

- `push` ;
- merger ;
- rebaser ;
- reset destructif ;
- supprimer une branche ;
- réécrire l'historique.

Une action Git distante ou destructive nécessite une instruction appropriée.

---

# 16. SÉCURITÉ ET ROBUSTESSE

Traiter avec attention particulière :

- numéros de téléphone ;
- identifiants matériels ;
- credentials MQTT ;
- mots de passe ;
- clés API ;
- secrets ;
- ports série ;
- commandes AT ;
- fichiers de configuration ;
- données reçues par SMS ;
- données venant du réseau.

Ne jamais :

- committer volontairement des secrets ;
- désactiver une validation pour faire passer un test ;
- faire confiance aveuglément aux données reçues ;
- exécuter du contenu provenant d'un SMS comme une commande système.

---

# 17. MODE APPRENTISSAGE

L'utilisateur développe principalement avec assistance IA.

Il n'est pas nécessaire qu'il écrive manuellement tout le code.

L'objectif est qu'il devienne progressivement capable de :

- comprendre l'architecture ;
- comprendre les responsabilités des modules ;
- suivre le parcours d'une donnée ;
- lire un diff important ;
- comprendre une erreur ;
- reconnaître les couches concernées ;
- comprendre les tests ;
- prendre les décisions techniques importantes ;
- détecter une proposition incohérente de l'IA.

Ne pas transformer automatiquement chaque tâche en cours.

---

# 18. CE QU'IL FAUT EXPLIQUER

Après une tâche significative, privilégier :

1. architecture concernée ;
2. responsabilités ;
3. flux ;
4. interfaces entre modules ;
5. concepts essentiels.

Ne pas expliquer chaque ligne par défaut.

Descendre au niveau d'une fonction ou d'une ligne uniquement si :

- l'utilisateur le demande ;
- elle provoque un bug ;
- elle représente un mécanisme important ;
- elle présente un risque.

---

# 19. CONCEPTS À APPRENDRE

Après une tâche significative, identifier au maximum :

```text
1 à 3 concepts
```

réellement importants.

Priorité aux concepts :

- nouveaux ;
- directement rencontrés ;
- récurrents ;
- nécessaires pour comprendre le système ;
- nécessaires pour diagnostiquer de futurs problèmes.

Pour DJUA_SMS, cela peut inclure par exemple :

- UART ;
- port série ;
- commande AT ;
- URC ;
- SMS PDU / texte ;
- persistance ;
- transaction ;
- SQLite ;
- déduplication ;
- idempotence ;
- outbox pattern ;
- MQTT ;
- QoS ;
- PUBACK ;
- retry ;
- orchestration ;
- séparation des responsabilités.

Toujours expliquer le concept dans le contexte réel du projet.

Exemple préférable :

> Ici, l'outbox permet de conserver en SQLite un message qui doit encore être publié sur MQTT. Si le broker est indisponible, le message n'est pas perdu.

Éviter les définitions purement académiques lorsqu'un exemple du projet suffit.

---

# 20. MÉMOIRE D'APPRENTISSAGE

Le projet peut utiliser :

```text
docs/learning/progress.md
docs/learning/concepts.md
```

## `progress.md`

Permet de suivre :

```text
Concepts compris
Concepts en apprentissage
Nouveaux concepts
Concepts à revoir
```

Ne jamais considérer un concept comme maîtrisé uniquement parce qu'il a été expliqué une fois.

## `concepts.md`

Ne documenter que les concepts réellement utiles au projet.

Format recommandé :

```markdown
## Nom du concept

**Rencontré dans :**
...

**Pourquoi il existe ici :**
...

**À retenir :**
...

**Exemple DJUA_SMS :**
...
```

Ne pas transformer ce fichier en encyclopédie générale.

---

# 21. RATTRAPAGE D'UN PROJET DÉJÀ AVANCÉ

Lorsque l'utilisateur demande :

```text
rattrapage apprentissage initial
```

considérer qu'il s'agit d'une initialisation pédagogique complète d'un projet déjà largement développé avant la mise en place du système d'apprentissage.

Pendant cette phase :

- ne modifier aucun code fonctionnel ;
- ne refactoriser aucun composant ;
- ne corriger aucun bug découvert ;
- ne changer aucune architecture ;
- ne démarrer aucune nouvelle fonctionnalité.

Les seuls fichiers pouvant être créés ou modifiés sont les fichiers de documentation et d'apprentissage nécessaires.

## Analyse du projet

Reconstruire l'état réel du dépôt.

Identifier :

1. l'objectif actuel du projet ;
2. l'architecture générale ;
3. les technologies, frameworks, bibliothèques et services importants ;
4. le rôle des principaux dossiers ;
5. les fichiers et composants réellement structurants ;
6. les principaux flux de données ;
7. les communications entre composants ;
8. les mécanismes de sécurité présents ;
9. la stratégie de stockage ;
10. les modèles de données importants ;
11. les tests existants et ce qu'ils couvrent ;
12. la configuration et le processus de lancement ;
13. le processus de déploiement lorsqu'il existe ;
14. les zones importantes incomplètes, fragiles, obsolètes ou difficiles à comprendre.

Pour DJUA_SMS, analyser notamment les flux :

```text
SIM800L
→ commandes AT
→ réception SMS
→ persistance
→ parsing / validation D1
→ normalisation
→ outbox
→ MQTT
```

et :

```text
indisponibilité / redémarrage
→ persistance
→ recovery
→ retry
→ publication
```

## Carte pédagogique

Classer les concepts rencontrés en :

```text
INDISPENSABLES MAINTENANT
IMPORTANTS PROCHAINEMENT
AVANCÉS
NON PRIORITAIRES POUR L'INSTANT
```

Ne jamais considérer qu'un concept est maîtrisé simplement parce qu'il apparaît dans le code.

Un concept découvert pendant l'analyse doit initialement être considéré comme :

```text
À VÉRIFIER
```

ou :

```text
À APPRENDRE
```

tant que la compréhension de l'utilisateur n'a pas été évaluée.

## Initialisation de l'apprentissage

Créer si nécessaire :

```text
docs/learning/progress.md
docs/learning/concepts.md
```

Dans `progress.md`, établir le point de départ pédagogique.

Ne marquer aucun concept comme compris sans preuve suffisante de compréhension de l'utilisateur.

Dans `concepts.md`, documenter uniquement les concepts structurants réellement présents dans le projet.

Utiliser des exemples provenant du code réel.

## Rapport initial

À la fin du rattrapage, présenter :

1. une carte simple de l'architecture ;
2. les 5 à 10 fichiers ou composants à comprendre en premier ;
3. les 5 concepts prioritaires ;
4. le parcours complet d'une donnée réelle dans le système ;
5. les parties pouvant être ignorées temporairement ;
6. les zones fragiles ou encore non validées ;
7. cinq questions permettant d'évaluer le niveau réel de compréhension de l'utilisateur.

Les questions doivent tester principalement le raisonnement et la compréhension du système, pas la mémorisation de syntaxe.

Après les réponses de l'utilisateur :

- corriger les incompréhensions ;
- identifier les concepts compris ;
- identifier les concepts fragiles ;
- identifier les concepts inconnus ;
- mettre à jour `docs/learning/progress.md`.

Cette phase constitue le point de départ du suivi pédagogique du projet.

# 22. CHECKPOINT D'APPRENTISSAGE

Lorsque l'utilisateur écrit :

```text
checkpoint apprentissage
```

utiliser :

- le code réel ;
- `docs/learning/progress.md` ;
- `docs/learning/concepts.md` ;
- les fonctionnalités déjà réalisées.

Poser au maximum 5 questions.

Favoriser les questions de compréhension.

Exemples :

```text
Pourquoi le SMS doit-il être enregistré avant CMGD ?
```

```text
Quel est le rôle de services/ingestion.py par rapport à gsm/sms_receiver.py ?
```

```text
Que devient un message MQTT lorsque le broker est momentanément indisponible ?
```

```text
Pourquoi FakeSerial ne constitue-t-il pas une validation SIM800L réelle ?
```

Après les réponses :

- identifier ce qui est compris ;
- corriger les incompréhensions ;
- expliquer autrement si nécessaire ;
- mettre à jour la progression si approprié.

---

# 23. MODE « ANALYSE AVANT DE CODER »

Lorsque l'utilisateur demande explicitement :

```text
analyse avant de coder
```

ne modifier aucun fichier fonctionnel.

Retourner :

- compréhension du problème ;
- état actuel ;
- flux concerné ;
- fichiers concernés ;
- cause probable si bug ;
- solution proposée ;
- risques ;
- tests à prévoir ;
- concepts importants.

Attendre ensuite une instruction d'implémentation.

---

# 24. MODE AUTONOME

Lorsque l'utilisateur demande explicitement une exécution autonome :

1. analyser ;
2. implémenter ;
3. tester ;
4. corriger les problèmes directement liés ;
5. terminer la tâche autant que raisonnablement possible.

Ne pas interrompre le travail pour des décisions triviales.

Ne pas étendre automatiquement le périmètre à une autre phase du projet.

Les restrictions :

```text
DJUA READ ONLY
```

et :

```text
LIMITES DE PHASE
```

restent absolues même en mode autonome.

---

# 25. NIVEAU D'EXPLICATION

Utiliser le vocabulaire technique réel.

Expliquer immédiatement les termes importants lorsque nécessaire.

Exemple :

> `CMTI` est une URC, c'est-à-dire un message spontané envoyé par le modem pour signaler ici qu'un nouveau SMS est disponible.

Ne pas infantiliser.

Ne pas supposer non plus que le vocabulaire est déjà connu.

---

# 26. FORMAT DE FIN DE TÂCHE

Pour une tâche significative, utiliser de préférence :

## Résultat

Ce qui a été réellement réalisé.

## Fonctionnement

Le flux ou mécanisme concerné, si utile.

## Modifications importantes

Les composants ou fichiers importants touchés.

## Vérification

Tests réellement exécutés et résultats.

Distinguer matériel et simulation.

## À comprendre

Maximum 1 à 3 concepts importants.

## Attention

Risques, limites ou validations restant à effectuer.

Pour une petite modification évidente, répondre beaucoup plus brièvement.

---

# 27. ORDRE DE PRIORITÉ DES RÈGLES

En cas de tension entre plusieurs objectifs, respecter cet ordre :

```text
1. Ne jamais modifier DJUA
2. Ne jamais provoquer de perte SMS
3. Ne jamais falsifier un niveau de validation
4. Préserver les invariants et le protocole D1
5. Maintenir la fiabilité de la passerelle
6. Respecter le périmètre demandé
7. Maintenir la qualité du code
8. Faire progresser les tests
9. Favoriser l'apprentissage de l'utilisateur
```

La pédagogie ne doit jamais entraîner une violation d'une règle technique ou de sécurité.

---

# 28. PRINCIPE FINAL

Le cycle normal est :

```text
Besoin
  ↓
Compréhension du flux
  ↓
Inspection du code existant
  ↓
Modification ciblée
  ↓
Tests
  ↓
Vérification des invariants
  ↓
Résumé du changement
  ↓
1 à 3 concepts importants
  ↓
Progression
```

Le développement réel fournit les occasions d'apprentissage.

L'objectif n'est pas :

> écrire tout DJUA_SMS sans IA.

L'objectif est :

> comprendre suffisamment DJUA_SMS pour savoir ce que l'IA construit, pourquoi elle le construit, comment le flux fonctionne, comment vérifier les changements et comment reprendre le contrôle lorsqu'un problème apparaît.
