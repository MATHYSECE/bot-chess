"""
L'adversaire : un moteur qui joue contre toi, dans un fil séparé.

Même principe que `analyse_continue.py`, mais pour un besoin différent. Ici on
ne veut pas un flux d'évaluations qui se précise : on veut un coup, et un seul,
au bout du temps de réflexion imparti.

La séparation en deux classes est volontaire. Fusionner les deux aurait donné un
objet aux deux modes de fonctionnement contradictoires — celui qui publie sans
cesse et celui qui répond une fois — avec un état interne difficile à suivre.
"""

from __future__ import annotations

import threading
from pathlib import Path

import chess

from noyau.moteur_uci import MoteurUCI


class Adversaire:
    """Un moteur qui joue un camp de la partie."""

    def __init__(
        self,
        chemin: Path | str | list[str] | None = None,
        elo: int | None = None,
        temps: float = 2.0,
    ):
        self.chemin = chemin
        self.elo = elo            # None = force maximale
        self.temps = temps        # secondes de réflexion par coup

        self.nom = "démarrage…"
        self.erreur: str | None = None
        self.pret = threading.Event()

        self._verrou = threading.Lock()
        self._demande: chess.Board | None = None
        self._coup: chess.Move | None = None
        self._reflechit = False
        self._actif = True
        self._reveil = threading.Event()

        self._fil = threading.Thread(target=self._boucle, name="adversaire", daemon=True)
        self._fil.start()

    # ------------------------------------------------------------------ #
    # Interface publique
    # ------------------------------------------------------------------ #

    def demander(self, echiquier: chess.Board) -> None:
        """Demande un coup pour la position donnée."""
        with self._verrou:
            if self._reflechit:
                return          # déjà en train de chercher, on ne redemande pas
            self._demande = echiquier.copy()
            self._coup = None
            self._reflechit = True
        self._reveil.set()

    def coup_pret(self) -> chess.Move | None:
        """
        Récupère le coup trouvé, et l'oublie aussitôt.

        Consommer le coup à la lecture évite qu'il soit joué deux fois si
        l'interface appelle cette méthode à chaque image.
        """
        with self._verrou:
            coup, self._coup = self._coup, None
            return coup

    def reflechit(self) -> bool:
        with self._verrou:
            return self._reflechit

    def arreter(self) -> None:
        self._actif = False
        self._reveil.set()
        self._fil.join(timeout=5.0)

    # ------------------------------------------------------------------ #
    # Fil de réflexion
    # ------------------------------------------------------------------ #

    def _boucle(self) -> None:
        try:
            moteur = MoteurUCI(self.chemin)
        except Exception as erreur:
            self.erreur = str(erreur)
            self.pret.set()
            return

        self.nom = moteur.nom
        moteur.brider(self.elo)
        self.pret.set()

        try:
            while self._actif:
                self._reveil.wait(timeout=0.2)
                self._reveil.clear()

                with self._verrou:
                    echiquier = self._demande
                    self._demande = None

                if echiquier is None:
                    continue

                try:
                    coup = moteur.meilleur_coup(echiquier, temps=self.temps)
                except Exception as erreur:
                    self.erreur = str(erreur)
                    coup = None

                with self._verrou:
                    self._coup = coup
                    self._reflechit = False
        finally:
            moteur.fermer()
