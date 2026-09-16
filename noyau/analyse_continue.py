"""
Analyse permanente de la position affichée, dans un fil d'exécution séparé.

--- Le problème à résoudre ---
Une interface graphique redessine sa fenêtre 60 fois par seconde. Si on lui
demande d'attendre le moteur, tout se fige : la fenêtre devient grise, Windows
la déclare « ne répond pas ». Il faut donc que le moteur travaille *à côté*.

--- La solution ---
Un fil (thread) dédié possède le moteur et lui parle. L'interface ne fait que
deux choses, toutes deux instantanées :
    demander(echiquier)  -> « analyse plutôt ceci maintenant »
    resultat()           -> « donne-moi le dernier état connu »

Toute la communication passe par deux variables protégées par un verrou. Le
moteur, lui, n'est JAMAIS touché depuis l'extérieur du fil : les objets de
python-chess ne sont pas conçus pour un accès concurrent.

--- Pourquoi une analyse « continue » ---
Un moteur travaille par approfondissement itératif : il résout d'abord à la
profondeur 1, puis 2, puis 3... et publie un résultat à chaque étape. On affiche
donc une évaluation grossière au bout de quelques millisecondes, qui se précise
sous les yeux de l'utilisateur — exactement le comportement de chess.com.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from pathlib import Path

import chess

from noyau import config
from noyau.moteur_uci import MoteurUCI, Variante


@dataclass(frozen=True)
class Resultat:
    """
    Instantané figé de l'analyse.

    L'objet est `frozen` (non modifiable) à dessein : le fil d'analyse en crée
    un nouveau à chaque publication au lieu de modifier l'ancien. L'interface
    peut donc le lire tranquillement, sans risquer de tomber sur un objet à
    moitié mis à jour.
    """

    fen: str                              # position concernée, pour vérification
    variantes: tuple[Variante, ...] = ()
    profondeur: int = 0
    termine: bool = False                 # vrai quand la profondeur max est atteinte
    noeuds: int = 0                       # positions examinées
    vitesse: int = 0                      # positions par seconde


class AnalyseContinue:
    """Pilote un moteur en tâche de fond et publie ses résultats au fil de l'eau."""

    def __init__(
        self,
        chemin: Path | None = None,
        nb_variantes: int = config.NB_VARIANTES,
        profondeur_max: int = config.PROFONDEUR_DEFAUT,
        temps_max: float | None = None,
        elo: int | None = None,
    ):
        self.chemin = chemin
        self.nb_variantes = nb_variantes
        self.profondeur_max = profondeur_max
        # Notre moteur maison n'atteindra jamais la profondeur 18 : pour lui on
        # borne l'analyse par le temps plutot que par la profondeur.
        self.temps_max = temps_max
        self.elo = elo

        self.nom_moteur = "démarrage…"
        self.erreur: str | None = None
        self.pret = threading.Event()

        self._verrou = threading.Lock()
        self._demande: chess.Board | None = None
        self._resultat: Resultat | None = None
        self._flux = None            # flux d'analyse en cours, pour l'interrompre
        self._actif = True
        self._reveil = threading.Event()

        # daemon=True : le fil ne survit pas à la fermeture du programme, même
        # si l'on oublie de l'arrêter proprement.
        self._fil = threading.Thread(target=self._boucle, name="analyse", daemon=True)
        self._fil.start()

    # ------------------------------------------------------------------ #
    # Interface publique (appelée depuis le fil principal)
    # ------------------------------------------------------------------ #

    def demander(self, echiquier: chess.Board) -> None:
        """
        Demande l'analyse d'une position, en abandonnant celle en cours.

        On copie l'échiquier : l'interface va continuer à le manipuler, et le
        fil d'analyse ne doit surtout pas travailler sur un objet qui bouge.
        """
        with self._verrou:
            self._demande = echiquier.copy(stack=False)
            self._resultat = None       # l'ancien résultat ne vaut plus rien
            flux = self._flux
        self._reveil.set()

        # Coupe net le calcul en cours. Sans cela, il faudrait attendre la fin
        # de la profondeur courante, ce qui peut prendre plusieurs secondes.
        if flux is not None:
            try:
                flux.stop()
            except Exception:
                pass  # le flux venait de se terminer tout seul

    def resultat(self) -> Resultat | None:
        """Dernier résultat publié, ou None si l'analyse vient de commencer."""
        with self._verrou:
            return self._resultat

    def arreter(self) -> None:
        """Termine le fil et ferme le moteur."""
        self._actif = False
        with self._verrou:
            flux = self._flux
        if flux is not None:
            try:
                flux.stop()
            except Exception:
                pass
        self._reveil.set()
        self._fil.join(timeout=3.0)

    # ------------------------------------------------------------------ #
    # Vie du fil d'analyse
    # ------------------------------------------------------------------ #

    def _boucle(self) -> None:
        """Boucle principale du fil : ouvrir le moteur, puis servir les demandes."""
        try:
            moteur = MoteurUCI(self.chemin)
        except Exception as erreur:
            self.erreur = str(erreur)
            self.pret.set()
            return

        self.nom_moteur = moteur.nom
        moteur.brider(self.elo)
        self.pret.set()

        try:
            while self._actif:
                # wait() avec délai : on se réveille aussi périodiquement pour
                # pouvoir constater un arrêt demandé.
                self._reveil.wait(timeout=0.2)
                self._reveil.clear()

                with self._verrou:
                    echiquier = self._demande
                    self._demande = None

                if echiquier is not None:
                    self._analyser(moteur, echiquier)
        finally:
            moteur.fermer()

    def _analyser(self, moteur: MoteurUCI, echiquier: chess.Board) -> None:
        """Analyse une position et publie chaque palier de profondeur atteint."""
        fen = echiquier.fen()

        if echiquier.is_game_over():
            self._publier(Resultat(fen=fen, termine=True))
            return

        # Avec MultiPV, le moteur envoie une info par variante et par profondeur.
        # On attend d'avoir la série complète avant de publier, sinon l'affichage
        # mélangerait la variante 1 de la profondeur 12 avec la 2 de la 11.
        attendues = min(self.nb_variantes, echiquier.legal_moves.count())
        accumulees: dict[int, Variante] = {}

        try:
            flux = moteur.flux_analyse(
                echiquier,
                profondeur=self.profondeur_max,
                temps=self.temps_max,
                nb_variantes=self.nb_variantes,
            )
        except Exception as erreur:
            self.erreur = str(erreur)
            return

        with self._verrou:
            self._flux = flux

        try:
            with flux:
                for info in flux:
                    if not self._actif or self._nouvelle_demande():
                        break
                    if "score" not in info or not info.get("pv"):
                        continue

                    rang = info.get("multipv", 1)
                    accumulees[rang] = Variante(
                        rang=rang,
                        coups=list(info["pv"]),
                        score=info["score"],
                        profondeur=info.get("depth", 0),
                    )

                    if len(accumulees) >= attendues:
                        self._publier(
                            Resultat(
                                fen=fen,
                                variantes=tuple(
                                    accumulees[r] for r in sorted(accumulees)
                                ),
                                profondeur=info.get("depth", 0),
                                noeuds=info.get("nodes", 0) or 0,
                                vitesse=info.get("nps", 0) or 0,
                            )
                        )
                        # Chaque palier repart d'une série vide.
                        if rang == attendues:
                            accumulees = {}
        except Exception:
            # Un moteur qui meurt en cours de route ne doit pas tuer l'interface.
            pass
        finally:
            with self._verrou:
                self._flux = None

        # Marque le résultat comme définitif si la position n'a pas changé.
        # On remplace l'objet plutôt que de le modifier : il est `frozen`, et
        # c'est justement ce qui garantit qu'un lecteur ne verra jamais un état
        # incohérent.
        with self._verrou:
            courant = self._resultat
            if courant is not None and courant.fen == fen and self._demande is None:
                self._resultat = replace(courant, termine=True)

    # ------------------------------------------------------------------ #
    # Utilitaires internes
    # ------------------------------------------------------------------ #

    def _nouvelle_demande(self) -> bool:
        with self._verrou:
            return self._demande is not None

    def _publier(self, resultat: Resultat) -> None:
        with self._verrou:
            # Ne pas écraser un résultat plus récent concernant une autre position.
            if self._demande is None:
                self._resultat = resultat
