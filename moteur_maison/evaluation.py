"""
Évaluation statique d'une position : « combien vaut-elle, sans rien calculer ? »

--- Le rôle de l'évaluation ---
La recherche explore l'arbre des coups possibles ; l'évaluation est ce qu'elle
consulte quand elle arrête d'explorer. C'est le seul endroit où le moteur
possède de la *connaissance* échiquéenne ; tout le reste n'est que du calcul.

--- L'interpolation entre les phases ---
Le point clé de PeSTO. On calcule deux scores en parallèle, l'un avec les
tables de milieu de partie, l'autre avec celles de finale, puis on mélange les
deux selon le matériel qui reste sur l'échiquier :

    phase 24 (tout est là)      -> 100 % milieu de partie
    phase 12 (moitié échangée)  -> moitié-moitié
    phase 0  (finale de pions)  -> 100 % finale

Sans cela, un moteur sortirait son roi en plein milieu de partie parce que la
table de finale le récompense, ou le laisserait dans son coin en finale de
tours. Le mélange progressif évite aussi les sauts d'évaluation brutaux au
moment d'un échange, qui provoquent des coups erratiques.

--- Convention de signe ---
`evaluer()` renvoie le score du point de vue du CAMP AU TRAIT, positif si ce
camp est mieux. C'est la convention qu'impose l'algorithme negamax, qui repose
sur l'identité : ce qui est bon pour moi est exactement mauvais pour l'autre.
"""

from __future__ import annotations

import chess

from moteur_maison import tables

# Raccourcis locaux : en Python, une variable globale du module se lit plus vite
# qu'un attribut d'un autre module (pas de recherche d'attribut à l'exécution).
# Sur une fonction appelée des millions de fois, ça compte réellement.
_MG_B = tables.MG_BLANCS
_MG_N = tables.MG_NOIRS
_EG_B = tables.EG_BLANCS
_EG_N = tables.EG_NOIRS
_PHASE = tables.PHASE
_PHASE_TOTALE = tables.PHASE_TOTALE

_TYPES = (chess.PAWN, chess.KNIGHT, chess.BISHOP,
          chess.ROOK, chess.QUEEN, chess.KING)

_scan = chess.scan_forward


def evaluer(echiquier: chess.Board) -> int:
    """
    Score de la position en centipions, du point de vue du camp au trait.

    On parcourt les pièces via les bitboards plutôt que via `piece_map()` :
    mesuré 2,7 fois plus rapide, parce que `scan_forward` égrène directement
    les bits d'un entier au lieu de construire un dictionnaire d'objets.
    """
    mg = 0
    eg = 0
    phase = 0

    for type_piece in _TYPES:
        poids = _PHASE[type_piece]
        table_mg_b = _MG_B[type_piece]
        table_eg_b = _EG_B[type_piece]
        table_mg_n = _MG_N[type_piece]
        table_eg_n = _EG_N[type_piece]

        # `pieces_mask` renvoie un entier dont chaque bit à 1 est une case
        # occupée par ce type de pièce et cette couleur.
        for case in _scan(echiquier.pieces_mask(type_piece, chess.WHITE)):
            mg += table_mg_b[case]
            eg += table_eg_b[case]
            phase += poids

        for case in _scan(echiquier.pieces_mask(type_piece, chess.BLACK)):
            mg -= table_mg_n[case]
            eg -= table_eg_n[case]
            phase += poids

    # Une promotion peut créer plus de matériel que la position de départ n'en
    # comptait : sans ce plafond, l'interpolation sortirait de [0, 1].
    if phase > _PHASE_TOTALE:
        phase = _PHASE_TOTALE

    total = mg * phase + eg * (_PHASE_TOTALE - phase)

    # Attention à la division : `//` arrondit vers le bas (−927,3 donne −928),
    # si bien que `-total // 24` n'est pas l'opposé de `total // 24`. On
    # tronquerait alors vers zéro d'un côté et vers l'infini de l'autre, et la
    # même position ne vaudrait pas exactement l'opposé pour l'adversaire.
    # Un centipion d'écart suffit à faire croire à la recherche qu'un coup nul
    # ou une répétition rapporte quelque chose. On tronque donc explicitement
    # vers zéro, ce qui rend l'évaluation parfaitement antisymétrique.
    if total >= 0:
        score = total // _PHASE_TOTALE
    else:
        score = -((-total) // _PHASE_TOTALE)

    # Jusqu'ici tout est calculé du point de vue des Blancs ; on retourne le
    # signe si ce sont les Noirs qui ont le trait.
    return score if echiquier.turn == chess.WHITE else -score


def phase_de_jeu(echiquier: chess.Board) -> int:
    """
    Indice de phase, de 24 (début de partie) à 0 (finale dépouillée).

    Utile en dehors de l'évaluation : la recherche s'en servira à l'étape 4c
    pour désactiver certains élagages en finale, où ils sont dangereux.
    """
    phase = 0
    for type_piece in _TYPES:
        poids = _PHASE[type_piece]
        if poids:
            phase += poids * chess.popcount(echiquier.pieces_mask(type_piece, chess.WHITE))
            phase += poids * chess.popcount(echiquier.pieces_mask(type_piece, chess.BLACK))
    return min(phase, _PHASE_TOTALE)
