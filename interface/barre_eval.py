"""
La barre d'évaluation verticale, à gauche de l'échiquier.

--- Pourquoi une probabilité et pas les centipions ---
Si la hauteur de la barre était proportionnelle à l'évaluation brute, elle
saturerait immédiatement : à +5 pions on serait déjà en butée, alors que la
différence entre +5 et +12 existe. Et surtout, elle bougerait à peine entre
0.00 et +0.80, alors que c'est précisément la zone où tout se joue.

On convertit donc l'évaluation en probabilité de victoire (voir
noyau/notation.py) : la barre devient une jauge honnête, très sensible autour
de l'égalité et calme dans les positions déjà décidées.
"""

from __future__ import annotations

import chess
import chess.engine
import pygame

from interface import theme
from interface.theme import Disposition
from noyau import notation


class BarreEval:
    """Jauge verticale montrant qui est en meilleure position."""

    def __init__(self):
        self.police = pygame.font.Font(theme.POLICE_UI_GRAS, 13)
        # Valeur affichée, qui rattrape progressivement la valeur réelle.
        self._hauteur_lissee = 0.5

    def dessiner(
        self,
        surface: pygame.Surface,
        disposition: Disposition,
        score: chess.engine.Score | None,
        retourne: bool,
    ) -> None:
        x, y, largeur, hauteur = disposition.barre

        part_blancs = 0.5 if score is None else notation.probabilite_victoire(score)

        # Lissage : sans lui, la barre sursaute à chaque palier de profondeur.
        # On se rapproche de 25 % de l'écart à chaque image, ce qui donne un
        # mouvement fluide sans jamais retarder de plus de quelques images.
        self._hauteur_lissee += (part_blancs - self._hauteur_lissee) * 0.25

        # Fond = camp du haut ; on remplit ensuite la part du camp du bas.
        couleur_haut = theme.BARRE_NOIRS if not retourne else theme.BARRE_BLANCS
        couleur_bas = theme.BARRE_BLANCS if not retourne else theme.BARRE_NOIRS
        part_bas = self._hauteur_lissee if not retourne else 1 - self._hauteur_lissee

        pygame.draw.rect(surface, couleur_haut, (x, y, largeur, hauteur))
        h_bas = int(hauteur * part_bas)
        pygame.draw.rect(surface, couleur_bas, (x, y + hauteur - h_bas, largeur, h_bas))

        # Repère du milieu : l'égalité parfaite.
        pygame.draw.line(
            surface, theme.BORDURE,
            (x, y + hauteur // 2), (x + largeur, y + hauteur // 2), 1,
        )
        pygame.draw.rect(surface, theme.BORDURE, (x, y, largeur, hauteur), width=1)

        if score is not None:
            self._dessiner_texte(surface, disposition, score, retourne)

    def _dessiner_texte(self, surface, disposition, score, retourne) -> None:
        """
        Écrit l'évaluation à l'extrémité du camp qui a l'avantage.

        Placer le texte du côté du camp favorisé garantit qu'il s'affiche
        toujours sur une zone remplie, donc lisible.
        """
        x, y, largeur, hauteur = disposition.barre
        texte = notation.texte_score(score, court=True)

        avantage_blancs = notation.probabilite_victoire(score) >= 0.5
        blancs_en_bas = not retourne

        if avantage_blancs:
            couleur = theme.TEXTE_SOMBRE
            en_bas = blancs_en_bas
        else:
            couleur = theme.BARRE_BLANCS
            en_bas = not blancs_en_bas

        rendu = self.police.render(texte, True, couleur)
        # Le texte est écrit verticalement, comme la barre.
        rendu = pygame.transform.rotate(rendu, 90)

        px = x + (largeur - rendu.get_width()) // 2
        py = (y + hauteur - rendu.get_height() - 6) if en_bas else (y + 6)
        surface.blit(rendu, (px, py))
