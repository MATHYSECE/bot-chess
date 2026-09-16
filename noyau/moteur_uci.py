"""
Dialogue avec un moteur d'échecs UCI.

--- Qu'est-ce que l'UCI ? ---
UCI (Universal Chess Interface) est un protocole texte. Le moteur est un
programme séparé qu'on lance en sous-processus ; on lui écrit des commandes sur
son entrée standard et on lit ses réponses sur sa sortie standard :

    nous   > uci                                  (présente-toi)
    moteur < id name Stockfish 18
    moteur < uciok
    nous   > position fen rnbqkbnr/pppppppp/...   (voici la position)
    nous   > go depth 20                          (réfléchis jusqu'à la profondeur 20)
    moteur < info depth 20 score cp 34 pv e2e4 e7e5 ...
    moteur < bestmove e2e4

--- Pourquoi cette classe ? ---
Tout passe par ce fichier. Le jour où notre moteur maison saura répondre à ces
mêmes commandes, il suffira de changer un chemin : l'interface graphique ne verra
aucune différence. C'est tout l'intérêt d'un protocole standard.

La bibliothèque python-chess gère déjà le dialogue bas niveau (module
chess.engine) ; on se contente de l'habiller pour exposer exactement ce dont
notre interface a besoin, avec un vocabulaire français.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine

from noyau import config


@dataclass
class Variante:
    """
    Une ligne de jeu proposée par le moteur.

    Le moteur peut en proposer plusieurs (option MultiPV) : la variante n°1 est
    le meilleur coup, la n°2 la deuxième meilleure option, etc. C'est ce que
    chess.com affiche sous l'échiquier en mode analyse.
    """

    rang: int                      # 1 = meilleur coup, 2 = deuxième, ...
    coups: list[chess.Move]        # la suite de coups prévue (la « variante »)
    score: chess.engine.PovScore   # l'évaluation, voir la note ci-dessous
    profondeur: int                # profondeur atteinte, en demi-coups

    @property
    def coup(self) -> chess.Move | None:
        """Le premier coup de la variante, c'est-à-dire le coup recommandé."""
        return self.coups[0] if self.coups else None

    def score_blancs(self) -> chess.engine.Score:
        """
        L'évaluation du point de vue des Blancs.

        Attention, subtilité classique : un moteur raisonne toujours du point de
        vue du camp au trait. « +2.0 » signifie « celui qui joue a deux pions
        d'avance », que ce soit les Blancs ou les Noirs. Pour une barre
        d'évaluation façon chess.com, il faut une référence fixe : on convertit
        donc systématiquement vers le point de vue des Blancs.
        """
        return self.score.white()


class MoteurUCI:
    """
    Enveloppe autour d'un moteur UCI (Stockfish, ou notre moteur maison plus tard).

    S'utilise comme un fichier, avec un bloc `with`, pour garantir que le
    sous-processus est bien fermé même en cas d'erreur :

        with MoteurUCI() as moteur:
            variantes = moteur.analyser(echiquier)
    """

    def __init__(
        self,
        chemin: Path | str | list[str] | None = None,
        threads: int = config.THREADS_MOTEUR,
        hash_mo: int = config.HASH_MOTEUR_MO,
        options: dict | None = None,
    ):
        # Trois formes acceptées :
        #   None            -> Stockfish, le moteur par défaut ;
        #   un chemin       -> n'importe quel exécutable UCI ;
        #   une liste       -> une commande complète, ce qu'exige notre moteur
        #                      maison puisqu'il se lance par « python -m ... ».
        if chemin is None:
            commande: str | list[str] = str(config.chemin_stockfish())
        elif isinstance(chemin, (list, tuple)):
            commande = list(chemin)
        else:
            commande = str(chemin)
        self.commande = commande

        # popen_uci lance le programme et effectue la poignée de main UCI
        # (envoi de « uci », attente de « uciok »). On impose le répertoire de
        # travail : sans lui, « python -m moteur_maison.uci » ne trouverait pas
        # ses modules.
        self._moteur = chess.engine.SimpleEngine.popen_uci(
            commande, cwd=str(config.RACINE)
        )

        self.nom = self._moteur.id.get("name", "moteur inconnu")
        self._configurer(threads, hash_mo)
        if options:
            self._appliquer(options)

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #

    def _configurer(self, threads: int, hash_mo: int) -> None:
        """
        Applique les options UCI, en ignorant celles que le moteur ne connaît pas.

        Tous les moteurs n'exposent pas les mêmes options : notre moteur maison
        n'aura sans doute ni « Threads » ni « Hash » au début. On filtre donc sur
        ce que le moteur a effectivement déclaré savoir faire.
        """
        souhaitees = {"Threads": threads, "Hash": hash_mo}
        acceptees = {
            nom: valeur
            for nom, valeur in souhaitees.items()
            if nom in self._moteur.options
        }
        if acceptees:
            self._moteur.configure(acceptees)

    def _appliquer(self, options: dict) -> None:
        """Applique des options supplementaires, en ignorant les inconnues."""
        acceptees = {n: v for n, v in options.items() if n in self._moteur.options}
        if acceptees:
            self._moteur.configure(acceptees)

    def brider(self, elo: int | None) -> None:
        """
        Limite artificiellement la force du moteur, ou la libère si elo vaut None.

        Sert à deux choses :
          - jouer contre un adversaire à ta portée plutôt que contre 3600 Elo ;
          - créer un étalon de mesure : faire affronter notre moteur maison à un
            Stockfish bridé à 2000 Elo permet de savoir où l'on se situe vraiment.

        Stockfish accepte des valeurs comprises entre 1320 et 3190 environ.
        """
        if "UCI_LimitStrength" not in self._moteur.options:
            return
        if elo is None:
            self._moteur.configure({"UCI_LimitStrength": False})
        else:
            self._moteur.configure({"UCI_LimitStrength": True, "UCI_Elo": int(elo)})

    # ------------------------------------------------------------------ #
    # Analyse
    # ------------------------------------------------------------------ #

    @staticmethod
    def _limite(profondeur: int | None, temps: float | None) -> chess.engine.Limit:
        """
        Construit la condition d'arrêt de la réflexion.

        Deux façons d'arrêter un moteur :
          - à profondeur fixe : résultat reproductible, mais durée imprévisible ;
          - à temps fixe : durée maîtrisée, idéal pour une interface interactive.
        """
        if temps is not None:
            return chess.engine.Limit(time=temps)
        return chess.engine.Limit(depth=profondeur or config.PROFONDEUR_DEFAUT)

    def analyser(
        self,
        echiquier: chess.Board,
        profondeur: int | None = None,
        temps: float | None = None,
        nb_variantes: int = config.NB_VARIANTES,
    ) -> list[Variante]:
        """
        Analyse une position et renvoie les meilleures variantes, la n°1 en tête.

        Fonctionne pour les Blancs comme pour les Noirs sans rien changer : le
        moteur analyse toujours pour le camp au trait, indiqué par la position
        elle-même (le « w » ou le « b » dans la notation FEN).
        """
        if echiquier.is_game_over():
            return []

        # MultiPV = « donne-moi les N meilleures lignes », pas seulement la
        # meilleure. Attention : plus N est grand, plus l'analyse est lente, car
        # le moteur ne peut plus élaguer aussi agressivement les coups qu'il
        # juge inférieurs.
        infos = self._moteur.analyse(
            echiquier,
            self._limite(profondeur, temps),
            multipv=max(1, nb_variantes),
        )

        # Avec multipv, python-chess renvoie une liste ; sans, un dictionnaire seul.
        if isinstance(infos, dict):
            infos = [infos]

        variantes = []
        for rang, info in enumerate(infos, start=1):
            variantes.append(
                Variante(
                    rang=info.get("multipv", rang),
                    coups=list(info.get("pv", [])),
                    score=info["score"],
                    profondeur=info.get("depth", 0),
                )
            )
        return variantes

    def flux_analyse(
        self,
        echiquier: chess.Board,
        profondeur: int | None = None,
        temps: float | None = None,
        nb_variantes: int = config.NB_VARIANTES,
    ) -> chess.engine.SimpleAnalysisResult:
        """
        Lance une analyse en flux, que l'on peut lire au fur et à mesure et
        interrompre à tout moment.

        C'est la version dont a besoin l'interface graphique. `analyser()`
        attend la fin du calcul avant de rendre la main : la fenêtre serait
        figée pendant plusieurs secondes. Ici, le moteur publie ses résultats
        intermédiaires (profondeur 5, puis 6, puis 7...) et on peut couper net
        dès que l'utilisateur joue un autre coup.

        À utiliser dans un bloc `with`, qui garantit l'arrêt du calcul :

            with moteur.flux_analyse(echiquier) as flux:
                for info in flux:
                    ...
        """
        return self._moteur.analysis(
            echiquier,
            self._limite(profondeur, temps),
            multipv=max(1, nb_variantes),
        )

    def meilleur_coup(
        self,
        echiquier: chess.Board,
        profondeur: int | None = None,
        temps: float | None = None,
    ) -> chess.Move | None:
        """Raccourci : le seul meilleur coup, sans les variantes secondaires."""
        resultat = self._moteur.play(echiquier, self._limite(profondeur, temps))
        return resultat.move

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #

    def fermer(self) -> None:
        """Termine proprement le sous-processus du moteur."""
        try:
            self._moteur.quit()
        except chess.engine.EngineTerminatedError:
            pass  # déjà mort, rien à faire

    def __enter__(self) -> "MoteurUCI":
        return self

    def __exit__(self, *_) -> None:
        self.fermer()
