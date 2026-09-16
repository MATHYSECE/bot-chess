"""
Tournoi automatique entre deux moteurs, pour mesurer un niveau au lieu de le supposer.

Utilisation :
    python -m outils.tournoi --parties 30 --elo 1500 --temps 0.5
    python -m outils.tournoi --parties 20 --elo 2000 --temps 1.0 --pgn parties/test.pgn

--- Le principe de la mesure ---
On ne peut pas mesurer un Elo dans l'absolu : un Elo n'existe que par rapport à
des adversaires. On fait donc jouer notre moteur contre un Stockfish bridé à un
Elo CONNU, et on déduit l'écart à partir du score obtenu.

La formule vient directement de la définition du système Elo, qui pose que
l'espérance de score entre deux joueurs séparés de D points vaut :

    E = 1 / (1 + 10^(-D/400))

En l'inversant, on obtient l'écart à partir du score observé :

    D = -400 × log10(1/E - 1)

--- Le piège du petit échantillon ---
Sur 10 parties, un score de 5/10 pourrait tout aussi bien venir d'un moteur
100 Elo plus faible que d'un moteur 100 Elo plus fort : le hasard domine. C'est
pourquoi on affiche systématiquement un intervalle de confiance. Un résultat
sans marge d'erreur n'est pas une mesure, c'est une impression.

Compter environ 100 parties pour une marge de ±60 Elo, 400 pour ±30.
"""

from __future__ import annotations

import argparse
import math
import random
import time

import chess
import chess.engine
import chess.pgn

from noyau import config
from noyau.moteur_uci import MoteurUCI

# Quelques ouvertures classiques jouées comme position de départ. Sans elles,
# deux moteurs déterministes rejoueraient exactement la même partie à chaque
# fois, et l'on mesurerait un seul duel répété au lieu d'un échantillon.
OUVERTURES = [
    "e4 e5", "e4 c5", "e4 e6", "e4 c6",
    "d4 d5", "d4 Nf6", "d4 e6", "d4 f5",
    "Nf3 d5", "c4 e5", "e4 d5", "d4 g6",
    "e4 Nf6", "c4 Nf6", "Nf3 Nf6", "e4 d6",
]

# Nombre maximal de coups avant de déclarer la partie nulle. Sans ce garde-fou,
# deux moteurs faibles peuvent tourner en rond indéfiniment.
COUPS_MAX = 200


def position_depart(ouverture: str) -> chess.Board:
    plateau = chess.Board()
    for san in ouverture.split():
        plateau.push_san(san)
    return plateau


def jouer_partie(
    blancs: MoteurUCI,
    noirs: MoteurUCI,
    ouverture: str,
    temps: float,
) -> tuple[float, chess.Board]:
    """
    Joue une partie complète et renvoie le score des Blancs (1, 0.5 ou 0).

    Le temps est fixé par coup plutôt que par partie : c'est moins réaliste
    qu'une vraie cadence, mais bien plus reproductible, ce qui est exactement
    ce qu'on veut pour une mesure.
    """
    plateau = position_depart(ouverture)

    while not plateau.is_game_over(claim_draw=True):
        if plateau.fullmove_number > COUPS_MAX:
            return 0.5, plateau

        moteur = blancs if plateau.turn == chess.WHITE else noirs
        try:
            coup = moteur.meilleur_coup(plateau, temps=temps)
        except Exception:
            # Un moteur qui plante perd la partie : c'est la règle des tournois.
            return (0.0 if plateau.turn == chess.WHITE else 1.0), plateau

        if coup is None or coup not in plateau.legal_moves:
            return (0.0 if plateau.turn == chess.WHITE else 1.0), plateau

        plateau.push(coup)

    issue = plateau.outcome(claim_draw=True)
    if issue is None or issue.winner is None:
        return 0.5, plateau
    return (1.0 if issue.winner == chess.WHITE else 0.0), plateau


def ecart_elo(score: float, parties: int) -> tuple[float, float]:
    """
    Convertit un score en écart Elo, avec une marge à 95 %.

    Les scores parfaits (0 ou 1) donnent un écart infini : on les rabat sur la
    demi-partie la plus proche, ce qui revient à dire « au moins tant ».
    """
    borne = 1.0 / (2 * parties)
    p = min(max(score, borne), 1 - borne)
    ecart = -400 * math.log10(1 / p - 1)

    # Erreur type d'une proportion, convertie en Elo par la pente de la courbe
    # logistique au point mesuré (400 / ln(10) × 1 / (p(1-p)) ... simplifié).
    erreur_score = math.sqrt(p * (1 - p) / parties)
    pente = 400 / (math.log(10) * p * (1 - p))
    return ecart, 1.96 * erreur_score * pente


def tournoi(parties: int, elo: int | None, temps: float,
            chemin_pgn: str | None, duel: str | None = None) -> None:
    """
    Fait jouer deux moteurs et en tire un ecart Elo.

    Deux usages :
      - par defaut, notre moteur contre un Stockfish bride : donne un niveau
        absolu, mais dependant de l'echelle de Stockfish ;
      - en mode duel, notre moteur contre lui-meme avec une option desactivee
        d'un cote : donne l'ecart entre deux versions, bien plus precisement.
        `duel` est le nom de l'option UCI a eteindre chez l'adversaire :
        "TT" mesure la table de transposition (etape 4b-1), "Tri" mesure les
        killers, l'historique, l'aspiration et la fenetre nulle (etape 4b-2).

    Le mode duel est la bonne mesure pour valider une optimisation. Comparer
    deux tournois separes contre Stockfish additionnerait leurs deux marges
    d'erreur, alors qu'un affrontement direct n'en a qu'une.
    """
    if duel:
        maison = MoteurUCI(config.commande_moteur_maison(), options={duel: True})
        reference = MoteurUCI(config.commande_moteur_maison(), options={duel: False})
        nom_maison = f"{maison.nom} avec {duel}"
        nom_ref = f"{reference.nom} sans {duel}"
    else:
        maison = MoteurUCI(config.commande_moteur_maison())
        reference = MoteurUCI()
        reference.brider(elo)
        nom_maison = maison.nom
        nom_ref = f"{reference.nom} (Elo {elo})" if elo else reference.nom

    print(f"{nom_maison}  contre  {nom_ref}")
    print(f"{parties} parties, {temps} s par coup\n")

    victoires = nulles = defaites = 0
    jeux = []
    debut = time.perf_counter()
    aleatoire = random.Random(12345)   # graine fixe : tournoi reproductible

    try:
        for numero in range(parties):
            ouverture = OUVERTURES[numero % len(OUVERTURES)]
            # On alterne les couleurs : jouer toujours avec les Blancs
            # surestimerait le niveau d'environ 30 Elo.
            maison_blancs = numero % 2 == 0

            if maison_blancs:
                score, plateau = jouer_partie(maison, reference, ouverture, temps)
            else:
                score, plateau = jouer_partie(reference, maison, ouverture, temps)
                score = 1.0 - score

            if score == 1.0:
                victoires += 1
                issue = "gagnee"
            elif score == 0.5:
                nulles += 1
                issue = "nulle "
            else:
                defaites += 1
                issue = "perdue"

            couleur = "Blancs" if maison_blancs else "Noirs "
            print(f"  partie {numero + 1:3}/{parties}  {couleur}  {issue}   "
                  f"score {victoires + nulles / 2:.1f}/{numero + 1}")

            if chemin_pgn:
                jeu = chess.pgn.Game.from_board(plateau)
                jeu.headers["White"] = nom_maison if maison_blancs else nom_ref
                jeu.headers["Black"] = nom_ref if maison_blancs else nom_maison
                jeu.headers["Event"] = "Tournoi de mesure"
                jeux.append(jeu)
    except KeyboardInterrupt:
        print("\nInterrompu — resultats partiels ci-dessous.")
    finally:
        maison.fermer()
        reference.fermer()

    jouees = victoires + nulles + defaites
    if not jouees:
        return

    score_total = (victoires + nulles / 2) / jouees
    ecart, marge = ecart_elo(score_total, jouees)
    duree = time.perf_counter() - debut

    print()
    print("=" * 58)
    print(f"  {victoires} victoires, {nulles} nulles, {defaites} defaites "
          f"sur {jouees} parties")
    print(f"  score : {score_total:.1%}")
    print(f"  ecart : {ecart:+.0f} Elo  (marge a 95 % : +/- {marge:.0f})")
    if duel:
        verdict = ("GAIN CONFIRME" if ecart - marge > 0
                   else "PERTE CONFIRMEE" if ecart + marge < 0
                   else "INDECIS : la marge englobe zero, il faut plus de parties")
        print(f"  ==> {verdict}")
    elif elo:
        print(f"  ==> niveau estime : {elo + ecart:.0f} Elo  "
              f"[{elo + ecart - marge:.0f} .. {elo + ecart + marge:.0f}]")
    print(f"  duree : {duree / 60:.1f} min")
    print("=" * 58)

    if chemin_pgn and jeux:
        with open(chemin_pgn, "w", encoding="utf-8") as fichier:
            for jeu in jeux:
                print(jeu, file=fichier, end="\n\n")
        print(f"Parties enregistrees dans {chemin_pgn}")


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Tournoi de mesure entre moteurs.")
    analyseur.add_argument("--parties", type=int, default=20)
    analyseur.add_argument("--elo", type=int, default=1500,
                           help="Elo du Stockfish de reference (1320 a 3190)")
    analyseur.add_argument("--temps", type=float, default=0.5,
                           help="secondes de reflexion par coup")
    analyseur.add_argument("--pgn", type=str, default=None,
                           help="fichier ou enregistrer les parties")
    analyseur.add_argument("--duel", nargs="?", const="Tri", default=None,
                           choices=["TT", "Tri", "Elagage"],
                           help="affronte notre moteur avec et sans une option "
                                "(TT = table de transposition, Tri = etape 4b-2)")
    args = analyseur.parse_args()

    tournoi(args.parties, args.elo, args.temps, args.pgn, args.duel)


if __name__ == "__main__":
    main()
