"""
L'application d'analyse : assemblage de toutes les briques.

Lancement :
    python -m interface.app

Ce fichier tient le rôle de chef d'orchestre. Il ne calcule rien lui-même :
  - les règles du jeu viennent de python-chess ;
  - l'état de la partie vient de noyau/partie.py ;
  - l'évaluation vient du moteur, via noyau/analyse_continue.py ;
  - le dessin est délégué aux classes de interface/.
Son travail est de recevoir les actions de l'utilisateur, de les traduire en
changements d'état, et de redemander une analyse quand la position change.
"""

from __future__ import annotations

import sys

import chess
import pygame

from interface import presse_papier, theme
from interface.barre_eval import BarreEval
from interface.echiquier_vue import VueEchiquier
from interface.panneau import Panneau
from noyau import config, notation
from noyau.adversaire import Adversaire
from noyau.analyse_continue import AnalyseContinue
from noyau.partie import Partie

# Profondeur minimale avant de juger un coup. En dessous, l'évaluation est trop
# grossière et l'on qualifierait de « gaffe » un coup parfaitement correct.
PROFONDEUR_JUGEMENT = 12

# Ordre des pièces proposées lors d'une promotion.
CHOIX_PROMOTION = (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)

# Correspondance entre la pastille « FORCE » et la valeur passée à UCI_Elo.
# None signifie « pas de bridage », donc pleine puissance.
FORCES = {"max": None, "2000": 2000, "1500": 1500}


class Application:
    """Fenêtre d'analyse : échiquier jouable, barre d'évaluation, panneau moteur."""

    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Bot Chess — Analyse")

        self.ecran = pygame.display.set_mode(theme.FENETRE_DEFAUT, pygame.RESIZABLE)
        self.disposition = theme.calculer(*theme.FENETRE_DEFAUT)

        self.vue = VueEchiquier(self.disposition)
        self.barre = BarreEval()
        self.panneau = Panneau()

        self.partie = Partie()
        self.echiquier = self.partie.echiquier()

        # Réglages pilotés par les pastilles du panneau.
        self.reglages = {"mode": "analyse", "moteur": "stockfish", "force": "max"}
        self.analyse: AnalyseContinue | None = None
        self.adversaire: Adversaire | None = None

        # --- état de l'interaction ---
        self.case_saisie: chess.Square | None = None   # pièce tenue à la souris
        self.selection: chess.Square | None = None     # case cliquée (mode clic-clic)
        self.destinations: set[chess.Square] = set()
        self.promotion: tuple[chess.Square, chess.Square] | None = None
        self.message = ""

        # --- état de l'analyse ---
        self.resultat = None
        self.dernier_score = None            # conservé pour éviter que la barre clignote
        self._jugement_attendu: tuple[int, float, bool] | None = None

        self.horloge = pygame.time.Clock()
        self.actif = True
        self._appliquer_reglages()

    # ------------------------------------------------------------------ #
    # Boucle principale
    # ------------------------------------------------------------------ #

    def executer(self) -> None:
        while self.actif:
            for evenement in pygame.event.get():
                self._traiter(evenement)

            if self.reglages["mode"] == "analyse":
                self._recuperer_analyse()
            else:
                self._tour_du_bot()

            self._dessiner()
            # 60 images par seconde : fluide, et sans monopoliser un cœur.
            self.horloge.tick(60)

        self._fermer_moteurs()
        pygame.quit()

    # ------------------------------------------------------------------ #
    # Moteurs
    # ------------------------------------------------------------------ #

    def _fermer_moteurs(self) -> None:
        """Ferme proprement les sous-processus encore ouverts."""
        if self.analyse is not None:
            self.analyse.arreter()
            self.analyse = None
        if self.adversaire is not None:
            self.adversaire.arreter()
            self.adversaire = None

    def _appliquer_reglages(self) -> None:
        """
        (Re)démarre le moteur correspondant aux pastilles choisies.

        Un seul moteur tourne à la fois : celui qui analyse en mode Analyse,
        celui qui joue en mode Partie. C'est délibéré — notre moteur maison est
        lent, autant lui laisser la machine entière quand c'est son tour.
        """
        self._fermer_moteurs()

        maison = self.reglages["moteur"] == "maison"
        chemin = config.commande_moteur_maison() if maison else None
        # Le bridage par Elo est une option propre à Stockfish ; notre moteur
        # maison n'en dispose pas, et joue donc toujours à pleine puissance.
        elo = None if maison else FORCES[self.reglages["force"]]

        if self.reglages["mode"] == "analyse":
            self.analyse = AnalyseContinue(
                chemin=chemin,
                temps_max=config.TEMPS_ANALYSE_MAISON if maison else None,
                elo=elo,
            )
            self._relancer_analyse()
        else:
            self.adversaire = Adversaire(
                chemin=chemin, elo=elo, temps=config.TEMPS_ADVERSAIRE
            )
            self.resultat = None
            self.dernier_score = None

    def _nom_moteur(self) -> str:
        if self.analyse is not None:
            return self.analyse.erreur or self.analyse.nom_moteur
        if self.adversaire is not None:
            return self.adversaire.erreur or self.adversaire.nom
        return "aucun moteur"

    # ------------------------------------------------------------------ #
    # Mode partie
    # ------------------------------------------------------------------ #

    def _camp_bot(self) -> chess.Color:
        """
        Le bot joue le camp d'en haut ; tu joues celui d'en bas.

        Aucun réglage supplémentaire n'est nécessaire : la touche F, qui
        retourne l'échiquier, change donc aussi de camp. C'est la convention
        de chess.com et de Lichess.
        """
        return chess.WHITE if self.vue.retourne else chess.BLACK

    def _bot_au_trait(self) -> bool:
        return (
            self.reglages["mode"] == "partie"
            and self.partie.au_bout()
            and self.echiquier.turn == self._camp_bot()
            and not self.echiquier.is_game_over()
        )

    def _tour_du_bot(self) -> None:
        """Fait jouer le moteur quand c'est son tour, sans bloquer l'affichage."""
        if self.adversaire is None or not self.adversaire.pret.is_set():
            return

        # Un coup est arrivé : on le joue.
        coup = self.adversaire.coup_pret()
        if coup is not None and self._bot_au_trait():
            self.partie.jouer(coup)
            self._position_changee()
            return

        if self._bot_au_trait() and not self.adversaire.reflechit():
            self.adversaire.demander(self.echiquier)

    def _texte_partie(self) -> str:
        """Phrase décrivant où en est la partie, affichée dans le panneau."""
        issue = self.echiquier.outcome()
        if issue is not None:
            if issue.winner is None:
                return f"Partie nulle ({self._raison(issue)})."
            gagnant = "Blancs" if issue.winner == chess.WHITE else "Noirs"
            vainqueur = "toi" if issue.winner != self._camp_bot() else "le moteur"
            return f"Les {gagnant} gagnent — {vainqueur}."
        if not self.partie.au_bout():
            return "Revue d'un coup passé — Fin pour reprendre."
        if self.echiquier.turn == self._camp_bot():
            return f"{self._nom_moteur()} réfléchit…"
        return "À toi de jouer."

    @staticmethod
    def _raison(issue: chess.Outcome) -> str:
        return {
            chess.Termination.STALEMATE: "pat",
            chess.Termination.INSUFFICIENT_MATERIAL: "matériel insuffisant",
            chess.Termination.FIFTYMOVE: "règle des 50 coups",
            chess.Termination.THREEFOLD_REPETITION: "triple répétition",
        }.get(issue.termination, "nulle")

    # ------------------------------------------------------------------ #
    # Évènements
    # ------------------------------------------------------------------ #

    def _traiter(self, ev: pygame.event.Event) -> None:
        if ev.type == pygame.QUIT:
            self.actif = False

        elif ev.type == pygame.VIDEORESIZE:
            self._redimensionner(ev.w, ev.h)

        elif ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == 1:
                self._clic_gauche(ev.pos)
            elif ev.button == 3:
                self._annuler_saisie()

        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self._relacher(ev.pos)

        elif ev.type == pygame.MOUSEWHEEL:
            self.panneau.defiler(ev.y)

        elif ev.type == pygame.KEYDOWN:
            self._touche(ev)

    def _redimensionner(self, largeur: int, hauteur: int) -> None:
        largeur = max(largeur, theme.FENETRE_MINI[0])
        hauteur = max(hauteur, theme.FENETRE_MINI[1])
        self.ecran = pygame.display.set_mode((largeur, hauteur), pygame.RESIZABLE)
        self.disposition = theme.calculer(largeur, hauteur)
        # Les images de pièces sont refabriquées à la nouvelle taille de case.
        self.vue.maj_disposition(self.disposition)

    # -- souris ---------------------------------------------------------- #

    def _clic_gauche(self, position: tuple[int, int]) -> None:
        # Une promotion en attente monopolise les clics.
        if self.promotion is not None:
            self._clic_promotion(position)
            return

        # Clic sur une pastille de réglage.
        controle = self.panneau.controle_sous(position)
        if controle is not None:
            groupe, valeur = controle
            if self.reglages.get(groupe) != valeur:
                self.reglages[groupe] = valeur
                self._annuler_saisie()
                self._appliquer_reglages()
            return

        # Clic dans la liste des coups : navigation.
        index = self.panneau.coup_sous(position)
        if index is not None:
            self.partie.aller_a(index)
            self._position_changee()
            return

        # En mode partie, on ne touche pas aux pièces du moteur.
        if self._bot_au_trait():
            return

        case = self.vue.case_sous(position)
        if case is None:
            return

        # Deuxième clic du mode « clic-clic » : on tente le coup.
        if self.selection is not None and case in self.destinations:
            self._tenter_coup(self.selection, case)
            return

        piece = self.echiquier.piece_at(case)
        if piece is not None and piece.color == self.echiquier.turn:
            self.selection = case
            self.case_saisie = case
            self.destinations = {
                c.to_square for c in self.echiquier.legal_moves if c.from_square == case
            }
        else:
            self._annuler_saisie()

    def _relacher(self, position: tuple[int, int]) -> None:
        """
        Fin d'un glisser-déposer.

        Subtilité : si l'on relâche sur la case de départ, c'est que l'on a
        simplement cliqué sur la pièce. On garde alors la sélection active pour
        permettre le mode clic-clic, au lieu de tout annuler.
        """
        if self.case_saisie is None:
            return

        depart = self.case_saisie
        self.case_saisie = None

        case = self.vue.case_sous(position)
        if case is None or case == depart:
            return
        if case in self.destinations:
            self._tenter_coup(depart, case)

    def _annuler_saisie(self) -> None:
        self.case_saisie = None
        self.selection = None
        self.destinations = set()
        self.promotion = None

    # -- clavier --------------------------------------------------------- #

    def _touche(self, ev: pygame.event.Event) -> None:
        ctrl = ev.mod & pygame.KMOD_CTRL

        if ev.key == pygame.K_ESCAPE:
            self._annuler_saisie()
        elif ctrl and ev.key == pygame.K_c:
            presse_papier.ecrire(self.echiquier.fen())
            self.message = "FEN copiée dans le presse-papier."
        elif ctrl and ev.key == pygame.K_v:
            self._coller()
        elif ctrl and ev.key == pygame.K_n:
            self.partie = Partie()
            self._position_changee()
            self.message = ""
        elif ctrl and ev.key == pygame.K_z:
            if self.partie.annuler():
                self._position_changee()
        elif ev.key == pygame.K_LEFT:
            self.partie.precedent()
            self._position_changee()
        elif ev.key == pygame.K_RIGHT:
            self.partie.suivant()
            self._position_changee()
        elif ev.key == pygame.K_HOME:
            self.partie.debut()
            self._position_changee()
        elif ev.key == pygame.K_END:
            self.partie.fin()
            self._position_changee()
        elif ev.key == pygame.K_f:
            self.vue.retourner()
        elif ev.key == pygame.K_SPACE:
            self._jouer_coup_moteur()

    def _coller(self) -> None:
        """
        Charge une position depuis le presse-papier.

        On accepte aussi bien une FEN qu'un PGN complet : le format est deviné
        à l'essai, ce qui évite à l'utilisateur d'avoir à le préciser.
        """
        contenu = presse_papier.lire().strip()
        if not contenu:
            self.message = "Presse-papier vide."
            return

        for charger, libelle in ((Partie.depuis_fen, "FEN"), (Partie.depuis_pgn, "PGN")):
            try:
                self.partie = charger(contenu)
                self._position_changee()
                self.message = f"{libelle} chargé."
                return
            except (ValueError, IndexError):
                continue

        self.message = "Contenu non reconnu (ni FEN, ni PGN)."

    def _jouer_coup_moteur(self) -> None:
        """Joue le meilleur coup trouvé, pour dérouler une variante rapidement."""
        if self.resultat and self.resultat.variantes:
            coup = self.resultat.variantes[0].coup
            if coup is not None:
                self._jouer(coup)

    # ------------------------------------------------------------------ #
    # Coups
    # ------------------------------------------------------------------ #

    def _tenter_coup(self, depart: chess.Square, arrivee: chess.Square) -> None:
        """Joue le coup, ou ouvre le choix de promotion s'il y a lieu."""
        coup = chess.Move(depart, arrivee)

        # Un coup de pion vers la dernière rangée n'est légal qu'accompagné
        # d'une pièce de promotion : `chess.Move(e7, e8)` est illégal, seul
        # `chess.Move(e7, e8, promotion=QUEEN)` l'est.
        if coup not in self.echiquier.legal_moves:
            avec_dame = chess.Move(depart, arrivee, promotion=chess.QUEEN)
            if avec_dame in self.echiquier.legal_moves:
                self.promotion = (depart, arrivee)
                self.case_saisie = None
                return
            self._annuler_saisie()
            return

        self._jouer(coup)

    def _clic_promotion(self, position: tuple[int, int]) -> None:
        """Traite le clic sur la petite fenêtre de choix de promotion."""
        for rect, type_piece in self._zones_promotion():
            if rect.collidepoint(position):
                depart, arrivee = self.promotion
                self.promotion = None
                self._jouer(chess.Move(depart, arrivee, promotion=type_piece))
                return
        self._annuler_saisie()

    def _jouer(self, coup: chess.Move) -> None:
        """Joue un coup et prépare le jugement que le moteur portera dessus."""
        # On mémorise l'évaluation AVANT le coup, du point de vue de celui qui
        # joue. Sans cette photo prise à temps, impossible de mesurer ensuite ce
        # que le coup a coûté.
        avant = None
        if self.resultat and self.resultat.fen == self.echiquier.fen() \
                and self.resultat.variantes and self.resultat.profondeur >= PROFONDEUR_JUGEMENT:
            joueur = self.echiquier.turn
            meilleur = self.resultat.variantes[0].coup
            avant = (
                notation.probabilite_victoire(self.resultat.variantes[0].score.pov(joueur)),
                coup == meilleur,
            )

        if not self.partie.jouer(coup):
            self._annuler_saisie()
            return

        index = self.partie.index - 1
        self._position_changee()
        # L'ordre compte : _position_changee() efface tout jugement en attente,
        # justement pour qu'un aller-retour dans la partie ne vienne pas coller
        # une note au mauvais coup. On enregistre donc la nôtre juste après.
        if avant is not None:
            self._jugement_attendu = (index, avant[0], avant[1])

    # ------------------------------------------------------------------ #
    # Analyse
    # ------------------------------------------------------------------ #

    def _position_changee(self) -> None:
        """À appeler après toute modification de la partie ou de la navigation."""
        self.echiquier = self.partie.echiquier()
        self._annuler_saisie()
        self.message = ""
        # Un jugement en attente ne concerne plus la position affichée.
        self._jugement_attendu = None
        self._relancer_analyse()

    def _relancer_analyse(self) -> None:
        self.resultat = None
        if self.analyse is not None:
            self.analyse.demander(self.echiquier)

    def _recuperer_analyse(self) -> None:
        """Récupère le dernier résultat publié par le fil d'analyse."""
        if self.analyse is None:
            return
        resultat = self.analyse.resultat()
        if resultat is None or resultat.fen != self.echiquier.fen():
            return

        self.resultat = resultat
        if resultat.variantes:
            self.dernier_score = resultat.variantes[0].score_blancs()
        self._juger_si_possible(resultat)

    def _juger_si_possible(self, resultat) -> None:
        """
        Attribue un jugement au coup qui vient d'être joué.

        On compare la probabilité de victoire du joueur avant son coup à celle
        qu'il a après. La différence est ce que le coup lui a coûté. On attend
        que l'analyse soit assez profonde pour que la comparaison ait un sens.
        """
        if self._jugement_attendu is None or not resultat.variantes:
            return
        if resultat.profondeur < PROFONDEUR_JUGEMENT:
            return

        index, proba_avant, etait_meilleur = self._jugement_attendu
        if index >= len(self.partie.coups):
            self._jugement_attendu = None
            return

        # Le coup a été joué par le camp qui n'est PAS au trait maintenant.
        joueur = not self.echiquier.turn
        score_apres = resultat.variantes[0].score.pov(joueur)
        proba_apres = notation.probabilite_victoire(score_apres)

        jugement, perte = notation.classer_coup(proba_avant, proba_apres, etait_meilleur)
        entree = self.partie.coups[index]
        entree.jugement = jugement
        entree.perte = perte
        entree.eval_apres = resultat.variantes[0].score_blancs()

        if jugement in ("Erreur", "Gaffe"):
            self.message = f"{entree.san} : {jugement.lower()} (−{perte:.0%} de chances)."
        elif jugement == "Meilleur coup":
            self.message = f"{entree.san} : meilleur coup."
        else:
            self.message = f"{entree.san} : {jugement.lower()}."

        self._jugement_attendu = None

    # ------------------------------------------------------------------ #
    # Dessin
    # ------------------------------------------------------------------ #

    def _dessiner(self) -> None:
        self.ecran.fill(theme.FOND)

        # En mode partie, la barre reste neutre : afficher l'évaluation
        # reviendrait à jouer avec la réponse sous les yeux.
        score_barre = None if self.reglages["mode"] == "partie" else self.dernier_score
        self.barre.dessiner(self.ecran, self.disposition, score_barre, self.vue.retourne)

        self.vue.dessiner(
            self.ecran,
            self.echiquier,
            dernier_coup=self.partie.dernier_coup(),
            selection=self.selection,
            destinations=self.destinations,
            fleches=self._fleches(),
            case_saisie=self.case_saisie,
            souris=pygame.mouse.get_pos(),
        )

        self.panneau.dessiner(
            self.ecran,
            self.disposition,
            self.partie,
            self.echiquier,
            self.resultat,
            self._nom_moteur(),
            self.message,
            reglages=self.reglages,
            etat_partie=self._texte_partie() if self.reglages["mode"] == "partie" else "",
        )

        if self.promotion is not None:
            self._dessiner_promotion()

        pygame.display.flip()

    def _fleches(self) -> list[tuple[chess.Square, chess.Square, tuple]]:
        """Flèches des coups recommandés, dans les couleurs du panneau."""
        if not self.resultat or self.case_saisie is not None:
            return []  # on masque les flèches pendant qu'on déplace une pièce
        fleches = []
        for i, variante in enumerate(self.resultat.variantes[: len(theme.FLECHES)]):
            if variante.coup is not None:
                fleches.append((variante.coup.from_square, variante.coup.to_square,
                                theme.FLECHES[i]))
        return fleches

    def _zones_promotion(self) -> list[tuple[pygame.Rect, int]]:
        """
        Rectangles cliquables du choix de promotion.

        Les quatre pièces sont empilées à partir de la case d'arrivée, en
        s'éloignant du bord de l'échiquier pour rester visibles.
        """
        if self.promotion is None:
            return []

        _, arrivee = self.promotion
        rect = self.vue.rect_case(arrivee)
        c = self.disposition.case

        # Vers le bas si la case d'arrivée est en haut de l'écran, sinon vers le haut.
        haut_ecran = rect.y < self.disposition.echiquier[1] + self.disposition.cote / 2
        sens = 1 if haut_ecran else -1

        zones = []
        for i, type_piece in enumerate(CHOIX_PROMOTION):
            y = rect.y + sens * i * c
            zones.append((pygame.Rect(rect.x, y, c, c), type_piece))
        return zones

    def _dessiner_promotion(self) -> None:
        from interface import pieces

        _, arrivee = self.promotion
        couleur = self.echiquier.turn
        c = self.disposition.case

        # Voile sombre sur tout l'échiquier pour concentrer l'attention.
        x0, y0 = self.disposition.echiquier
        voile = pygame.Surface((self.disposition.cote,) * 2, pygame.SRCALPHA)
        voile.fill((0, 0, 0, 120))
        self.ecran.blit(voile, (x0, y0))

        for rect, type_piece in self._zones_promotion():
            pygame.draw.rect(self.ecran, theme.PANNEAU_CLAIR, rect, border_radius=6)
            pygame.draw.rect(self.ecran, theme.BORDURE, rect, width=2, border_radius=6)
            image = pieces.image(chess.Piece(type_piece, couleur), c)
            self.ecran.blit(image, rect.topleft)


def main() -> None:
    try:
        Application().executer()
    except FileNotFoundError as erreur:
        print(erreur)
        sys.exit(1)


if __name__ == "__main__":
    main()
