"""
Les tables d'évaluation PeSTO, et leur conversion au repère de python-chess.

--- D'où viennent ces nombres ---
« PeSTO » signifie *Piece-Square Tables Only* : une évaluation qui ne regarde
que deux choses, quelle pièce et sur quelle case. Pas de structure de pions,
pas de sécurité du roi, rien d'autre. C'est volontairement rustique, et
pourtant redoutablement efficace.

Les valeurs n'ont pas été posées à la main par un joueur. Elles ont été
*réglées automatiquement* : on part de valeurs quelconques, on fait évaluer des
millions de positions dont on connaît l'issue réelle, et on ajuste chaque
nombre pour réduire l'écart entre la prédiction et la réalité. C'est la méthode
dite du « texel tuning ». Résultat : des tables qui encodent des connaissances
qu'aucun humain n'aurait su chiffrer aussi finement.

--- Deux jeux de tables, et pourquoi ---
Chaque pièce possède une table « milieu de partie » (mg) et une table « fin de
partie » (eg), parce que la valeur d'une case dépend de la phase :

  Le roi en e1, protégé derrière ses pions, vaut +13 en milieu de partie
  (mg_roi) mais −17 en finale (eg_roi) : une fois les dames échangées, un roi
  terré dans son coin est une pièce inutile, alors qu'un roi centralisé est une
  arme. La même case change complètement de valeur.

L'évaluation interpole entre les deux selon le matériel restant : voir
`evaluation.py`.

--- Le repère ---
Les tables sont écrites ci-dessous dans l'ordre de LECTURE, comme un diagramme
d'échiquier vu du côté des Blancs : la première ligne est la rangée 8, la
dernière est la rangée 1. python-chess, lui, numérote a1 = 0 et h8 = 63. La
fonction `_convertir()` fait la traduction une fois pour toutes au chargement.
"""

from __future__ import annotations

import chess

# --------------------------------------------------------------------------- #
# Valeur des pièces, en centipions
# --------------------------------------------------------------------------- #

# Noter que le cavalier et le fou PERDENT de la valeur en finale, tandis que la
# tour et le pion en GAGNENT : moins il reste de pièces, plus les pions valent
# cher (ils vont à dame) et plus les lignes s'ouvrent pour les tours.
VALEUR_MG = {
    chess.PAWN: 82, chess.KNIGHT: 337, chess.BISHOP: 365,
    chess.ROOK: 477, chess.QUEEN: 1025, chess.KING: 0,
}
VALEUR_EG = {
    chess.PAWN: 94, chess.KNIGHT: 281, chess.BISHOP: 297,
    chess.ROOK: 512, chess.QUEEN: 936, chess.KING: 0,
}

# Poids de chaque pièce dans le calcul de la phase de jeu (voir evaluation.py).
# Deux cavaliers + deux fous + deux tours + une dame par camp = 24 au total.
PHASE = {
    chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 1,
    chess.ROOK: 2, chess.QUEEN: 4, chess.KING: 0,
}
PHASE_TOTALE = 24

# --------------------------------------------------------------------------- #
# Tables brutes, dans l'ordre de lecture (rangée 8 en premier)
# --------------------------------------------------------------------------- #

_MG_PION = [
      0,   0,   0,   0,   0,   0,   0,   0,
     98, 134,  61,  95,  68, 126,  34, -11,
     -6,   7,  26,  31,  65,  56,  25, -20,
    -14,  13,   6,  21,  23,  12,  17, -23,
    -27,  -2,  -5,  12,  17,   6,  10, -25,
    -26,  -4,  -4, -10,   3,   3,  33, -12,
    -35,  -1, -20, -23, -15,  24,  38, -22,
      0,   0,   0,   0,   0,   0,   0,   0,
]
_EG_PION = [
      0,   0,   0,   0,   0,   0,   0,   0,
    178, 173, 158, 134, 147, 132, 165, 187,
     94, 100,  85,  67,  56,  53,  82,  84,
     32,  24,  13,   5,  -2,   4,  17,  17,
     13,   9,  -3,  -7,  -7,  -8,   3,  -1,
      4,   7,  -6,   1,   0,  -5,  -1,  -8,
     13,   8,   8,  10,  13,   0,   2,  -7,
      0,   0,   0,   0,   0,   0,   0,   0,
]

_MG_CAVALIER = [
    -167, -89, -34, -49,  61, -97, -15, -107,
     -73, -41,  72,  36,  23,  62,   7,  -17,
     -47,  60,  37,  65,  84, 129,  73,   44,
      -9,  17,  19,  53,  37,  69,  18,   22,
     -13,   4,  16,  13,  28,  19,  21,   -8,
     -23,  -9,  12,  10,  19,  17,  25,  -16,
     -29, -53, -12,  -3,  -1,  18, -14,  -19,
    -105, -21, -58, -33, -17, -28, -19,  -23,
]
_EG_CAVALIER = [
    -58, -38, -13, -28, -31, -27, -63, -99,
    -25,  -8, -25,  -2,  -9, -25, -24, -52,
    -24, -20,  10,   9,  -1,  -9, -19, -41,
    -17,   3,  22,  22,  22,  11,   8, -18,
    -18,  -6,  16,  25,  16,  17,   4, -18,
    -23,  -3,  -1,  15,  10,  -3, -20, -22,
    -42, -20, -10,  -5,  -2, -20, -23, -44,
    -29, -51, -23, -15, -22, -18, -50, -64,
]

_MG_FOU = [
    -29,   4, -82, -37, -25, -42,   7,  -8,
    -26,  16, -18, -13,  30,  59,  18, -47,
    -16,  37,  43,  40,  35,  50,  37,  -2,
     -4,   5,  19,  50,  37,  37,   7,  -2,
     -6,  13,  13,  26,  34,  12,  10,   4,
      0,  15,  15,  15,  14,  27,  18,  10,
      4,  15,  16,   0,   7,  21,  33,   1,
    -33,  -3, -14, -21, -13, -12, -39, -21,
]
_EG_FOU = [
    -14, -21, -11,  -8,  -7,  -9, -17, -24,
     -8,  -4,   7, -12,  -3, -13,  -4, -14,
      2,  -8,   0,  -1,  -2,   6,   0,   4,
     -3,   9,  12,   9,  14,  10,   3,   2,
     -6,   3,  13,  19,   7,  10,  -3,  -9,
    -12,  -3,   8,  10,  13,   3,  -7, -15,
    -14, -18,  -7,  -1,   4,  -9, -15, -27,
    -23,  -9, -23,  -5,  -9, -16,  -5, -17,
]

_MG_TOUR = [
     32,  42,  32,  51,  63,   9,  31,  43,
     27,  32,  58,  62,  80,  67,  26,  44,
     -5,  19,  26,  36,  17,  45,  61,  16,
    -24, -11,   7,  26,  24,  35,  -8, -20,
    -36, -26, -12,  -1,   9,  -7,   6, -23,
    -45, -25, -16, -17,   3,   0,  -5, -33,
    -44, -16, -20,  -9,  -1,  11,  -6, -71,
    -19, -13,   1,  17,  16,   7, -37, -26,
]
_EG_TOUR = [
     13,  10,  18,  15,  12,  12,   8,   5,
     11,  13,  13,  11,  -3,   3,   8,   3,
      7,   7,   7,   5,   4,  -3,  -5,  -3,
      4,   3,  13,   1,   2,   1,  -1,   2,
      3,   5,   8,   4,  -5,  -6,  -8, -11,
     -4,   0,  -5,  -1,  -7, -12,  -8, -16,
     -6,  -6,   0,   2,  -9,  -9, -11,  -3,
     -9,   2,   3,  -1,  -5, -13,   4, -20,
]

_MG_DAME = [
    -28,   0,  29,  12,  59,  44,  43,  45,
    -24, -39,  -5,   1, -16,  57,  28,  54,
    -13, -17,   7,   8,  29,  56,  47,  57,
    -27, -27, -16, -16,  -1,  17,  -2,   1,
     -9, -26,  -9, -10,  -2,  -4,   3,  -3,
    -14,   2, -11,  -2,  -5,   2,  14,   5,
    -35,  -8,  11,   2,   8,  15,  -3,   1,
     -1, -18,  -9,  10, -15, -25, -31, -50,
]
_EG_DAME = [
     -9,  22,  22,  27,  27,  19,  10,  20,
    -17,  20,  32,  41,  58,  25,  30,   0,
    -20,   6,   9,  49,  47,  35,  19,   9,
      3,  22,  24,  45,  57,  40,  57,  36,
    -18,  28,  19,  47,  31,  34,  39,  23,
    -16, -27,  15,   6,   9,  17,  10,   5,
    -22, -23, -30, -16, -16, -23, -36, -32,
    -33, -28, -22, -43,  -5, -32, -20, -41,
]

_MG_ROI = [
    -65,  23,  16, -15, -56, -34,   2,  13,
     29,  -1, -20,  -7,  -8,  -4, -38, -29,
     -9,  24,   2, -16, -20,   6,  22, -22,
    -17, -20, -12, -27, -30, -25, -14, -36,
    -49,  -1, -27, -39, -46, -44, -33, -51,
    -14, -14, -22, -46, -44, -30, -15, -27,
      1,   7,  -8, -64, -43, -16,   9,   8,
    -15,  36,  12, -54,   8, -28,  24,  14,
]
_EG_ROI = [
    -74, -35, -18, -18, -11,  15,   4, -17,
    -12,  17,  14,  17,  17,  38,  23,  11,
     10,  17,  23,  15,  20,  45,  44,  13,
     -8,  22,  24,  27,  26,  33,  26,   3,
    -18,  -4,  21,  24,  27,  23,   9, -11,
    -19,  -3,  11,  21,  23,  16,   7,  -9,
    -27, -11,   4,  13,  14,   4,  -5, -17,
    -53, -34, -21, -11, -28, -14, -24, -43,
]

_BRUTES_MG = {
    chess.PAWN: _MG_PION, chess.KNIGHT: _MG_CAVALIER, chess.BISHOP: _MG_FOU,
    chess.ROOK: _MG_TOUR, chess.QUEEN: _MG_DAME, chess.KING: _MG_ROI,
}
_BRUTES_EG = {
    chess.PAWN: _EG_PION, chess.KNIGHT: _EG_CAVALIER, chess.BISHOP: _EG_FOU,
    chess.ROOK: _EG_TOUR, chess.QUEEN: _EG_DAME, chess.KING: _EG_ROI,
}

# --------------------------------------------------------------------------- #
# Construction des tables utilisables
# --------------------------------------------------------------------------- #


def _convertir(brutes: list[int]) -> list[int]:
    """
    Passe de l'ordre de lecture (a8 en premier) à la numérotation python-chess.

    L'indice i de la liste brute correspond à la colonne i % 8 et à la rangée
    7 - i // 8 : la première ligne écrite est la rangée 8, donc l'indice 0 est
    la case a8.
    """
    table = [0] * 64
    for i, valeur in enumerate(brutes):
        case = chess.square(i % 8, 7 - i // 8)
        table[case] = valeur
    return table


def _construire(brutes: dict, valeurs: dict) -> tuple[dict, dict]:
    """
    Fabrique les tables finales, valeur matérielle déjà incluse.

    Deux optimisations qui comptent, puisque ces tables sont lues des millions
    de fois par seconde :
      - on additionne la valeur de la pièce à chaque case, pour n'avoir qu'une
        seule lecture au lieu de deux additions à l'exécution ;
      - on prépare une table miroir pour les Noirs, ce qui évite de calculer
        `case ^ 56` à chaque consultation.
    """
    blancs, noirs = {}, {}
    for type_piece, liste in brutes.items():
        table = _convertir(liste)
        valeur = valeurs[type_piece]
        blancs[type_piece] = [valeur + c for c in table]
        # Un Noir sur la case X vaut ce que vaut un Blanc sur la case symétrique.
        noirs[type_piece] = [
            valeur + table[chess.square_mirror(case)] for case in chess.SQUARES
        ]
    return blancs, noirs


MG_BLANCS, MG_NOIRS = _construire(_BRUTES_MG, VALEUR_MG)
EG_BLANCS, EG_NOIRS = _construire(_BRUTES_EG, VALEUR_EG)
