"""
Traduction des chiffres du moteur en informations lisibles par un humain.

Le moteur parle en « centipions » : 100 = la valeur d'un pion. Une interface
d'analyse doit transformer ça en trois choses différentes :
  1. un texte court   -> « +1.35 », « -0.42 », « Mat en 4 »
  2. une probabilité  -> pour la hauteur de la barre d'évaluation
  3. un jugement      -> « Excellent », « Imprécision », « Gaffe »
"""

from __future__ import annotations

import math

import chess
import chess.engine

# --------------------------------------------------------------------------- #
# 1. Affichage du score
# --------------------------------------------------------------------------- #


def texte_score(score: chess.engine.Score, court: bool = False) -> str:
    """
    Met en forme une évaluation, du point de vue de qui l'a produite.

    Exemples : « +1.35 » (avantage blanc), « -0.42 » (avantage noir),
    « Mat en 4 » (ou « M4 » en version courte), « -M3 » si c'est nous qui
    sommes matés.
    """
    mat = score.mate()
    if mat is not None:
        if court:
            return f"{'−' if mat < 0 else '+'}M{abs(mat)}"
        camp = "Mat en" if mat > 0 else "Maté en"
        return f"{camp} {abs(mat)}"

    centipions = score.score()
    if centipions is None:  # ne devrait pas arriver, sécurité
        return "?"

    pions = centipions / 100.0
    # Le signe explicite est important : « 0.30 » seul ne dit pas qui est mieux.
    return f"{pions:+.2f}"


# --------------------------------------------------------------------------- #
# 2. Probabilité de victoire
# --------------------------------------------------------------------------- #

# Constante issue des statistiques de Lichess sur des millions de parties :
# elle relie l'évaluation en centipions au pourcentage de parties gagnées.
_PENTE = 0.00368208


def probabilite_victoire(score: chess.engine.Score) -> float:
    """
    Convertit une évaluation en probabilité de gagner, entre 0.0 et 1.0.

    Pourquoi ne pas utiliser directement les centipions ? Parce qu'ils ne sont
    pas linéaires du point de vue humain. Passer de +0.0 à +1.0 change
    radicalement la partie ; passer de +8.0 à +9.0 ne change rien, c'est gagné
    dans les deux cas. La courbe sigmoïde ci-dessous écrase justement les
    extrêmes, ce qui donne une barre d'évaluation au comportement naturel et
    une classification des coups qui correspond au ressenti du joueur.
    """
    mat = score.mate()
    if mat is not None:
        return 1.0 if mat > 0 else 0.0

    centipions = score.score(mate_score=10_000)
    # Sigmoïde ramenée dans l'intervalle [0, 1].
    return 1.0 / (1.0 + math.exp(-_PENTE * centipions))


# --------------------------------------------------------------------------- #
# 3. Classification des coups
# --------------------------------------------------------------------------- #

# Seuils exprimés en perte de probabilité de victoire, pas en centipions.
# C'est la méthode de chess.com et de Lichess : perdre 0.5 pion quand on est
# à +8 n'est pas grave, le perdre à égalité peut coûter la partie.
_SEUILS = (
    (0.02, "Excellent"),
    (0.05, "Bien"),
    (0.10, "Imprécision"),
    (0.20, "Erreur"),
)
_PIRE = "Gaffe"


def classer_coup(
    proba_avant: float,
    proba_apres: float,
    etait_le_meilleur: bool = False,
) -> tuple[str, float]:
    """
    Juge un coup en comparant la position avant et après.

    Les deux probabilités doivent être exprimées du point de vue du joueur qui
    vient de jouer. On renvoie le libellé et la perte constatée, utile pour
    afficher « tu as perdu 23 % de chances de gagner ».
    """
    if etait_le_meilleur:
        return "Meilleur coup", 0.0

    perte = max(0.0, proba_avant - proba_apres)
    for seuil, libelle in _SEUILS:
        if perte < seuil:
            return libelle, perte
    return _PIRE, perte


# --------------------------------------------------------------------------- #
# 4. Notation des coups
# --------------------------------------------------------------------------- #

# python-chess produit la notation algébrique anglaise ; on la traduit.
# Les colonnes (a-h) étant en minuscules et le roque s'écrivant « O-O », seules
# les majuscules de pièces sont concernées : la substitution est sans ambiguïté.
_PIECES_FR = str.maketrans({
    "K": "R",   # King    -> Roi
    "Q": "D",   # Queen   -> Dame
    "R": "T",   # Rook    -> Tour
    "B": "F",   # Bishop  -> Fou
    "N": "C",   # kNight  -> Cavalier
})


def san_francais(echiquier: chess.Board, coup: chess.Move) -> str:
    """Notation algébrique française d'un coup légal dans la position donnée."""
    return echiquier.san(coup).translate(_PIECES_FR)


def variante_en_texte(
    echiquier: chess.Board,
    coups: list[chess.Move],
    maxi: int = 6,
    francais: bool = True,
) -> str:
    """
    Transforme une suite de coups en notation algébrique lisible.

    Le moteur renvoie des coups au format UCI (« g1f3 » = case de départ, case
    d'arrivée). L'humain lit la notation algébrique standard (« Cf3 »). La
    conversion exige de rejouer les coups un par un, car « Cf3 » dépend de la
    position : s'il y a deux cavaliers pouvant aller en f3, il faut écrire
    « Cgf3 » pour lever l'ambiguïté.

    On travaille sur une copie de l'échiquier pour ne pas modifier l'original.
    """
    copie = echiquier.copy(stack=False)
    morceaux = []

    for coup in coups[:maxi]:
        if coup not in copie.legal_moves:
            break  # variante devenue incohérente, on s'arrête proprement

        numero = copie.fullmove_number
        if copie.turn == chess.WHITE:
            prefixe = f"{numero}."
        elif not morceaux:
            # La variante commence sur un coup noir : on le signale par « 12... »
            prefixe = f"{numero}..."
        else:
            prefixe = ""

        texte = san_francais(copie, coup) if francais else copie.san(coup)
        morceaux.append(prefixe + texte)
        copie.push(coup)

    return " ".join(morceaux)
