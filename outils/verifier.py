"""
Garde-fou du moteur : vérifie qu'une optimisation n'a pas changé les résultats.

Utilisation :
    python -m outils.verifier
    python -m outils.verifier --profondeur 6

--- Pourquoi cet outil existe ---
À partir de l'étape 4b, les bugs deviennent invisibles. Une table de
transposition mal écrite ne fait pas planter le moteur : elle lui rend des
scores légèrement faux, il joue un peu moins bien, et rien ne prévient. On
croirait avoir gagné 200 Elo en en ayant perdu 50.

Le principe du test est simple et solide : une optimisation qui accélère la
recherche ne doit RIEN changer au résultat. On lance donc la même recherche
deux fois, avec et sans la nouveauté, et on compare les scores. S'ils diffèrent,
c'est un bug — pas un progrès.

Le nombre de nœuds, lui, doit chuter : c'est là que se lit le gain.
"""

from __future__ import annotations

import argparse

import chess

from moteur_maison.recherche import Contraintes, Recherche

# Un échantillon volontairement varié : les bugs de table de transposition se
# révèlent surtout dans les finales (peu de pièces, beaucoup de transpositions)
# et dans les positions de mat forcé (scores de mat mal convertis).
POSITIONS = [
    ("depart", chess.STARTING_FEN),
    ("italienne", "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"),
    ("sicilienne", "rnbqkb1r/pp2pppp/3p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 2 6"),
    ("milieu ferme", "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2Q1RK1 w - - 0 9"),
    ("milieu ouvert", "r2q1rk1/pp1bbppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 4 10"),
    ("tactique", "r1b1k2r/ppppnppp/2n2q2/2b5/3NP3/2P1B3/PP3PPP/RN1QKB1R w KQkq - 0 1"),
    ("mat en 2", "r5rk/5p1p/5R2/4B3/8/8/7P/7K w - - 0 1"),
    ("mat en 3", "r1b1kb1r/pppp1ppp/5q2/4n3/3KP3/2N3PN/PPP4P/R1BQ1B1R b kq - 0 1"),
    ("finale tours", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
    ("finale pions", "8/pp3ppp/8/2p5/2P5/8/PP3PPP/8 w - - 0 1"),
    ("finale dames", "8/8/4k3/8/8/4K3/4Q3/8 w - - 0 1"),
    ("repetition", "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"),
]


# Les configurations comparables. Chaque nouvelle etape s'ajoute ici, et se
# mesure contre l'etape precedente deja validee — jamais contre le moteur nu,
# sinon on ne saurait pas laquelle des deux nouveautes a introduit l'ecart.
CONFIGURATIONS = {
    "4a": {"utiliser_tt": False, "utiliser_tri": False, "utiliser_elagage": False},
    "4b1": {"utiliser_tt": True, "utiliser_tri": False, "utiliser_elagage": False},
    "4b2": {"utiliser_tt": True, "utiliser_tri": True, "utiliser_elagage": False},
    # ATTENTION : 4c contient des elagages NON SURS. Comparer 4b2 a 4c fera
    # apparaitre des ecarts de score, et c'est NORMAL, pas un bug. Cet outil ne
    # peut donc plus valider 4c : voir outils/tactique.py.
    "4c": {"utiliser_tt": True, "utiliser_tri": True, "utiliser_elagage": True},
}


def comparer(fen: str, profondeur: int, avant: str, apres: str) -> tuple[bool, dict]:
    """Lance la même recherche dans deux configurations, et compare."""
    resultats = {}

    for etiquette, nom_config in (("sans", avant), ("avec", apres)):
        plateau = chess.Board(fen)
        # Un chercheur neuf à chaque fois : sinon la table garderait des restes
        # de la position précédente et le test ne serait pas reproductible.
        chercheur = Recherche(**CONFIGURATIONS[nom_config])
        resultat = chercheur.chercher(
            plateau, Contraintes(profondeur_max=profondeur, temps_max=120)
        )
        ligne = resultat.lignes[0]
        resultats[etiquette] = {
            "score": ligne.score,
            "coup": plateau.san(ligne.coup),
            "noeuds": resultat.noeuds,
            "temps": resultat.temps,
        }

    identique = resultats["sans"]["score"] == resultats["avec"]["score"]
    return identique, resultats


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Verification de non-regression.")
    analyseur.add_argument("--profondeur", type=int, default=5)
    analyseur.add_argument("--avant", default="4b1", choices=sorted(CONFIGURATIONS),
                           help="configuration de reference (deja validee)")
    analyseur.add_argument("--apres", default="4b2", choices=sorted(CONFIGURATIONS),
                           help="configuration a valider")
    args = analyseur.parse_args()

    print(f"Recherche a profondeur fixe {args.profondeur} : "
          f"{args.avant} contre {args.apres}.\n")
    entete = (f"{'position':16}{'score':>14}{'coup':>16}"
              f"{'noeuds ' + args.avant:>13}{'noeuds ' + args.apres:>13}{'gain':>8}")
    print(entete)
    print("-" * len(entete))

    echecs = []
    total_sans = total_avec = 0

    for nom, fen in POSITIONS:
        identique, r = comparer(fen, args.profondeur, args.avant, args.apres)
        sans, avec = r["sans"], r["avec"]
        total_sans += sans["noeuds"]
        total_avec += avec["noeuds"]

        gain = sans["noeuds"] / avec["noeuds"] if avec["noeuds"] else 0
        if identique:
            score = f"{sans['score']:+}"
        else:
            score = f"{sans['score']:+} != {avec['score']:+}"
            echecs.append((nom, sans, avec))

        coups = sans["coup"] if sans["coup"] == avec["coup"] else f"{sans['coup']}/{avec['coup']}"
        marque = " " if identique else "!"
        print(f"{marque}{nom:15}{score:>14}{coups:>16}"
              f"{sans['noeuds']:>13,}{avec['noeuds']:>13,}{gain:>7.1f}x")

    print("-" * len(entete))
    gain_total = total_sans / total_avec if total_avec else 0
    print(f"{'TOTAL':16}{'':>30}{total_sans:>13,}{total_avec:>13,}{gain_total:>7.1f}x")
    print()

    if echecs:
        print(f"ECHEC : {len(echecs)} position(s) donnent un score different.")
        print(f"Le passage de {args.avant} a {args.apres} modifie le resultat : c'est un bug.")
        for nom, sans, avec in echecs:
            print(f"  {nom} : sans={sans['score']:+} ({sans['coup']}) "
                  f"avec={avec['score']:+} ({avec['coup']})")
    else:
        print("OK : aucun score ne change. Le gain est pur.")
        print("(Un coup different a score egal est normal : plusieurs coups peuvent")
        print(" valoir exactement la meme chose.)")


if __name__ == "__main__":
    main()
