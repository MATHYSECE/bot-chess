"""
Dessin de l'échiquier et conversion entre pixels et cases.

Cette classe ne décide de rien : elle reçoit une position et des indications
d'affichage (case sélectionnée, flèches à tracer...) et les dessine. Toute la
logique de jeu reste dans le noyau. Cette séparation permet de changer
complètement l'apparence sans toucher aux règles.

--- Le repérage des cases ---
python-chess numérote les cases de 0 (a1) à 63 (h8) :
    colonne = case % 8   (0 = colonne a)
    rangee  = case // 8  (0 = rangée 1)
À l'écran, l'axe vertical est inversé (le pixel 0 est en haut) et l'échiquier
peut être retourné pour jouer les Noirs. Les deux fonctions `_ecran()` et
`case_sous()` concentrent cette conversion : partout ailleurs, on raisonne en
numéros de cases.
"""

from __future__ import annotations

import math

import chess
import pygame

from interface import pieces, theme
from interface.theme import Disposition

# Lettres et chiffres affichés en bordure d'échiquier.
_COLONNES = "abcdefgh"


class VueEchiquier:
    """Affiche un échiquier et traduit les clics de souris en cases."""

    def __init__(self, disposition: Disposition, retourne: bool = False):
        self.disposition = disposition
        self.retourne = retourne          # True = les Noirs sont en bas
        self._police_reperes: pygame.font.Font | None = None
        self.maj_disposition(disposition)

    def maj_disposition(self, disposition: Disposition) -> None:
        """À appeler quand la fenêtre change de taille."""
        self.disposition = disposition
        pieces.vider_cache()
        pieces.precharger(disposition.case)
        taille_repere = max(10, disposition.case // 5)
        self._police_reperes = pygame.font.Font(theme.POLICE_UI_GRAS, taille_repere)

    def retourner(self) -> None:
        """Bascule le point de vue entre les Blancs et les Noirs."""
        self.retourne = not self.retourne

    # ------------------------------------------------------------------ #
    # Conversions pixels <-> cases
    # ------------------------------------------------------------------ #

    def _ecran(self, case: chess.Square) -> tuple[int, int]:
        """Coin haut-gauche, en pixels, de la case donnée."""
        colonne = chess.square_file(case)
        rangee = chess.square_rank(case)

        if self.retourne:
            col_ecran, lig_ecran = 7 - colonne, rangee
        else:
            col_ecran, lig_ecran = colonne, 7 - rangee

        x0, y0 = self.disposition.echiquier
        c = self.disposition.case
        return x0 + col_ecran * c, y0 + lig_ecran * c

    def rect_case(self, case: chess.Square) -> pygame.Rect:
        """Rectangle occupé par une case."""
        x, y = self._ecran(case)
        c = self.disposition.case
        return pygame.Rect(x, y, c, c)

    def centre_case(self, case: chess.Square) -> tuple[float, float]:
        x, y = self._ecran(case)
        demi = self.disposition.case / 2
        return x + demi, y + demi

    def case_sous(self, point: tuple[int, int]) -> chess.Square | None:
        """Case située sous un point de l'écran, ou None si l'on est en dehors."""
        x0, y0 = self.disposition.echiquier
        c = self.disposition.case
        col_ecran = (point[0] - x0) // c
        lig_ecran = (point[1] - y0) // c

        if not (0 <= col_ecran < 8 and 0 <= lig_ecran < 8):
            return None

        if self.retourne:
            colonne, rangee = 7 - col_ecran, lig_ecran
        else:
            colonne, rangee = col_ecran, 7 - lig_ecran

        return chess.square(int(colonne), int(rangee))

    # ------------------------------------------------------------------ #
    # Dessin
    # ------------------------------------------------------------------ #

    def dessiner(
        self,
        surface: pygame.Surface,
        echiquier: chess.Board,
        dernier_coup: chess.Move | None = None,
        selection: chess.Square | None = None,
        destinations: set[chess.Square] | None = None,
        fleches: list[tuple[chess.Square, chess.Square, tuple]] | None = None,
        case_saisie: chess.Square | None = None,
        souris: tuple[int, int] | None = None,
    ) -> None:
        """
        Dessine tout l'échiquier, dans l'ordre des plans.

        L'ordre compte : chaque couche recouvre la précédente. Les flèches
        passent au-dessus des pièces (comme sur chess.com) pour rester lisibles,
        et la pièce en cours de déplacement est dessinée en tout dernier, sous
        le curseur.
        """
        self._dessiner_cases(surface)
        self._dessiner_surlignages(surface, echiquier, dernier_coup, selection)
        self._dessiner_reperes(surface)
        self._dessiner_pieces(surface, echiquier, case_saisie)
        self._dessiner_destinations(surface, echiquier, destinations or set())
        self._dessiner_fleches(surface, fleches or [])
        self._dessiner_piece_saisie(surface, echiquier, case_saisie, souris)

    # -- couches --------------------------------------------------------- #

    def _dessiner_cases(self, surface: pygame.Surface) -> None:
        for case in chess.SQUARES:
            # Une case est claire quand la somme colonne + rangée est impaire.
            claire = (chess.square_file(case) + chess.square_rank(case)) % 2 == 1
            couleur = theme.CASE_CLAIRE if claire else theme.CASE_SOMBRE
            pygame.draw.rect(surface, couleur, self.rect_case(case))

    def _voile(self, surface: pygame.Surface, case: chess.Square, couleur_rvba) -> None:
        """Pose un rectangle translucide sur une case."""
        voile = pygame.Surface((self.disposition.case,) * 2, pygame.SRCALPHA)
        voile.fill(couleur_rvba)
        surface.blit(voile, self._ecran(case))

    def _dessiner_surlignages(
        self,
        surface: pygame.Surface,
        echiquier: chess.Board,
        dernier_coup: chess.Move | None,
        selection: chess.Square | None,
    ) -> None:
        if dernier_coup is not None:
            self._voile(surface, dernier_coup.from_square, theme.DERNIER_COUP)
            self._voile(surface, dernier_coup.to_square, theme.DERNIER_COUP)

        if selection is not None:
            self._voile(surface, selection, theme.SELECTION)

        # Roi en échec : signal indispensable pour ne pas jouer un coup illégal
        # sans comprendre pourquoi il est refusé.
        if echiquier.is_check():
            roi = echiquier.king(echiquier.turn)
            if roi is not None:
                self._voile(surface, roi, theme.ECHEC)

    def _dessiner_reperes(self, surface: pygame.Surface) -> None:
        """Lettres de colonnes et chiffres de rangées, dans les coins des cases."""
        c = self.disposition.case
        marge = max(2, c // 24)

        for i in range(8):
            colonne = 7 - i if self.retourne else i
            rangee = i if self.retourne else 7 - i

            # Chiffre de rangée, en haut à gauche de la colonne a affichée.
            case_gauche = chess.square(7 if self.retourne else 0, rangee)
            claire = (chess.square_file(case_gauche) + rangee) % 2 == 1
            couleur = theme.CASE_SOMBRE if claire else theme.CASE_CLAIRE
            x, y = self._ecran(case_gauche)
            texte = self._police_reperes.render(str(rangee + 1), True, couleur)
            surface.blit(texte, (x + marge, y + marge))

            # Lettre de colonne, en bas à droite de la rangée du bas.
            case_bas = chess.square(colonne, 0 if not self.retourne else 7)
            claire = (colonne + chess.square_rank(case_bas)) % 2 == 1
            couleur = theme.CASE_SOMBRE if claire else theme.CASE_CLAIRE
            x, y = self._ecran(case_bas)
            texte = self._police_reperes.render(_COLONNES[colonne], True, couleur)
            surface.blit(texte, (x + c - texte.get_width() - marge,
                                 y + c - texte.get_height() - marge))

    def _dessiner_pieces(
        self,
        surface: pygame.Surface,
        echiquier: chess.Board,
        case_saisie: chess.Square | None,
    ) -> None:
        for case, piece in echiquier.piece_map().items():
            if case == case_saisie:
                continue  # dessinée à la fin, collée au curseur
            surface.blit(pieces.image(piece, self.disposition.case), self._ecran(case))

    def _dessiner_destinations(
        self,
        surface: pygame.Surface,
        echiquier: chess.Board,
        destinations: set[chess.Square],
    ) -> None:
        """
        Marque les cases atteignables : un point pour une case vide, un anneau
        pour une capture. C'est la convention de Lichess et de chess.com.
        """
        c = self.disposition.case
        for case in destinations:
            calque = pygame.Surface((c, c), pygame.SRCALPHA)
            if echiquier.piece_at(case) is None:
                pygame.draw.circle(calque, theme.DESTINATION, (c // 2, c // 2), c // 6)
            else:
                pygame.draw.circle(
                    calque, theme.CAPTURE, (c // 2, c // 2), c // 2 - c // 24,
                    width=max(3, c // 12),
                )
            surface.blit(calque, self._ecran(case))

    def _dessiner_fleches(
        self,
        surface: pygame.Surface,
        fleches: list[tuple[chess.Square, chess.Square, tuple]],
    ) -> None:
        """Trace les flèches des coups recommandés, la meilleure en dernier."""
        c = self.disposition.case
        calque = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

        # On dessine à l'envers pour que la flèche n°1 se retrouve au-dessus.
        for depart, arrivee, couleur in reversed(fleches):
            self._une_fleche(calque, depart, arrivee, couleur, c)

        surface.blit(calque, (0, 0))

    def _une_fleche(self, calque, depart, arrivee, couleur, c: int) -> None:
        """
        Une flèche allant du centre d'une case au centre d'une autre.

        Géométrie : on construit le polygone dans un repère aligné sur la
        direction de la flèche (vecteur unitaire u, et sa perpendiculaire p),
        ce qui évite toute trigonométrie compliquée.
        """
        x1, y1 = self.centre_case(depart)
        x2, y2 = self.centre_case(arrivee)

        dx, dy = x2 - x1, y2 - y1
        longueur = math.hypot(dx, dy)
        if longueur < 1:
            return

        ux, uy = dx / longueur, dy / longueur      # direction
        px, py = -uy, ux                           # perpendiculaire

        # On laisse la pièce de départ visible et on arrête la pointe un peu
        # avant le bord de la case d'arrivée.
        recul_depart = c * 0.30
        recul_arrivee = c * 0.10
        x1 += ux * recul_depart
        y1 += uy * recul_depart
        x2 -= ux * recul_arrivee
        y2 -= uy * recul_arrivee

        if math.hypot(x2 - x1, y2 - y1) < c * 0.2:
            return  # flèche trop courte pour être lisible

        tete = c * 0.34          # longueur de la pointe
        demi_tete = c * 0.20     # demi-largeur de la pointe
        demi_corps = c * 0.075   # demi-largeur du trait

        bx, by = x2 - ux * tete, y2 - uy * tete   # base de la pointe

        polygone = [
            (x1 + px * demi_corps, y1 + py * demi_corps),
            (bx + px * demi_corps, by + py * demi_corps),
            (bx + px * demi_tete, by + py * demi_tete),
            (x2, y2),
            (bx - px * demi_tete, by - py * demi_tete),
            (bx - px * demi_corps, by - py * demi_corps),
            (x1 - px * demi_corps, y1 - py * demi_corps),
        ]
        pygame.draw.polygon(calque, couleur, polygone)

    def _dessiner_piece_saisie(
        self,
        surface: pygame.Surface,
        echiquier: chess.Board,
        case_saisie: chess.Square | None,
        souris: tuple[int, int] | None,
    ) -> None:
        """La pièce en cours de déplacement, centrée sur le curseur."""
        if case_saisie is None or souris is None:
            return
        piece = echiquier.piece_at(case_saisie)
        if piece is None:
            return

        image = pieces.image(piece, self.disposition.case)
        demi = self.disposition.case // 2
        surface.blit(image, (souris[0] - demi, souris[1] - demi))
