"""
Palette de couleurs et calcul de la disposition de la fenêtre.

Tout regrouper ici sert deux buts :
  - changer l'apparence sans toucher au code de dessin ;
  - rendre la fenêtre redimensionnable, puisque chaque position est *calculée*
    à partir de la taille courante plutôt qu'écrite en dur.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Couleurs (format RVB, ou RVBA quand la transparence est utile)
# --------------------------------------------------------------------------- #

FOND = (34, 32, 30)
PANNEAU = (46, 43, 40)
PANNEAU_CLAIR = (58, 55, 51)
BORDURE = (72, 68, 63)

TEXTE = (232, 230, 226)
TEXTE_DOUX = (150, 146, 140)
TEXTE_SOMBRE = (30, 28, 26)

CASE_CLAIRE = (235, 236, 208)
CASE_SOMBRE = (115, 149, 82)

# Surlignage du dernier coup joué : jaune translucide posé par-dessus la case.
DERNIER_COUP = (246, 246, 105, 110)
# Case sélectionnée au moment d'un glisser-déposer.
SELECTION = (246, 246, 105, 150)
# Petits points indiquant les cases où la pièce saisie peut aller.
DESTINATION = (30, 30, 30, 55)
# Cerclage des cases de destination occupées par une pièce à capturer.
CAPTURE = (30, 30, 30, 60)
# Roi en échec.
ECHEC = (220, 70, 60, 140)

# Flèches des coups recommandés, en code tricolore : vert, jaune, rouge.
# La quatrième valeur est l'opacité (0 = invisible, 255 = opaque) : le meilleur
# coup est le plus franc, les suivants s'effacent légèrement pour que l'œil
# aille d'abord au vert.
# Le jaune est volontairement foncé et très opaque : un jaune vif serait illisible
# sur les cases claires de l'échiquier, qui sont déjà crème.
FLECHES = [
    (90, 180, 90, 200),    # meilleur coup
    (222, 176, 40, 200),   # deuxième
    (215, 72, 62, 185),    # troisième
]

# Barre d'évaluation.
BARRE_BLANCS = (248, 248, 246)
BARRE_NOIRS = (58, 55, 51)

# Couleurs des jugements portés sur les coups joués.
CLASSEMENT = {
    "Meilleur coup": (118, 186, 92),
    "Excellent": (118, 186, 92),
    "Bien": (150, 175, 140),
    "Imprécision": (230, 190, 90),
    "Erreur": (232, 140, 70),
    "Gaffe": (216, 85, 75),
}

# --------------------------------------------------------------------------- #
# Polices
# --------------------------------------------------------------------------- #

POLICE_UI = "C:/Windows/Fonts/segoeui.ttf"
POLICE_UI_GRAS = "C:/Windows/Fonts/segoeuib.ttf"
# Segoe UI Symbol contient les glyphes d'échecs Unicode (U+2654 à U+265F).
POLICE_PIECES = "C:/Windows/Fonts/seguisym.ttf"

# --------------------------------------------------------------------------- #
# Disposition
# --------------------------------------------------------------------------- #

MARGE = 18
LARGEUR_BARRE = 26
LARGEUR_PANNEAU_MIN = 380
FENETRE_DEFAUT = (1320, 800)
FENETRE_MINI = (1040, 660)


@dataclass(frozen=True)
class Disposition:
    """
    Position et taille de chaque zone, recalculée à chaque redimensionnement.

    Le principe : l'échiquier prend toute la hauteur disponible, dans la limite
    de la largeur restante une fois le panneau latéral réservé. On arrondit
    ensuite la taille d'une case à l'entier inférieur pour éviter les bavures
    d'un pixel entre les cases.
    """

    fenetre: tuple[int, int]
    case: int
    echiquier: tuple[int, int]     # coin haut-gauche de l'échiquier
    barre: tuple[int, int, int, int]   # x, y, largeur, hauteur
    panneau: tuple[int, int, int, int]  # x, y, largeur, hauteur

    @property
    def cote(self) -> int:
        """Côté de l'échiquier en pixels."""
        return self.case * 8


def calculer(largeur: int, hauteur: int) -> Disposition:
    """Répartit l'espace de la fenêtre entre la barre, l'échiquier et le panneau."""
    largeur = max(largeur, FENETRE_MINI[0])
    hauteur = max(hauteur, FENETRE_MINI[1])

    # Espace horizontal utilisable par l'échiquier une fois tout le reste réservé.
    dispo_h = largeur - (MARGE * 4) - LARGEUR_BARRE - LARGEUR_PANNEAU_MIN
    dispo_v = hauteur - (MARGE * 2)

    case = max(40, min(dispo_h, dispo_v) // 8)
    cote = case * 8

    y_haut = (hauteur - cote) // 2
    x_barre = MARGE
    x_echiquier = x_barre + LARGEUR_BARRE + MARGE
    x_panneau = x_echiquier + cote + MARGE

    return Disposition(
        fenetre=(largeur, hauteur),
        case=case,
        echiquier=(x_echiquier, y_haut),
        barre=(x_barre, y_haut, LARGEUR_BARRE, cote),
        panneau=(x_panneau, y_haut, largeur - x_panneau - MARGE, cote),
    )
