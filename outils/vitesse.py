"""
Mesure la vitesse du moteur sur l'interpreteur qui execute ce script.

Utilisation :
    python -m outils.vitesse
    outils_externes\\pypy3.11-v7.3.23-win64\\pypy.exe -m outils.vitesse

--- Pourquoi le prechauffage ---
PyPy compile le code a la volee : il observe les boucles qui tournent souvent et
les traduit en code machine. Les premieres secondes d'execution sont donc
LENTES, le temps que le compilateur fasse son travail. Mesurer sans prechauffer
donnerait un resultat pessimiste et faux.

Ce n'est pas un artefact de mesure : en partie reelle, le processus du moteur
vit pendant toute la partie, donc il est chaud des le deuxieme ou troisieme
coup. C'est bien la vitesse a chaud qui compte.
"""

from __future__ import annotations

import platform
import sys
import time

import chess

from moteur_maison.recherche import Contraintes, Recherche

MILIEU = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2Q1RK1 w - - 0 9"

POSITIONS = [
    ("depart", chess.STARTING_FEN),
    ("italienne", "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"),
    ("milieu ferme", MILIEU),
    ("milieu ouvert", "r2q1rk1/pp1bbppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 4 10"),
    ("finale tours", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
]


def prechauffer(secondes: float = 6.0) -> None:
    """Fait tourner la recherche a vide pour laisser le compilateur travailler."""
    fin = time.perf_counter() + secondes
    chercheur = Recherche()
    while time.perf_counter() < fin:
        chercheur.chercher(chess.Board(MILIEU), Contraintes(profondeur_max=5, temps_max=1.0))


def main() -> None:
    implementation = platform.python_implementation()
    print(f"{implementation} {platform.python_version()}  ({sys.executable})")
    print()

    print("Prechauffage...", end="", flush=True)
    prechauffer()
    print(" fait.\n")

    # --- Vitesse brute ---
    chercheur = Recherche(utiliser_tt=False)
    resultat = chercheur.chercher(
        chess.Board(MILIEU), Contraintes(profondeur_max=99, temps_max=3.0)
    )
    nps = resultat.noeuds / resultat.temps if resultat.temps else 0
    print(f"vitesse brute : {nps:,.0f} noeuds/s")
    print()

    # --- Profondeur atteinte ---
    print(f"{'position':16}{'0,4 s':>18}{'3 s':>18}")
    print(f"{'':16}{'sans TT':>9}{'avec TT':>9}{'sans TT':>9}{'avec TT':>9}")
    print("-" * 52)

    for nom, fen in POSITIONS:
        ligne = f"{nom:16}"
        for temps in (0.4, 3.0):
            for tt in (False, True):
                chercheur = Recherche(utiliser_tt=tt)
                res = chercheur.chercher(
                    chess.Board(fen), Contraintes(profondeur_max=99, temps_max=temps)
                )
                ligne += f"{res.profondeur:>9}"
        print(ligne)


if __name__ == "__main__":
    main()
