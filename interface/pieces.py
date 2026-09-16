"""
Fabrication des images de pièces, sans aucun fichier à télécharger.

--- La technique ---
Unicode définit deux séries de symboles d'échecs : U+2654-2659 (contours creux,
« blancs ») et U+265A-265F (silhouettes pleines, « noires »). Dessiner les
Blancs avec les glyphes creux donne un rendu maigrichon, illisible sur une case
claire.

On utilise donc les glyphes PLEINS pour les deux camps, et on joue sur les
couleurs : silhouette blanche cernée de noir pour les Blancs, silhouette noire
cernée de gris clair pour les Noirs. C'est exactement le principe des jeux de
pièces classiques, et le résultat est net à toutes les tailles.

Pillow sait dessiner du texte avec un contour (stroke_width) ; pygame ne le sait
pas. On rend donc l'image avec Pillow, puis on la convertit en surface pygame.
"""

from __future__ import annotations

import chess
import pygame
from PIL import Image, ImageDraw, ImageFont

from interface import theme

# Silhouettes pleines, utilisées pour les deux couleurs.
GLYPHES = {
    chess.PAWN: "♟",
    chess.KNIGHT: "♞",
    chess.BISHOP: "♝",
    chess.ROOK: "♜",
    chess.QUEEN: "♛",
    chess.KING: "♚",
}

# Remplissage et contour, par couleur de camp.
_REMPLISSAGE = {
    chess.WHITE: ((250, 250, 248, 255), (28, 26, 24, 255)),
    chess.BLACK: ((34, 32, 30, 255), (188, 186, 182, 255)),
}

# Cache : rendre une pièce coûte quelques millisecondes, on ne le fait qu'une
# fois par (type de pièce, couleur, taille). Le cache est vidé et reconstruit
# quand la fenêtre change de taille.
_cache: dict[tuple[int, bool, int], pygame.Surface] = {}


def _rendre(piece: chess.Piece, taille: int) -> pygame.Surface:
    """Dessine une pièce dans un carré de `taille` pixels de côté."""
    remplissage, contour = _REMPLISSAGE[piece.color]

    # La pièce n'occupe pas toute la case : on laisse une marge d'environ 12 %.
    corps = int(taille * 0.78)
    police = ImageFont.truetype(theme.POLICE_PIECES, corps)
    epaisseur = max(1, round(taille / 36))

    image = Image.new("RGBA", (taille, taille), (0, 0, 0, 0))
    dessin = ImageDraw.Draw(image)
    # anchor="mm" = le point donné est le milieu du texte, horizontalement et
    # verticalement. C'est ce qui centre proprement le glyphe dans la case.
    dessin.text(
        (taille / 2, taille / 2),
        GLYPHES[piece.piece_type],
        font=police,
        fill=remplissage,
        anchor="mm",
        stroke_width=epaisseur,
        stroke_fill=contour,
    )

    # Conversion Pillow -> pygame : on passe par les octets bruts RVBA.
    surface = pygame.image.frombytes(image.tobytes(), image.size, "RGBA")
    return surface.convert_alpha()


def image(piece: chess.Piece, taille: int) -> pygame.Surface:
    """Renvoie l'image d'une pièce, en la fabriquant à la première demande."""
    cle = (piece.piece_type, piece.color, taille)
    if cle not in _cache:
        _cache[cle] = _rendre(piece, taille)
    return _cache[cle]


def precharger(taille: int) -> None:
    """
    Fabrique les douze pièces d'un coup.

    Appelé au démarrage et après un redimensionnement : mieux vaut une pause de
    quelques dizaines de millisecondes au bon moment qu'un à-coup pendant le jeu.
    """
    for couleur in (chess.WHITE, chess.BLACK):
        for type_piece in GLYPHES:
            image(chess.Piece(type_piece, couleur), taille)


def vider_cache() -> None:
    """Libère les images (à faire quand la taille des cases change)."""
    _cache.clear()
