"""
Le panneau latéral : ce que pense le moteur, et la liste des coups joués.

Trois blocs empilés :
  1. l'en-tête    -> quel moteur tourne, à quelle profondeur, à quelle vitesse ;
  2. les variantes -> les meilleurs coups de la position affichée ;
  3. la partie     -> tous les coups joués, cliquables pour naviguer.

Le panneau est purement visuel : il dessine, et il sait dire sur quel coup on a
cliqué. Il ne modifie jamais la partie lui-même.
"""

from __future__ import annotations

import chess
import pygame

from interface import theme
from interface.theme import Disposition
from noyau import notation
from noyau.analyse_continue import Resultat
from noyau.partie import Partie

# Hauteurs fixes des différentes zones, en pixels.
H_ENTETE = 46
H_LIGNE_VARIANTE = 42
H_TITRE = 26
H_RANGEE_COUP = 26
H_AIDE = 78
H_RANGEE_CONTROLE = 28
H_PASTILLE = 21

# Les réglages cliquables du panneau. Chaque entrée est :
#   (libellé de la rangée, nom du groupe, [(texte affiché, valeur interne), ...])
# Le panneau ne fait que les dessiner et dire lequel a été cliqué ; c'est
# l'application qui décide de ce que chaque réglage déclenche.
CONTROLES = [
    ("MODE", "mode", [("Analyse", "analyse"), ("Partie", "partie")]),
    ("MOTEUR", "moteur", [("Stockfish", "stockfish"), ("Maison", "maison")]),
    ("FORCE", "force", [("Max", "max"), ("2000", "2000"), ("1500", "1500")]),
]
H_CONTROLES = H_TITRE + len(CONTROLES) * H_RANGEE_CONTROLE + 6


class Panneau:
    """Affiche l'analyse et la liste des coups."""

    def __init__(self):
        self.titre = pygame.font.Font(theme.POLICE_UI_GRAS, 12)
        self.normal = pygame.font.Font(theme.POLICE_UI, 14)
        self.gras = pygame.font.Font(theme.POLICE_UI_GRAS, 15)
        self.petit = pygame.font.Font(theme.POLICE_UI, 12)
        self.mono = pygame.font.Font(theme.POLICE_UI, 13)

        self.defilement = 0            # décalage vertical de la liste des coups
        self._zones_coups: list[tuple[pygame.Rect, int]] = []
        self._zone_liste = pygame.Rect(0, 0, 0, 0)
        self._hauteur_liste_totale = 0
        self._zones_controles: list[tuple[pygame.Rect, str, str]] = []

    # ------------------------------------------------------------------ #
    # Interaction
    # ------------------------------------------------------------------ #

    def controle_sous(self, point: tuple[int, int]) -> tuple[str, str] | None:
        """Réglage cliqué, sous la forme (groupe, valeur), ou None."""
        for rect, groupe, valeur in self._zones_controles:
            if rect.collidepoint(point):
                return groupe, valeur
        return None

    def coup_sous(self, point: tuple[int, int]) -> int | None:
        """
        Index de navigation correspondant au coup cliqué, ou None.

        L'index renvoyé est celui à passer à `Partie.aller_a()` : après le
        coup n°0 de la liste, on veut voir la position à l'index 1.
        """
        if not self._zone_liste.collidepoint(point):
            return None
        for rect, index in self._zones_coups:
            if rect.collidepoint(point):
                return index + 1
        return None

    def defiler(self, crans: int) -> None:
        """Fait défiler la liste des coups à la molette."""
        pas = H_RANGEE_COUP * 2
        maxi = max(0, self._hauteur_liste_totale - self._zone_liste.height)
        self.defilement = max(0, min(self.defilement - crans * pas, maxi))

    # ------------------------------------------------------------------ #
    # Dessin
    # ------------------------------------------------------------------ #

    def dessiner(
        self,
        surface: pygame.Surface,
        disposition: Disposition,
        partie: Partie,
        echiquier: chess.Board,
        resultat: Resultat | None,
        nom_moteur: str,
        message: str = "",
        reglages: dict[str, str] | None = None,
        etat_partie: str = "",
    ) -> None:
        x, y, largeur, hauteur = disposition.panneau
        pygame.draw.rect(surface, theme.PANNEAU, (x, y, largeur, hauteur), border_radius=6)

        reglages = reglages or {}
        en_partie = reglages.get("mode") == "partie"

        curseur = y
        curseur = self._entete(surface, x, curseur, largeur, nom_moteur, resultat, en_partie)
        curseur = self._controles(surface, x, curseur, largeur, reglages)

        # En mode partie, afficher les meilleurs coups reviendrait à jouer avec
        # la solution sous les yeux : on montre l'état de la partie à la place.
        if en_partie:
            curseur = self._etat_partie(surface, x, curseur, largeur, etat_partie)
        else:
            curseur = self._variantes(surface, x, curseur, largeur, echiquier, resultat)

        bas_liste = y + hauteur - H_AIDE
        self._liste_coups(surface, x, curseur, largeur, bas_liste - curseur, partie)
        self._aide(surface, x, bas_liste, largeur, H_AIDE, message)

    # -- réglages cliquables ---------------------------------------------- #

    def _controles(self, surface, x, y, largeur, reglages: dict) -> int:
        """Dessine les rangées de pastilles et mémorise leurs zones cliquables."""
        self._section(surface, x, y, "RÉGLAGES")
        y += H_TITRE
        self._zones_controles = []

        for rangee, (libelle, groupe, options) in enumerate(CONTROLES):
            ry = y + rangee * H_RANGEE_CONTROLE
            surface.blit(self.petit.render(libelle, True, theme.TEXTE_DOUX), (x + 14, ry + 4))

            px = x + 84
            for texte, valeur in options:
                largeur_p = self.petit.size(texte)[0] + 18
                rect = pygame.Rect(px, ry, largeur_p, H_PASTILLE)
                actif = reglages.get(groupe) == valeur

                fond = theme.CLASSEMENT["Excellent"] if actif else theme.PANNEAU_CLAIR
                couleur_texte = theme.TEXTE_SOMBRE if actif else theme.TEXTE_DOUX
                pygame.draw.rect(surface, fond, rect, border_radius=10)

                rendu = self.petit.render(texte, True, couleur_texte)
                surface.blit(rendu, (rect.centerx - rendu.get_width() // 2, rect.y + 3))

                self._zones_controles.append((rect, groupe, valeur))
                px += largeur_p + 6

        return y + len(CONTROLES) * H_RANGEE_CONTROLE + 6

    # -- état de la partie en cours ---------------------------------------- #

    def _etat_partie(self, surface, x, y, largeur, texte: str) -> int:
        self._section(surface, x, y, "PARTIE EN COURS")
        y += H_TITRE
        rendu = self.gras.render(self._tronquer(self.gras, texte, largeur - 28),
                                 True, theme.TEXTE)
        surface.blit(rendu, (x + 14, y + 6))
        return y + H_LIGNE_VARIANTE

    # -- en-tête --------------------------------------------------------- #

    def _entete(self, surface, x, y, largeur, nom_moteur, resultat, en_partie=False) -> int:
        pygame.draw.rect(surface, theme.PANNEAU_CLAIR, (x, y, largeur, H_ENTETE),
                         border_top_left_radius=6, border_top_right_radius=6)

        nom = self.gras.render(nom_moteur, True, theme.TEXTE)
        surface.blit(nom, (x + 14, y + 6))

        if en_partie:
            etat = "analyse suspendue pendant la partie"
        elif resultat is None:
            etat = "analyse en cours…"
        elif resultat.termine:
            etat = f"profondeur {resultat.profondeur} · terminé"
        else:
            vitesse = f" · {resultat.vitesse / 1_000_000:.1f} Mn/s" if resultat.vitesse else ""
            etat = f"profondeur {resultat.profondeur}{vitesse}"

        rendu = self.petit.render(etat, True, theme.TEXTE_DOUX)
        surface.blit(rendu, (x + 14, y + 26))
        return y + H_ENTETE

    # -- variantes ------------------------------------------------------- #

    def _variantes(self, surface, x, y, largeur, echiquier, resultat) -> int:
        self._section(surface, x, y, "MEILLEURS COUPS")
        y += H_TITRE

        variantes = resultat.variantes if resultat else ()
        if not variantes:
            texte = "…" if resultat is None else "position terminée"
            surface.blit(self.normal.render(texte, True, theme.TEXTE_DOUX), (x + 14, y + 10))
            return y + H_LIGNE_VARIANTE

        for i, v in enumerate(variantes):
            self._une_variante(surface, x, y + i * H_LIGNE_VARIANTE, largeur, echiquier, v, i)

        return y + len(variantes) * H_LIGNE_VARIANTE + 8

    def _une_variante(self, surface, x, y, largeur, echiquier, variante, rang) -> None:
        couleur_rang = theme.FLECHES[rang][:3] if rang < len(theme.FLECHES) else theme.TEXTE_DOUX

        # Pastille de couleur, identique à celle de la flèche sur l'échiquier :
        # l'œil relie immédiatement la ligne de texte à la flèche correspondante.
        pygame.draw.rect(surface, couleur_rang, (x + 14, y + 8, 4, 24), border_radius=2)

        if variante.coup is None:
            return

        # Évaluation du point de vue du joueur au trait : « est-ce bon pour moi ? »
        score = variante.score.pov(echiquier.turn)
        eval_txt = notation.texte_score(score, court=True)
        san = notation.san_francais(echiquier, variante.coup)

        surface.blit(self.gras.render(eval_txt, True, theme.TEXTE), (x + 26, y + 5))
        surface.blit(self.gras.render(san, True, theme.TEXTE), (x + 90, y + 5))

        suite = notation.variante_en_texte(echiquier, variante.coups, maxi=8)
        suite = self._tronquer(self.petit, suite, largeur - 40)
        surface.blit(self.petit.render(suite, True, theme.TEXTE_DOUX), (x + 26, y + 24))

    # -- liste des coups -------------------------------------------------- #

    def _liste_coups(self, surface, x, y, largeur, hauteur, partie: Partie) -> None:
        self._section(surface, x, y, "PARTIE")
        y += H_TITRE
        hauteur -= H_TITRE

        zone = pygame.Rect(x + 8, y, largeur - 16, max(0, hauteur))
        self._zone_liste = zone
        self._zones_coups = []

        nb_rangees = (len(partie.coups) + 1) // 2
        self._hauteur_liste_totale = nb_rangees * H_RANGEE_COUP
        self._ajuster_defilement(partie, zone)

        # set_clip empêche de dessiner en dehors de la zone : les rangées qui
        # dépassent en haut et en bas sont coupées net, comme dans une vraie
        # liste défilante.
        ancien_clip = surface.get_clip()
        surface.set_clip(zone)

        largeur_col = (zone.width - 44) // 2
        for rangee in range(nb_rangees):
            ry = zone.y + rangee * H_RANGEE_COUP - self.defilement
            if ry + H_RANGEE_COUP < zone.y or ry > zone.bottom:
                continue  # hors écran, inutile de dessiner

            numero = self.petit.render(f"{rangee + 1}.", True, theme.TEXTE_DOUX)
            surface.blit(numero, (zone.x + 6, ry + 5))

            for demi in (0, 1):
                index = rangee * 2 + demi
                if index >= len(partie.coups):
                    break
                rect = pygame.Rect(zone.x + 40 + demi * largeur_col, ry, largeur_col, H_RANGEE_COUP)
                self._une_case_coup(surface, rect, partie, index)
                self._zones_coups.append((rect, index))

        surface.set_clip(ancien_clip)

    def _une_case_coup(self, surface, rect, partie: Partie, index: int) -> None:
        entree = partie.coups[index]
        courant = index == partie.index - 1

        if courant:
            pygame.draw.rect(surface, theme.PANNEAU_CLAIR, rect, border_radius=4)

        couleur = theme.TEXTE if courant else (200, 197, 192)
        police = self.gras if courant else self.mono
        surface.blit(police.render(entree.san, True, couleur), (rect.x + 8, rect.y + 4))

        # Pastille du jugement, à droite de la case.
        if entree.jugement:
            teinte = theme.CLASSEMENT.get(entree.jugement, theme.TEXTE_DOUX)
            centre = (rect.right - 12, rect.centery)
            pygame.draw.circle(surface, teinte, centre, 5)

    def _ajuster_defilement(self, partie: Partie, zone: pygame.Rect) -> None:
        """Fait suivre la liste automatiquement quand on avance dans la partie."""
        if partie.index == 0:
            return
        rangee = (partie.index - 1) // 2
        haut = rangee * H_RANGEE_COUP
        bas = haut + H_RANGEE_COUP

        if haut < self.defilement:
            self.defilement = haut
        elif bas > self.defilement + zone.height:
            self.defilement = bas - zone.height

        maxi = max(0, self._hauteur_liste_totale - zone.height)
        self.defilement = max(0, min(self.defilement, maxi))

    # -- pied de panneau -------------------------------------------------- #

    def _aide(self, surface, x, y, largeur, hauteur, message) -> None:
        pygame.draw.line(surface, theme.BORDURE, (x + 12, y), (x + largeur - 12, y))

        if message:
            rendu = self.petit.render(self._tronquer(self.petit, message, largeur - 28),
                                      True, theme.CLASSEMENT["Imprécision"])
            surface.blit(rendu, (x + 14, y + 8))

        lignes = [
            "← →  coup précédent / suivant      ⇱ ⇲  début / fin",
            "F  retourner l'échiquier — en mode partie, tu joues le camp du bas",
            "Espace  jouer le coup du moteur      Ctrl+Z  annuler",
            "Ctrl+V  coller FEN/PGN      Ctrl+C  copier FEN      Ctrl+N  nouvelle",
        ]
        for i, ligne in enumerate(lignes):
            rendu = self.petit.render(ligne, True, theme.TEXTE_DOUX)
            surface.blit(rendu, (x + 14, y + 26 + i * 14))

    # -- outils ----------------------------------------------------------- #

    def _section(self, surface, x, y, libelle) -> None:
        rendu = self.titre.render(libelle, True, theme.TEXTE_DOUX)
        surface.blit(rendu, (x + 14, y + 8))

    @staticmethod
    def _tronquer(police: pygame.font.Font, texte: str, largeur: int) -> str:
        """Coupe un texte trop long et le termine par une ellipse."""
        if police.size(texte)[0] <= largeur:
            return texte
        while texte and police.size(texte + "…")[0] > largeur:
            texte = texte[:-1]
        return texte + "…"
