"""
Suite de tests tactiques : le garde-fou de l'étape 4c.

Utilisation :
    python -m outils.tactique construire --positions 120
    python -m outils.tactique tester --config 4b2
    python -m outils.tactique tester --config 4c --temps 1.0

--- Pourquoi cet outil remplace `verifier.py` ---
Jusqu'à l'étape 4b, toutes nos optimisations étaient *sûres* : elles trouvaient
exactement les mêmes scores, plus vite. `verifier.py` le prouvait en exigeant
des scores identiques.

Les élagages de l'étape 4c ne sont PAS sûrs. Le coup nul, les réductions de
coups tardifs et la futility inversée coupent délibérément des branches qui
pourraient contenir le meilleur coup. Exiger des scores identiques n'a donc plus
aucun sens : ils vont changer, c'est le principe même de la technique.

La bonne question devient : **le moteur trouve-t-il toujours les coups qui
comptent ?** D'où cette suite de positions où il existe un coup nettement
meilleur que tous les autres — exactement le genre de coup qu'un élagage trop
agressif ferait manquer.

--- Comment la suite est construite ---
Automatiquement, et c'est tout l'intérêt d'avoir Stockfish sous la main :

  1. on tire des positions au hasard dans les parties déjà jouées (parties/) ;
  2. Stockfish les analyse en profondeur avec les DEUX meilleurs coups ;
  3. on ne garde que celles où le premier coup écrase le second d'au moins
     deux pions.

Ce filtre est la clé. Dans une position calme, trois coups se valent et « rater
le meilleur » ne veut rien dire. Dans une position à réponse unique, manquer le
coup est une faute nette, et parfaitement mesurable.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import chess
import chess.pgn

from moteur_maison.recherche import Contraintes, Recherche
from noyau import config
from noyau.moteur_uci import MoteurUCI
from outils.verifier import CONFIGURATIONS

FICHIER = config.RACINE / "ressources" / "suite_tactique.txt"

# Écart minimal entre le meilleur coup et le deuxième, en centipions.
# 200 = deux pions : à ce niveau d'écart, il n'y a pas de débat.
ECART_MINIMAL = 200

# Profondeur d'analyse de Stockfish pour établir la vérité de référence.
# 14 suffit largement : on ne cherche pas la valeur exacte de la position, mais
# seulement à constater qu'un coup dépasse le suivant de deux pions. Monter à 18
# multipliait le temps de construction par cinq sans rien changer au verdict.
PROFONDEUR_REFERENCE = 14


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def positions_candidates(nombre: int, graine: int = 42) -> list[chess.Board]:
    """
    Tire des positions dans les parties déjà jouées par nos tournois.

    On écarte les tout débuts (théorie d'ouverture, peu de tactique) et les fins
    de partie où il ne reste presque rien. On veut du milieu de partie, là où se
    jouent les tactiques.
    """
    alea = random.Random(graine)
    plateaux = []

    for chemin in sorted((config.RACINE / "parties").glob("*.pgn")):
        with open(chemin, encoding="utf-8") as fichier:
            while True:
                jeu = chess.pgn.read_game(fichier)
                if jeu is None:
                    break
                plateau = jeu.board()
                coups = list(jeu.mainline_moves())
                for numero, coup in enumerate(coups):
                    plateau.push(coup)
                    if 12 <= numero <= len(coups) - 8 and alea.random() < 0.06:
                        if not plateau.is_game_over():
                            plateaux.append(plateau.copy(stack=False))

    alea.shuffle(plateaux)
    return plateaux[: nombre * 6]      # large réserve : le filtre est sévère


def construire(nombre: int) -> None:
    """Fabrique la suite et l'enregistre."""
    candidates = positions_candidates(nombre)
    if not candidates:
        print("Aucune partie trouvee dans parties/. Lance d'abord un tournoi.")
        return

    print(f"{len(candidates)} positions candidates, filtrage par Stockfish "
          f"(profondeur {PROFONDEUR_REFERENCE})...\n")

    retenues = []
    with MoteurUCI() as stockfish:
        for numero, plateau in enumerate(candidates, start=1):
            if len(retenues) >= nombre:
                break

            variantes = stockfish.analyser(
                plateau, profondeur=PROFONDEUR_REFERENCE, nb_variantes=2
            )
            if len(variantes) < 2:
                continue

            trait = plateau.turn
            note1 = variantes[0].score.pov(trait).score(mate_score=100_000)
            note2 = variantes[1].score.pov(trait).score(mate_score=100_000)
            if note1 is None or note2 is None:
                continue

            ecart = note1 - note2
            if ecart >= ECART_MINIMAL:
                retenues.append((plateau.fen(), variantes[0].coup.uci(), ecart))
                print(f"  [{len(retenues):3}/{nombre}] ecart {ecart:+6}  "
                      f"{plateau.san(variantes[0].coup)}")

            if numero % 25 == 0:
                print(f"  ... {numero} examinees, {len(retenues)} retenues")

    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    with open(FICHIER, "w", encoding="utf-8") as sortie:
        sortie.write("# Suite tactique : position, meilleur coup (UCI), ecart en centipions\n")
        sortie.write(f"# Reference : Stockfish profondeur {PROFONDEUR_REFERENCE}, "
                     f"ecart minimal {ECART_MINIMAL}\n")
        for fen, coup, ecart in retenues:
            sortie.write(f"{fen}\t{coup}\t{ecart}\n")

    print(f"\n{len(retenues)} positions enregistrees dans {FICHIER}")


# --------------------------------------------------------------------------- #
# Test
# --------------------------------------------------------------------------- #


def charger() -> list[tuple[str, str, int]]:
    if not FICHIER.exists():
        raise FileNotFoundError(
            f"{FICHIER} absent. Lance d'abord : python -m outils.tactique construire"
        )
    suite = []
    for ligne in FICHIER.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("#") or not ligne.strip():
            continue
        fen, coup, ecart = ligne.split("\t")
        suite.append((fen, coup, int(ecart)))
    return suite


def tester(nom_config: str, temps: float, profondeur: int | None) -> None:
    """Fait passer la suite à une configuration du moteur."""
    suite = charger()
    print(f"Configuration {nom_config} sur {len(suite)} positions, "
          f"{temps} s par position.\n")

    trouves = 0
    noeuds_total = 0
    rates = []

    for numero, (fen, attendu, ecart) in enumerate(suite, start=1):
        plateau = chess.Board(fen)
        chercheur = Recherche(**CONFIGURATIONS[nom_config])
        resultat = chercheur.chercher(
            plateau,
            Contraintes(profondeur_max=profondeur or 64, temps_max=temps),
        )
        noeuds_total += resultat.noeuds

        joue = resultat.meilleur_coup
        if joue is not None and joue.uci() == attendu:
            trouves += 1
        else:
            rates.append((fen, plateau.san(chess.Move.from_uci(attendu)),
                          plateau.san(joue) if joue else "-", ecart))

        if numero % 20 == 0:
            print(f"  {numero}/{len(suite)} : {trouves} trouves "
                  f"({trouves / numero:.0%})")

    print()
    print("=" * 58)
    print(f"  {nom_config} : {trouves}/{len(suite)} coups trouves "
          f"({trouves / len(suite):.1%})")
    print(f"  {noeuds_total:,} noeuds au total")
    print("=" * 58)

    if rates:
        print(f"\nLes {min(8, len(rates))} premiers echecs "
              f"(attendu / joue / ecart en centipions) :")
        for fen, attendu, joue, ecart in rates[:8]:
            print(f"  {attendu:8} au lieu de {joue:8}  (-{ecart})")
            print(f"      {fen}")


# --------------------------------------------------------------------------- #


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Suite de tests tactiques.")
    sous = analyseur.add_subparsers(dest="action", required=True)

    c = sous.add_parser("construire", help="fabrique la suite avec Stockfish")
    c.add_argument("--positions", type=int, default=120)

    t = sous.add_parser("tester", help="fait passer la suite au moteur maison")
    t.add_argument("--config", default="4c", choices=sorted(CONFIGURATIONS))
    t.add_argument("--temps", type=float, default=1.0)
    t.add_argument("--profondeur", type=int, default=None)

    args = analyseur.parse_args()

    if args.action == "construire":
        construire(args.positions)
    else:
        tester(args.config, args.temps, args.profondeur)


if __name__ == "__main__":
    main()
