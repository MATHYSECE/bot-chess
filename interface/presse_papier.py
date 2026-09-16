"""
Accès au presse-papier de Windows.

pygame propose bien un module `scrap`, mais il est marqué comme expérimental et
gère mal le texte Unicode. On passe donc par tkinter, livré avec Python : on
crée une fenêtre invisible juste le temps de lire ou d'écrire, puis on la
détruit. C'est peu élégant, mais c'est fiable et sans dépendance nouvelle.
"""

from __future__ import annotations

import tkinter


def lire() -> str:
    """Contenu texte du presse-papier, ou chaîne vide s'il n'y a rien d'exploitable."""
    racine = tkinter.Tk()
    racine.withdraw()  # ne jamais afficher la fenêtre
    try:
        return racine.clipboard_get()
    except tkinter.TclError:
        return ""      # presse-papier vide ou contenant autre chose que du texte
    finally:
        racine.destroy()


def ecrire(texte: str) -> None:
    """Place un texte dans le presse-papier."""
    racine = tkinter.Tk()
    racine.withdraw()
    racine.clipboard_clear()
    racine.clipboard_append(texte)
    # update() force tkinter à transmettre réellement le contenu à Windows
    # avant que la fenêtre ne disparaisse.
    racine.update()
    racine.destroy()
