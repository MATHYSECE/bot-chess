"""
État d'une partie : les coups joués, la navigation, les jugements du moteur.

Ce fichier ne connaît rien à l'affichage. C'est volontaire : on peut le tester
en console, s'en servir pour un tournoi automatique entre deux moteurs, ou le
brancher sur une autre interface, sans rien réécrire.

--- Le choix de représentation ---
On ne conserve pas un échiquier que l'on modifierait sur place, mais :
    position de départ (FEN) + liste ordonnée des coups + un curseur.
Reconstruire l'échiquier revient alors à rejouer les coups depuis le début.
C'est un peu plus de calcul (négligeable : quelques microsecondes), mais ça rend
le « sauter au coup n°12 » trivial et sans risque de désynchronisation.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import chess
import chess.pgn


@dataclass
class CoupJoue:
    """Un coup de la partie, accompagné de ce que le moteur en a pensé."""

    coup: chess.Move
    san: str                          # notation française, calculée à l'ajout
    jugement: str | None = None       # « Excellent », « Gaffe »...
    perte: float = 0.0                # probabilité de victoire perdue (0 à 1)
    eval_apres: object | None = None  # chess.engine.Score, point de vue Blancs


@dataclass
class Partie:
    """La partie en cours, avec son curseur de navigation."""

    fen_depart: str = chess.STARTING_FEN
    coups: list[CoupJoue] = field(default_factory=list)
    index: int = 0  # nombre de coups affichés ; 0 = position de départ

    # ------------------------------------------------------------------ #
    # Lecture de l'état
    # ------------------------------------------------------------------ #

    def echiquier(self) -> chess.Board:
        """
        L'échiquier tel qu'il doit être affiché, c'est-à-dire au curseur.

        On renvoie une reconstruction fraîche à chaque appel : l'appelant peut
        la modifier sans crainte d'abîmer l'état de la partie.
        """
        plateau = chess.Board(self.fen_depart)
        for entree in self.coups[: self.index]:
            plateau.push(entree.coup)
        return plateau

    def dernier_coup(self) -> chess.Move | None:
        """Le coup qui a mené à la position affichée, pour le surligner."""
        if self.index == 0:
            return None
        return self.coups[self.index - 1].coup

    def au_bout(self) -> bool:
        """Vrai si le curseur est sur la dernière position connue."""
        return self.index == len(self.coups)

    # ------------------------------------------------------------------ #
    # Modification
    # ------------------------------------------------------------------ #

    def jouer(self, coup: chess.Move) -> bool:
        """
        Joue un coup depuis la position affichée.

        Si l'on n'est pas à la fin de la partie, la suite est effacée : on part
        dans une nouvelle ligne. C'est le comportement de chess.com et de
        Lichess, celui auquel un joueur s'attend.
        """
        plateau = self.echiquier()
        if coup not in plateau.legal_moves:
            return False

        from noyau import notation  # import local : évite une dépendance circulaire

        san = notation.san_francais(plateau, coup)
        del self.coups[self.index :]
        self.coups.append(CoupJoue(coup=coup, san=san))
        self.index += 1
        return True

    def annuler(self) -> bool:
        """Supprime définitivement le dernier coup de la partie."""
        if not self.coups:
            return False
        self.coups.pop()
        self.index = min(self.index, len(self.coups))
        return True

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #

    def aller_a(self, index: int) -> None:
        """Place le curseur, en le maintenant dans les bornes valides."""
        self.index = max(0, min(index, len(self.coups)))

    def precedent(self) -> None:
        self.aller_a(self.index - 1)

    def suivant(self) -> None:
        self.aller_a(self.index + 1)

    def debut(self) -> None:
        self.aller_a(0)

    def fin(self) -> None:
        self.aller_a(len(self.coups))

    # ------------------------------------------------------------------ #
    # Import / export
    # ------------------------------------------------------------------ #

    @classmethod
    def depuis_fen(cls, fen: str) -> "Partie":
        """Nouvelle partie démarrant sur une position donnée."""
        chess.Board(fen)  # lève ValueError si la FEN est invalide
        return cls(fen_depart=fen)

    @classmethod
    def depuis_pgn(cls, texte: str) -> "Partie":
        """
        Charge une partie au format PGN (celui qu'exportent chess.com et Lichess).

        Permet de coller une de tes parties dans l'interface pour l'analyser
        coup par coup.
        """
        from noyau import notation

        jeu = chess.pgn.read_game(io.StringIO(texte))
        if jeu is None:
            raise ValueError("Aucune partie trouvée dans ce texte PGN.")

        depart = jeu.headers.get("FEN", chess.STARTING_FEN)
        partie = cls(fen_depart=depart)
        plateau = chess.Board(depart)

        for coup in jeu.mainline_moves():
            partie.coups.append(
                CoupJoue(coup=coup, san=notation.san_francais(plateau, coup))
            )
            plateau.push(coup)

        partie.fin()
        return partie

    def vers_pgn(self) -> str:
        """Exporte la partie en PGN, pour la sauvegarder ou la coller ailleurs."""
        jeu = chess.pgn.Game()
        if self.fen_depart != chess.STARTING_FEN:
            jeu.headers["FEN"] = self.fen_depart
            jeu.headers["SetUp"] = "1"

        noeud: chess.pgn.GameNode = jeu
        for entree in self.coups:
            noeud = noeud.add_variation(entree.coup)

        exporteur = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
        return jeu.accept(exporteur)
