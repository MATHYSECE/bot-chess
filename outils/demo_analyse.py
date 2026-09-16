"""
Démonstration en console de la phase 1 : le moteur répond, on sait le lire.

Utilisation :
    python -m outils.demo_analyse
    python -m outils.demo_analyse "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"

Le deuxième exemple est un piège classique : c'est le mat du berger, et le
moteur doit annoncer un mat en 1 pour les Blancs.
"""

from __future__ import annotations

import sys
import time

import chess

from noyau import notation
from noyau.moteur_uci import MoteurUCI

# Position par défaut : le début de partie.
FEN_DEFAUT = chess.STARTING_FEN


def afficher(echiquier: chess.Board, profondeur: int = 20) -> None:
    """Analyse une position et affiche le résultat comme le ferait chess.com."""
    print(echiquier.unicode(invert_color=True, borders=True, empty_square=" "))
    trait = "Blancs" if echiquier.turn == chess.WHITE else "Noirs"
    print(f"\nTrait aux {trait}  |  FEN : {echiquier.fen()}\n")

    with MoteurUCI() as moteur:
        print(f"Moteur : {moteur.nom}")
        debut = time.perf_counter()
        variantes = moteur.analyser(echiquier, profondeur=profondeur, nb_variantes=3)
        duree = time.perf_counter() - debut

    if not variantes:
        print("Partie terminée, aucun coup à proposer.")
        return

    print(f"Analyse à la profondeur {profondeur} en {duree:.1f} s\n")
    print(f"{'#':<3}{'Coup':<8}{'Éval':>8}{'Gain':>8}   Variante prévue")
    print("-" * 78)

    for v in variantes:
        # Score du point de vue du joueur au trait : c'est ce qui intéresse
        # celui qui doit jouer (« est-ce bon POUR MOI ? »).
        eval_texte = notation.texte_score(v.score.pov(echiquier.turn))
        gain = notation.probabilite_victoire(v.score.pov(echiquier.turn))
        suite = notation.variante_en_texte(echiquier, v.coups)
        coup_san = notation.san_francais(echiquier, v.coup) if v.coup else "-"
        print(f"{v.rang:<3}{coup_san:<8}{eval_texte:>8}{gain:>7.0%}   {suite}")

    print("-" * 78)
    # La barre d'évaluation, elle, est toujours orientée « point de vue Blancs ».
    eval_blancs = notation.texte_score(variantes[0].score_blancs())
    print(f"Évaluation de la position (point de vue Blancs) : {eval_blancs}")


def main() -> None:
    fen = sys.argv[1] if len(sys.argv) > 1 else FEN_DEFAUT
    try:
        echiquier = chess.Board(fen)
    except ValueError as erreur:
        print(f"FEN invalide : {erreur}")
        sys.exit(1)
    afficher(echiquier)


if __name__ == "__main__":
    main()
