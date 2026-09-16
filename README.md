# Bot Chess

Interface d'analyse d'échecs et moteur maison, tournant entièrement en local.
Le moteur maison est mesuré à **2096 Elo** [2025 .. 2167].

Le projet contient **deux choses distinctes** qu'il ne faut pas confondre :

1. **Un outil d'analyse** façon chess.com, adossé à Stockfish. Terminé, utilisable.
2. **Un moteur d'échecs écrit par nous**, en Python. En construction, mesuré à
   chaque étape.

Les deux se substituent l'un à l'autre d'un clic dans l'interface, parce qu'ils
parlent le même protocole.

TEST

---

## Table des matières

- [Démarrer](#démarrer)
- [L'interface](#linterface)
- [Organisation du code](#organisation-du-code)
- [Le protocole UCI, clé de voûte du projet](#le-protocole-uci-clé-de-voûte-du-projet)
- [Le moteur maison](#le-moteur-maison)
- [Les outils de mesure](#les-outils-de-mesure)
- [Résultats mesurés](#résultats-mesurés)
- [Leçons de méthode](#leçons-de-méthode)
- [Feuille de route](#feuille-de-route)
- [Réinstaller depuis zéro](#réinstaller-depuis-zéro)

---

## Démarrer

Double-clic sur **`Analyse.bat`**, ou :

```bash
python -m interface.app
```

Analyse d'une position en console, sans interface graphique :

```bash
python -m outils.demo_analyse
python -m outils.demo_analyse "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
```

---

## L'interface

### Ce qu'elle sait faire

- Analyse permanente de la position affichée, **quel que soit le camp au trait**.
- Les **3 meilleurs coups**, avec évaluation et variante prévue.
- Une **flèche par coup recommandé** : vert le meilleur, jaune le deuxième,
  rouge le troisième. La couleur indique un **rang**, pas une qualité : c'est le
  chiffre d'évaluation qui dit ce que vaut le coup.
- **Barre d'évaluation** graduée en probabilité de victoire, pas en centipions.
- **Jugement automatique** de chaque coup joué : meilleur coup, excellent, bien,
  imprécision, erreur, gaffe — avec le pourcentage de chances perdues.
- **Mode partie** contre le moteur de ton choix.
- Import d'une **FEN** ou d'un **PGN** par simple collage.
- Notation algébrique **française** (Cf3, Fb5, Dxd8, Th1, O-O, a8=D).
- Fenêtre redimensionnable, échiquier retournable.

### Les réglages du panneau

Trois rangées de pastilles cliquables, en haut du panneau latéral :

| Rangée | Effet |
|---|---|
| `MODE` | `Analyse` montre les meilleurs coups ; `Partie` te fait affronter le moteur |
| `MOTEUR` | `Stockfish` ou `Maison` — le même choix vaut pour l'analyse et pour l'adversaire |
| `FORCE` | bride Stockfish à 1500 ou 2000 Elo (sans effet sur le moteur maison) |

En mode `Partie`, **tu joues le camp du bas** : `F` retourne l'échiquier et te
fait donc changer de couleur. L'analyse est suspendue et la barre d'évaluation
reste neutre — jouer avec la solution sous les yeux n'aurait aucun intérêt.

Un seul moteur tourne à la fois : celui qui analyse en mode Analyse, celui qui
joue en mode Partie. C'est délibéré, le moteur maison étant lent, autant lui
laisser la machine quand c'est son tour.

### Commandes

| Action | Touche |
|---|---|
| Coup précédent / suivant | ← → |
| Début / fin de la partie | ⇱ / ⇲ |
| Retourner l'échiquier | `F` |
| Jouer le coup recommandé | `Espace` |
| Coller une FEN ou un PGN | `Ctrl+V` |
| Copier la FEN courante | `Ctrl+C` |
| Annuler le dernier coup | `Ctrl+Z` |
| Nouvelle partie | `Ctrl+N` |
| Annuler la saisie en cours | `Échap` ou clic droit |

Les pièces se déplacent au glisser-déposer **ou** par deux clics. La molette
fait défiler la liste des coups ; cliquer sur un coup y ramène la position.

---

## Organisation du code

```
noyau/                   logique pure, sans aucun affichage
  config.py              chemins, détection de PyPy, réglages matériels
  moteur_uci.py          dialogue avec n'importe quel moteur UCI
  analyse_continue.py    analyse permanente en tâche de fond (thread)
  adversaire.py          moteur qui joue un camp, en tâche de fond (thread)
  partie.py              coups joués, navigation, import/export PGN
  notation.py            scores lisibles, probabilités, jugements, notation FR

interface/               affichage pygame
  app.py                 assemblage, boucle principale, gestion des évènements
  echiquier_vue.py       dessin de l'échiquier, flèches, pixels <-> cases
  panneau.py             panneau latéral (réglages, variantes, liste des coups)
  barre_eval.py          barre d'évaluation verticale
  pieces.py              fabrication des images de pièces (aucun téléchargement)
  presse_papier.py       accès au presse-papier Windows via tkinter
  theme.py               couleurs et calcul de la disposition

moteur_maison/           notre moteur d'échecs
  tables.py              tables PeSTO (valeur des pièces + valeur des cases)
  evaluation.py          évaluation interpolée milieu / fin de partie
  recherche.py           negamax, alpha-bêta, quiescence, tri, aspiration, PVS
  transposition.py       mémoire des positions déjà analysées
  uci.py                 façade UCI : rend le moteur interchangeable

outils/                  scripts en ligne de commande
  demo_analyse.py        analyse d'une position en console
  verifier.py            garde-fou : une optimisation ne doit rien changer
  vitesse.py             vitesse et profondeur de l'interpréteur courant
  tournoi.py             mesure du niveau par match entre moteurs

moteurs_externes/        Stockfish 18 (non versionné, ~109 Mo)
outils_externes/         PyPy 7.3.23 (non versionné, ~150 Mo)
parties/                 PGN produits par les tournois
```

### Le principe directeur

**`noyau/` ne connaît pas `interface/`.** On peut donc tester toute la logique en
console, la réutiliser pour un tournoi automatique, ou brancher une autre
interface, sans réécrire une ligne. De même, `moteur_maison/` ne connaît ni l'un
ni l'autre : il ne parle que par sa façade UCI.

---

## Le protocole UCI, clé de voûte du projet

UCI (*Universal Chess Interface*) est un protocole texte. Le moteur est un
**programme séparé** qu'on lance en sous-processus ; on lui écrit des commandes
sur son entrée standard et on lit ses réponses sur sa sortie standard :

```
nous   > uci                                  (présente-toi)
moteur < id name Stockfish 18
moteur < uciok
nous   > position fen rnbqkbnr/pppppppp/...   (voici la position)
nous   > go depth 20                          (réfléchis jusqu'à la profondeur 20)
moteur < info depth 20 score cp 34 pv e2e4 e7e5 ...
moteur < bestmove e2e4
```

Ce choix, fait dès la première phase, a rapporté trois fois :

1. **Le moteur maison est interchangeable avec Stockfish** — l'interface ne voit
   aucune différence.
2. **Le moteur peut tourner sous un autre interpréteur.** Comme il vit dans un
   processus séparé et ne communique que par du texte, rien ne l'oblige à
   partager le Python de l'interface. D'où PyPy et son facteur 4,2, obtenu sans
   changer une ligne d'algorithme.
3. **Le moteur peut jouer contre lui-même**, une version contre l'autre, ce qui
   est la façon la plus précise de mesurer une optimisation.

---

## Le moteur maison

Un moteur d'échecs écrit intégralement en Python. Sélectionner `MOTEUR` →
`Maison` dans le panneau le substitue à Stockfish.

### L'évaluation — ce que le moteur *sait*

C'est le seul endroit du programme qui contient de la connaissance échiquéenne.
Tout le reste n'est que du calcul.

**Les tables PeSTO** (`tables.py`). *Piece-Square Tables Only* : une évaluation
qui ne regarde que deux choses, quelle pièce et sur quelle case. Environ 800
nombres, et c'est tout ce que le moteur sait des échecs.

Ces nombres n'ont pas été posés à la main : ils ont été **réglés
automatiquement** par « texel tuning » — on part de valeurs quelconques, on fait
évaluer des millions de positions dont on connaît l'issue réelle, et on ajuste
chaque nombre pour réduire l'écart entre prédiction et réalité. Le savoir a
émergé de la statistique :

```
ROI          milieu   finale        CAVALIER     milieu   finale
  e1 (départ)   +8      -28           a1 (coin)   -105      -29
  g1 (roqué)   +24      -24           d5 (centre)  +53      +22
  e4 (centre)  -46      +27
```

Personne n'a écrit « le roi se cache au début et se bat à la fin », ni « un
cavalier au bord est un cavalier mort ». Les chiffres l'ont découvert.

**L'interpolation entre phases** (`evaluation.py`). Deux jeux de tables, milieu
de partie et finale, mélangés selon le matériel restant :

```
phase 24 (tout est là)      -> 100 % milieu de partie
phase 12 (moitié échangée)  -> moitié-moitié
phase 0  (finale de pions)  -> 100 % finale
```

Sans ce mélange progressif, le moteur sortirait son roi en plein milieu de
partie, et l'évaluation ferait des sauts brutaux à chaque échange.

**L'antisymétrie exacte.** `evaluer()` renvoie le score du point de vue du camp
au trait. La division entière de Python arrondissant vers le bas, `-x // 24`
n'est pas l'opposé de `x // 24` : l'évaluation n'était pas parfaitement
antisymétrique, à un centipion près. Un centipion suffit à faire croire à la
recherche qu'un coup nul rapporte quelque chose. On tronque donc explicitement
vers zéro. Vérifié sur 5 000 positions aléatoires.

### La recherche — ce que le moteur *calcule*

**Negamax.** Ce qui est bon pour moi est exactement mauvais pour l'adversaire.
Une seule fonction au lieu de deux :

```
valeur(position) = max sur les coups de ( - valeur(position après le coup) )
```

**Élagage alpha-bêta.** Dès qu'un coup est assez bon pour que l'adversaire ne le
laisse jamais arriver, inutile de savoir à quel point il est bon. L'arbre passe
de b^n à environ b^(n/2) — à temps égal, deux fois plus de profondeur. Ce gain
dépend **entièrement de l'ordre des coups**, d'où tout ce qui suit.

**Recherche de quiescence.** Le piège de toute recherche à profondeur fixe est
l'effet d'horizon : s'arrêter au milieu d'un échange et croire qu'on a gagné une
dame, alors que la reprise arrive au coup suivant. Arrivé à la profondeur 0, on
continue donc à explorer les captures jusqu'au calme. En échec, on examine
**tous** les coups légaux : se limiter aux captures ferait manquer un mat.

**Tri MVV-LVA** (*Most Valuable Victim, Least Valuable Aggressor*). Prendre une
dame avec un pion d'abord, prendre un pion avec sa dame en dernier.

**Approfondissement itératif.** On cherche à la profondeur 1, puis 2, puis 3.
Recommencer semble du gaspillage ; c'est un gain net, parce que chaque passe
fournit l'ordre de coups de la suivante — et un meilleur ordre élague tellement
mieux que le surcoût est remboursé. Bonus indispensable : on a toujours un coup
jouable quand le temps s'épuise.

**Détection des nulles.** Répétition (par comparaison des clés de position le
long du chemin), règle des 50 coups, matériel insuffisant.

### La table de transposition (`transposition.py`)

Des chemins différents mènent à la même position : `1.e4 e5 2.Cf3` et
`1.Cf3 e5 2.e4` donnent un échiquier identique. On note ce qu'on a trouvé, on le
relit au lieu de recalculer.

**Le vrai gain n'est pas celui qu'on croit.** Économiser des recalculs aide ;
mais chaque entrée retient aussi **le meilleur coup trouvé**, et le réessayer en
premier redonne à l'élagage ses conditions optimales. La mémoire sert surtout à
mieux trier.

**Les trois sortes de scores.** Après un élagage, on ne connaît qu'une borne. Il
faut ranger cette nuance, sinon on réutilise une borne comme une certitude :

| Drapeau | Signification |
|---|---|
| `EXACT` | la vraie valeur, obtenue sans coupure |
| `BORNE_INF` | la valeur est au moins celle-ci (coupure bêta) |
| `BORNE_SUP` | la valeur est au plus celle-ci (aucun coup n'a atteint alpha) |

**Le piège des scores de mat.** « Mat en 3 » signifie « mat en 3 **à partir
d'ici** » : le score encode une distance relative au nœud. Rangé tel quel et relu
depuis une autre profondeur, il fait croire à un mat qui n'existe pas — et le
moteur sacrifie sa dame pour rien, sans jamais planter. On range donc la distance
depuis la **racine**, on relit la distance depuis le **nœud courant**
(`_mat_vers_table` / `_mat_depuis_table`).

**Choix de structure, décidé sur mesure.** Un accès coûte 1,0 µs contre 38 µs
pour générer les coups d'une position, soit **2,7 % du coût d'un nœud**. Le
choix n'ayant aucune importance pour la vitesse, on a pris le plus sûr : un
dictionnaire Python indexé par la clé complète, où aucune collision n'est
possible. Détail agréable : la clé était déjà calculée pour la détection de
répétition, donc la consultation est gratuite.

### Le tri fin et les fenêtres étroites (étape 4b-2)

**Killer moves.** Deux coups tranquilles retenus par niveau de profondeur. À un
niveau donné, les positions sœurs se ressemblent — elles ne diffèrent que par un
coup joué plus haut. Une fourchette qui marche contre une réponse marche souvent
contre les autres.

**Heuristique d'historique.** La généralisation : un compteur par couple (case de
départ, case d'arrivée), incrémenté du **carré** de la profondeur à chaque
coupure. Le carré n'est pas cosmétique — une coupure obtenue profondément a coûté
bien plus de travail, elle en dit donc bien plus long. La table est divisée par
deux quand elle sature, sinon les comptages du début de partie écraseraient
l'information récente.

**Fenêtres d'aspiration.** À la profondeur 9, on connaît le résultat de la 8. Il
est rare qu'un pli change l'évaluation de plus d'un tiers de pion : on cherche
donc entre `score − 30` et `score + 30` plutôt qu'entre −∞ et +∞. Une fenêtre
étroite provoque beaucoup plus de coupures. Si le pari rate, on élargit par
quatre, puis on repasse en fenêtre complète.

**Recherche à fenêtre nulle (PVS).** Une fois le premier coup examiné à fond, on
ne cherche plus à savoir *combien* valent les suivants, seulement **s'ils sont
pires**. Une fenêtre d'un centipion suffit, et coûte bien moins cher. Si un coup
surprend, on le réexamine sérieusement.

Ces deux dernières fonctionnent par pari, et les paris ne sont gagnants que si le
tri est bon : **c'est pourquoi les quatre techniques vont ensemble.** PVS greffé
sur un mauvais tri serait contre-productif.

### PyPy

Le moteur s'exécute sous PyPy, un interpréteur Python qui compile à la volée. Le
code est rigoureusement identique.

```
CPython 3.12 :  40 162 nœuds/s
PyPy 7.3.23  : 167 228 nœuds/s   (4,2×)
```

`noyau/config.py` détecte PyPy automatiquement dans `outils_externes/`. S'il est
absent, le moteur retombe sur Python standard sans rien casser.

**Attention au préchauffage** : à froid le moteur atteint la profondeur 4, à
chaud la 5 — le compilateur a besoin de quelques secondes. Toute mesure doit
préchauffer. En partie réelle, le processus vit toute la partie, donc il est
chaud dès le deuxième coup.

### Les options UCI du moteur

| Option | Défaut | Rôle |
|---|---|---|
| `MultiPV` | 1 | nombre de variantes à renvoyer (1 à 5) |
| `TT` | true | active la table de transposition (4b-1) |
| `Tri` | true | active killers, historique, aspiration et PVS (4b-2) |
| `Elagage` | true | active coup nul, LMR et futility inversée (4c) |

Les deux interrupteurs n'existent que pour la mesure : ils permettent de faire
jouer une version du moteur contre une autre sans maintenir deux programmes.

---

## Les outils de mesure

### 1. `verifier.py` — le garde-fou

**À lancer avant toute mesure de performance.**

```bash
python -m outils.verifier                          # 4b1 contre 4b2 (défaut)
python -m outils.verifier --avant 4a --apres 4b1   # ce qu'a apporté la table
python -m outils.verifier --profondeur 6
```

À partir de l'étape 4b, **les bugs deviennent invisibles** : une table de
transposition mal écrite ne fait pas planter le moteur, elle lui rend des scores
légèrement faux, il joue un peu moins bien, et rien ne prévient.

Le principe est simple et solide : une optimisation qui accélère la recherche ne
doit **rien** changer au résultat. On lance la même recherche dans deux
configurations et on compare les scores. S'ils diffèrent, c'est un bug, pas un
progrès. Le nombre de nœuds, lui, doit chuter — c'est là que se lit le gain.

Chaque étape se compare à **la précédente déjà validée**, jamais au moteur nu :
sinon on ne saurait pas laquelle des deux nouveautés a introduit l'écart.

### 2. `vitesse.py` — vitesse et profondeur

```bash
python -m outils.vitesse
outils_externes\pypy3.11-v7.3.23-win64\pypy.exe -m outils.vitesse
```

Préchauffe, puis mesure les nœuds par seconde et la profondeur atteinte à
0,4 s et 3 s sur cinq positions types.

### 3. `tournoi.py` — l'Elo

```bash
# niveau absolu, contre un Stockfish bridé à un Elo connu
python -m outils.tournoi --parties 100 --elo 1800 --temps 0.4 --pgn parties/x.pgn

# duel : une version du moteur contre une autre
python -m outils.tournoi --parties 100 --temps 1.0 --duel Tri
python -m outils.tournoi --parties 100 --temps 1.0 --duel TT
```

**Le principe.** Un Elo n'existe que par rapport à des adversaires. On fait donc
jouer notre moteur contre un adversaire d'Elo **connu**, et on déduit l'écart du
score obtenu :

```
E = 1 / (1 + 10^(-D/400))        d'où        D = -400 × log10(1/E - 1)
```

**Le duel est plus précis que deux tournois séparés**, parce qu'il n'a qu'une
marge d'erreur au lieu de deux. Et il ne dépend pas de la calibration de
l'échelle de Stockfish.

**La marge d'erreur n'est pas décorative.** Un résultat sans marge n'est pas une
mesure, c'est une impression. Compter environ 100 parties pour ±60 à 70 Elo,
400 pour ±30. L'outil conclut lui-même par `GAIN CONFIRMÉ`, `PERTE CONFIRMÉE` ou
`INDÉCIS` selon que l'intervalle englobe zéro.

Détails d'implémentation qui comptent : les couleurs sont **alternées** (jouer
toujours les Blancs surestimerait le niveau d'environ 30 Elo), les parties
partent de **16 ouvertures différentes** (sans quoi deux moteurs déterministes
rejoueraient la même partie), et `Ctrl+C` affiche les résultats partiels au lieu
de tout perdre.

---

## Résultats mesurés

### Vitesse des briques de base (Ryzen 5 5500)

| Opération | Vitesse | Conséquence |
|---|---|---|
| Génération des coups légaux | 26 318 /s (38 µs) | **le goulot d'étranglement** |
| `push` + `pop` | 282 544 /s | négligeable |
| Évaluation par bitboards | 122 878 /s | retenu |
| Évaluation par `piece_map()` | 46 062 /s | 2,7× plus lent, écarté |
| `_transposition_key()` | 1 346 796 /s | retenu |
| `chess.polyglot.zobrist_hash()` | 57 457 /s | **23× plus lent**, écarté |
| Accès à la table de transposition | 1,0 µs | 2,7 % du coût d'un nœud |

Stockfish 18 sur la même machine, pour comparaison : **5 728 343 nœuds/s**
(6 threads, 2 Go de table).

### Nœuds nécessaires pour atteindre la profondeur 5

Somme sur les 12 positions de `verifier.py`, à résultat rigoureusement identique :

| Version | Nœuds | Gain cumulé |
|---|---|---|
| 4a | 4 915 674 | — |
| 4b-1 (table de transposition) | 1 803 406 | 2,7× |
| 4b-2 (tri fin, fenêtres étroites) | 976 282 | 5,0× |
| 4c (élagages non sûrs) | 272 314 | **18×** |

À partir de 4c, « résultat identique » n'est plus vrai : 4 des 12 positions
donnent un score différent, ce qui est normal et voulu.

### Tests tactiques

52 positions où le meilleur coup dépasse le second d'au moins deux pions,
1 seconde par position :

| Version | Coups trouvés |
|---|---|
| 4b-2 | 38/52 (73,1 %) |
| **4c** | **44/52 (84,6 %)** |

Malgré des élagages qui coupent délibérément des branches, 4c trouve **plus** de
solutions tactiques : il cherche plus profond dans le même temps. Il examine même
plus de nœuds par seconde, un nœud coupé par la futility inversée ne coûtant
qu'une évaluation, sans génération de coups.

### Niveau

| Étape | Mesure | Cadence | Résultat |
|---|---|---|---|
| 4a | 30 parties contre Stockfish 1500 | 0,4 s | **1608 Elo** ± 130 |
| 4b-1 | 100 parties contre Stockfish 1800 | 0,4 s | **1828 Elo** ± 68 |
| **4c** | **100 parties contre Stockfish 2000** | **1,0 s** | **2096 Elo** ± 71 |
| Table de transposition seule | duel, 100 parties | 0,4 s | +35 ± 68 — *indécis* |
| Étape 4b-2 seule | duel, 72 parties | 1,0 s | **+263 ± 104 — confirmé** |
| Étape 4c seule | duel, 100 parties | 1,0 s | **+156 ± 75 — confirmé** |

Le duel 4b-2 s'est arrêté à 72 parties sur 100 (processus tué, cause inconnue,
sans trace d'erreur). Les 72 parties suffisent : 54 victoires, 10 nulles,
8 défaites, soit 81,9 %, borne basse à +158 Elo.

**Objectif atteint.** Le moteur maison est mesuré à **2096 Elo**, intervalle de
confiance [2025 .. 2167] : la borne basse elle-même dépasse 2000. Ce n'est pas
une estimation ponctuelle mais un résultat, obtenu sur 100 parties contre un
Stockfish bridé à exactement 2000 — un score supérieur à 50 % suffisant à
trancher la question.

### Génération de parties (pour un futur auto-apprentissage)

Un seul cœur, sous PyPy :

| Profondeur | Durée par partie | Positions calmes par partie |
|---|---|---|
| 3 | 10,5 s | 99 |
| 4 | 28,1 s | 108 |
| 5 | 71,9 s | 123 |

Mémoire : **488 Mo** pour un processus après 3 parties (table à 267 000
entrées). À plafond, compter ~800 Mo par processus — d'où l'intérêt de réduire
`ENTREES_MAX` pour ce cas d'usage.

---

## Leçons de méthode

### 1. Une optimisation ne se mesure qu'au point de fonctionnement où elle agit

La table de transposition a d'abord donné **+35 Elo ± 68**, un résultat indécis,
alors qu'on en attendait +150 à 250. La cause n'était pas le code mais la
cadence : à 0,4 s par coup le moteur n'atteignait que la profondeur 2 à 4, et une
table de transposition ne sert à rien à cette profondeur — il n'y a presque rien
à transposer dans un arbre aussi petit.

Mesuré à 2 s, le gain apparaît dans 4 positions sur 5. C'est ce constat qui a
fait remonter PyPy avant la fin de l'étape 4b, et qui a fait mesurer 4b-2 à 1,0 s
plutôt qu'à 0,4 s.

### 2. Vérifier avant de mesurer

Une optimisation correcte ne change aucun résultat. Si les scores bougent, c'est
un bug — et à partir de 4b, ce bug ne se manifeste par aucun plantage.

### 3. Mesurer avant de choisir

Trois décisions techniques ont été prises sur mesure et non au jugé : la clé de
transposition (`_transposition_key` plutôt que `zobrist_hash`, 23× plus rapide),
l'évaluation par bitboards (2,7× plus rapide que `piece_map`), et la structure de
la table (la plus sûre, puisque la vitesse ne dépendait pas du choix).

### 4. Un garde-fou n'est valable que pour ce qu'il sait vérifier

`verifier.py` exige des scores identiques. C'est le bon test jusqu'à 4b, où
toutes les optimisations sont *sûres*. À 4c, les élagages changent le résultat
par construction : le test perd son sens et il a fallu le remplacer par une
suite tactique (`outils/tactique.py`).

Il a quand même servi une dernière fois, comme signal d'alarme : il a montré 4c
ratant un mat en 3 que 4b-2 trouvait. Le coup mateur était tranquille mais
donnait échec, et j'avais omis ce test dans les exclusions LMR. Réduit de deux
plis, le mat passait sous l'horizon. Aucun plantage, aucun message — juste un
moteur devenu aveugle par intermittence. Correction : ne jamais réduire un coup
qui donne échec, pour 0,9 % de nœuds en plus.

### 5. Un chiffre sans marge d'erreur n'est pas une mesure

4 parties gagnées sur 6 donnent « +191 Elo ± 393 », ce qui ne veut rien dire.
L'outil affiche systématiquement l'intervalle de confiance et refuse de conclure
quand il englobe zéro.

---

## Feuille de route

| Étape | Contenu | État |
|---|---|---|
| 0-3 | Interface d'analyse complète, mode partie | ✅ fait |
| 4a | Évaluation PeSTO, negamax, alpha-bêta, quiescence, MVV-LVA, UCI | ✅ 1608 Elo |
| 4b-1 | Table de transposition + PyPy | ✅ 1828 Elo |
| 4b-2 | Killers, historique, aspiration, PVS | ✅ +263 Elo |
| 4c | Coup nul, LMR, futility inversée | ✅ +156 Elo |
| **5** | **Mesure complète, génération par étapes** | ⬜ en cours |
| 6 | Livre d'ouvertures, gestion du temps, multi-cœurs | ⬜ |

### Au-delà : les plafonds successifs

| Piste | Gain réaliste | Difficulté |
|---|---|---|
| Livre d'ouvertures | +30 à 50 | faible |
| Gestion du temps (réfléchir plus sur les coups critiques) | +30 à 60 | faible |
| Multi-cœurs | +80 à 150 | difficile — le verrou de Python impose des processus séparés |
| **Notre propre évaluation, réglée par nous** | +100 à 250 | gros morceau |

Le moteur n'utilise aujourd'hui **qu'un seul des 6 cœurs** de la machine.

L'architecture actuelle plafonne vers **2200-2400 Elo**. Au-delà il faudrait
changer de nature : réécriture en C, ou évaluation par réseau de neurones.

### Notre propre évaluation

Le seul morceau du projet où le moteur **apprendrait** vraiment quelque chose —
tout le reste ne fait que calculer plus vite.

Le principe : refaire nous-mêmes le texel tuning qui a produit PeSTO. Notre
évaluation étant **linéaire en ses paramètres**, la dérivée par rapport à chaque
nombre est immédiate — pas de rétropropagation, une descente de gradient
élémentaire qui converge en quelques minutes.

1. Un jeu de positions avec le résultat réel de la partie (gagnée/nulle/perdue).
2. L'évaluation prédit une probabilité de victoire, on la compare au résultat.
3. On pousse les ~800 nombres dans le sens qui réduit l'écart.
4. On valide par duel direct : **nos tables contre PeSTO**.

Attente honnête : le premier jet sera probablement **moins bon** que PeSTO, réglé
sur des millions de parties de qualité avec des années de méthodologie. L'intérêt
n'est pas de refaire les mêmes tables en moins bien, mais de **posséder la
machine à régler** — pour ensuite régler ce que PeSTO ne regarde pas du tout :
mobilité, structure de pions, sécurité du roi, tours sur colonne ouverte, paire
de fous. C'est là que se trouvent les +250 Elo.

Ordre de grandeur : 800 paramètres demandent au moins 1 million de positions
(≈ 10 000 parties), 4 millions étant confortable. À profondeur 3 sur les 6 cœurs
de la machine, compter une nuit pour le premier million.

---

## Réinstaller depuis zéro

### Dépendances Python

```bash
pip install -r requirements.txt
```

soit `chess`, `pygame` et `pillow`. `tkinter` et `numpy` viennent avec Python.

### Stockfish

Télécharger la variante **bmi2** (celle qui exploite les instructions rapides des
processeurs Zen 3 et suivants) sur
[stockfishchess.org/download](https://stockfishchess.org/download/), et placer le
`.exe` dans `moteurs_externes/stockfish/`. `config.py` le retrouve par
motif, sans nom codé en dur : une mise à jour de Stockfish ne casse rien.

### PyPy (facultatif mais très rentable)

Télécharger PyPy pour Windows x64 sur
[pypy.org/download.html](https://pypy.org/download.html), décompresser dans
`outils_externes/`, puis :

```bash
outils_externes\pypy3.11-v7.3.23-win64\pypy.exe -m ensurepip
outils_externes\pypy3.11-v7.3.23-win64\pypy.exe -m pip install chess
```

`config.py` le détecte automatiquement. Sans lui, le moteur tourne 4,2 fois
moins vite mais fonctionne parfaitement.

### Réglages matériels

Dans `noyau/config.py` :

| Réglage | Valeur | Rôle |
|---|---|---|
| `THREADS_MOTEUR` | 6 | threads laissés à Stockfish |
| `HASH_MOTEUR_MO` | 2048 | table de transposition de Stockfish |
| `NB_VARIANTES` | 3 | nombre de coups proposés |
| `PROFONDEUR_DEFAUT` | 18 | profondeur d'analyse de Stockfish |
| `TEMPS_ANALYSE_MAISON` | 3.0 s | le moteur maison est borné par le temps |
| `TEMPS_ADVERSAIRE` | 2.0 s | réflexion par coup en mode partie |

Les pièces sont **fabriquées localement** à partir des glyphes Unicode de la
police Segoe UI Symbol : aucun fichier d'image à télécharger, et un rendu net à
toutes les tailles.
