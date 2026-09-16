"""
La façade UCI : ce qui rend notre moteur interchangeable avec Stockfish.

Lancement (rarement à la main, c'est l'interface qui s'en charge) :
    python -m moteur_maison.uci

--- Ce que fait ce fichier ---
Il lit des commandes texte sur l'entrée standard, pilote la recherche, et écrit
les réponses sur la sortie standard. Rien de plus. C'est ce contrat minimal qui
permet à n'importe quelle interface d'échecs du monde d'utiliser notre moteur,
et à notre interface d'utiliser n'importe quel moteur.

--- Le point délicat : deux fils d'exécution ---
La commande `stop` doit pouvoir arriver PENDANT que le moteur réfléchit. Si la
recherche tournait dans le fil principal, on ne lirait plus l'entrée standard et
`stop` ne serait traité qu'une fois la réflexion finie — c'est-à-dire trop tard.
La recherche tourne donc dans un fil secondaire, et le fil principal ne fait
qu'écouter les commandes.

Conséquence : deux fils peuvent vouloir écrire en même temps. D'où le verrou
autour de chaque écriture, sans lequel une ligne « info » pourrait se retrouver
coupée en deux par un « bestmove ».
"""

from __future__ import annotations

import sys
import threading

import chess

from moteur_maison.recherche import SEUIL_MAT, MAT, Contraintes, Recherche, Resultat

NOM = "Moteur Maison 4c"
AUTEUR = "picheret.m"

# Bornes de l'option MultiPV proposée à l'interface.
MULTIPV_MAX = 5


class ServeurUCI:
    """Traduit le protocole UCI en appels à notre moteur de recherche."""

    def __init__(self):
        self.echiquier = chess.Board()
        self.recherche = Recherche(sur_profondeur=self._publier)
        self.multipv = 1

        self._fil: threading.Thread | None = None
        self._verrou_sortie = threading.Lock()

    # ------------------------------------------------------------------ #
    # Sortie
    # ------------------------------------------------------------------ #

    def _ecrire(self, ligne: str) -> None:
        """Écrit une ligne et la pousse immédiatement : l'interface attend."""
        with self._verrou_sortie:
            sys.stdout.write(ligne + "\n")
            sys.stdout.flush()

    def _publier(self, resultat: Resultat) -> None:
        """
        Publie une ligne « info » par variante, à chaque profondeur atteinte.

        C'est ce flux qui alimente l'affichage progressif de l'interface :
        l'évaluation qui se précise sous les yeux de l'utilisateur.
        """
        temps_ms = max(1, int(resultat.temps * 1000))
        nps = int(resultat.noeuds / resultat.temps) if resultat.temps > 0 else 0

        for rang, ligne in enumerate(resultat.lignes, start=1):
            # UCI distingue un score en centipions d'un mat annoncé.
            mat = ligne.mat_en()
            score = f"mate {mat}" if mat is not None else f"cp {ligne.score}"
            pv = " ".join(coup.uci() for coup in ligne.pv) or ligne.coup.uci()

            self._ecrire(
                f"info depth {resultat.profondeur} multipv {rang} score {score} "
                f"nodes {resultat.noeuds} nps {nps} time {temps_ms} pv {pv}"
            )

    # ------------------------------------------------------------------ #
    # Boucle de commandes
    # ------------------------------------------------------------------ #

    def executer(self) -> None:
        for ligne in sys.stdin:
            commande = ligne.strip()
            if not commande:
                continue

            mot = commande.split(maxsplit=1)[0]

            if mot == "uci":
                self._presenter()
            elif mot == "isready":
                self._ecrire("readyok")
            elif mot == "ucinewgame":
                self.echiquier = chess.Board()
                # Nouvelle partie : ce que la table retient de la precedente
                # n'a plus aucune valeur.
                self.recherche.tt.vider()
            elif mot == "setoption":
                self._option(commande)
            elif mot == "position":
                self._position(commande)
            elif mot == "go":
                self._go(commande)
            elif mot == "stop":
                self.recherche.arret.set()
            elif mot == "quit":
                self.recherche.arret.set()
                break

    def _presenter(self) -> None:
        self._ecrire(f"id name {NOM}")
        self._ecrire(f"id author {AUTEUR}")
        self._ecrire(
            f"option name MultiPV type spin default 1 min 1 max {MULTIPV_MAX}"
        )
        # Interrupteur destine a la mesure : il permet de faire jouer la
        # version 4a contre la version 4b sans maintenir deux programmes.
        self._ecrire("option name TT type check default true")
        self._ecrire("option name Tri type check default true")
        self._ecrire("option name Elagage type check default true")
        self._ecrire("uciok")

    def _option(self, commande: str) -> None:
        """Traite « setoption name X value Y »."""
        morceaux = commande.split()
        if "name" not in morceaux or "value" not in morceaux:
            return
        nom = " ".join(morceaux[morceaux.index("name") + 1: morceaux.index("value")])
        valeur = " ".join(morceaux[morceaux.index("value") + 1:])

        if nom == "MultiPV":
            try:
                self.multipv = max(1, min(MULTIPV_MAX, int(valeur)))
            except ValueError:
                pass
        elif nom == "TT":
            self.recherche.utiliser_tt = valeur.strip().lower() == "true"
        elif nom == "Tri":
            # Killers, historique, aspiration et fenetre nulle : tout l'apport
            # de l'etape 4b-2, en un seul interrupteur pour la mesure.
            self.recherche.utiliser_tri = valeur.strip().lower() == "true"
        elif nom == "Elagage":
            # Coup nul, LMR et futility inversee : l'etape 4c.
            self.recherche.utiliser_elagage = valeur.strip().lower() == "true"

    def _position(self, commande: str) -> None:
        """
        Traite « position startpos moves e2e4 e7e5 » ou « position fen ... ».

        On rejoue les coups un par un plutôt que de sauter à la position finale :
        c'est ce qui donne au moteur l'historique dont il a besoin pour détecter
        les répétitions.
        """
        morceaux = commande.split()

        if "startpos" in morceaux:
            self.echiquier = chess.Board()
        elif "fen" in morceaux:
            debut = morceaux.index("fen") + 1
            fin = morceaux.index("moves") if "moves" in morceaux else len(morceaux)
            self.echiquier = chess.Board(" ".join(morceaux[debut:fin]))
        else:
            return

        if "moves" in morceaux:
            for uci in morceaux[morceaux.index("moves") + 1:]:
                try:
                    self.echiquier.push_uci(uci)
                except ValueError:
                    break  # coup illégal : on s'arrête là plutôt que de planter

    # ------------------------------------------------------------------ #
    # Réflexion
    # ------------------------------------------------------------------ #

    def _go(self, commande: str) -> None:
        # Une réflexion déjà en cours doit se terminer avant d'en lancer une autre.
        if self._fil is not None and self._fil.is_alive():
            self.recherche.arret.set()
            self._fil.join()

        contraintes = self._contraintes(commande)
        self.recherche.arret.clear()

        self._fil = threading.Thread(target=self._reflechir, args=(contraintes,), daemon=True)
        self._fil.start()

    def _contraintes(self, commande: str) -> Contraintes:
        """Traduit les nombreuses formes de « go » en une seule structure."""
        morceaux = commande.split()

        def valeur(cle: str) -> int | None:
            if cle in morceaux:
                try:
                    return int(morceaux[morceaux.index(cle) + 1])
                except (IndexError, ValueError):
                    return None
            return None

        contraintes = Contraintes(multipv=self.multipv)

        if "infinite" in morceaux:
            return contraintes

        profondeur = valeur("depth")
        if profondeur is not None:
            contraintes.profondeur_max = profondeur

        noeuds = valeur("nodes")
        if noeuds is not None:
            contraintes.noeuds_max = noeuds

        mouvement = valeur("movetime")
        if mouvement is not None:
            contraintes.temps_max = mouvement / 1000.0
            return contraintes

        # Cadence de partie : l'interface donne le temps restant à chaque camp.
        blancs = self.echiquier.turn == chess.WHITE
        restant = valeur("wtime" if blancs else "btime")
        increment = valeur("winc" if blancs else "binc") or 0

        if restant is not None:
            contraintes.temps_max = self._budget(restant, increment)

        return contraintes

    @staticmethod
    def _budget(restant_ms: int, increment_ms: int) -> float:
        """
        Combien de temps consacrer à ce coup.

        Règle simple et robuste : un trentième du temps restant, plus la
        quasi-totalité de l'incrément. Le diviseur 30 suppose qu'il reste une
        trentaine de coups à jouer, ce qui est une bonne approximation en
        milieu de partie. La marge de sécurité évite de perdre au temps sur un
        coup qui déborde légèrement.
        """
        budget = restant_ms / 30.0 + increment_ms * 0.8
        plafond = restant_ms * 0.4          # ne jamais risquer plus de 40 % du reste
        marge = 50                          # de quoi transmettre la réponse
        return max(0.01, min(budget, plafond, restant_ms - marge) / 1000.0)

    def _reflechir(self, contraintes: Contraintes) -> None:
        """Exécuté dans le fil secondaire : cherche, puis annonce le coup."""
        try:
            resultat = self.recherche.chercher(self.echiquier, contraintes)
            coup = resultat.meilleur_coup
        except Exception:
            coup = None

        # Un moteur UCI DOIT toujours répondre un bestmove, même en catastrophe :
        # sans réponse, l'interface attend indéfiniment.
        if coup is None:
            legaux = list(self.echiquier.legal_moves)
            coup = legaux[0] if legaux else None

        self._ecrire(f"bestmove {coup.uci() if coup else '0000'}")


def main() -> None:
    ServeurUCI().executer()


if __name__ == "__main__":
    main()
