"""
Chemins et reglages globaux du projet.

Centraliser les chemins ici evite de les repeter partout : le jour ou tu mets
Stockfish a jour ou deplaces un dossier, il n'y a qu'un seul endroit a corriger.
"""

import sys
from pathlib import Path

# Path(__file__) = ce fichier ; .resolve() le transforme en chemin absolu ;
# .parent remonte d'un cran (noyau/), deux fois = la racine du projet.
RACINE = Path(__file__).resolve().parent.parent

DOSSIER_MOTEURS = RACINE / "moteurs_externes"
DOSSIER_RESSOURCES = RACINE / "ressources"
DOSSIER_PARTIES = RACINE / "parties"


def chemin_stockfish() -> Path:
    """
    Retrouve l'executable Stockfish sans coder son nom en dur.

    Le nom du fichier contient la variante compilee (bmi2, avx2...) et le
    numero de version change a chaque mise a jour. On cherche donc n'importe
    quel .exe commencant par "stockfish" dans le sous-dossier prevu.
    """
    dossier = DOSSIER_MOTEURS / "stockfish"
    candidats = sorted(dossier.glob("stockfish*.exe"))
    if not candidats:
        raise FileNotFoundError(
            f"Aucun executable Stockfish trouve dans {dossier}.\n"
            "Telecharge-le sur https://stockfishchess.org/download/ et "
            "place le .exe dans ce dossier."
        )
    return candidats[0]


DOSSIER_OUTILS = RACINE / "outils_externes"


def chemin_pypy() -> Path | None:
    """
    Retrouve PyPy s'il est installe, sinon None.

    PyPy est un interpreteur Python qui compile le code a la volee. Sur notre
    moteur, il est mesure 4,2 fois plus rapide que Python standard, pour un
    code rigoureusement identique.
    """
    for dossier in sorted(DOSSIER_OUTILS.glob("pypy*")):
        executable = dossier / "pypy.exe"
        if executable.exists():
            return executable
    return None


def commande_moteur_maison(forcer_cpython: bool = False) -> list[str]:
    """
    Comment lancer notre propre moteur, vu comme un programme UCI ordinaire.

    Ce n'est pas un .exe mais un module Python : on renvoie donc une liste
    d'arguments plutot qu'un chemin.

    C'est ici que se paie le choix d'architecture de la phase 1. Parce que le
    moteur tourne dans un PROCESSUS SEPARE et ne communique que par du texte,
    rien n'oblige l'interface et le moteur a partager le meme interpreteur.
    L'interface reste sur Python standard, avec pygame et tout le reste ; le
    moteur passe sous PyPy et va 4 fois plus vite. Aucune ligne d'algorithme
    n'a change.

    `forcer_cpython` sert a la mesure : il permet de faire jouer la version
    PyPy contre la version Python standard.
    """
    if not forcer_cpython:
        pypy = chemin_pypy()
        if pypy is not None:
            return [str(pypy), "-m", "moteur_maison.uci"]
    return [sys.executable, "-m", "moteur_maison.uci"]


# --- Reglages materiels, adaptes a ta machine (Ryzen 5 5500 : 6 coeurs / 12 threads, 32 Go) ---

# Nombre de threads laisses au moteur. On garde des coeurs libres pour que
# l'interface graphique reste fluide pendant que le moteur reflechit.
THREADS_MOTEUR = 6

# Taille de la table de transposition, en Mo. C'est la memoire ou le moteur
# stocke les positions deja analysees pour ne pas les recalculer.
# Plus elle est grande, plus l'analyse longue est efficace.
HASH_MOTEUR_MO = 2048

# Nombre de variantes proposees par defaut (le "top 3 des coups" facon chess.com).
NB_VARIANTES = 3

# Profondeur d'analyse par defaut. 18-20 suffit largement pour une analyse
# de partie ; au-dela le gain devient marginal et le temps explose.
PROFONDEUR_DEFAUT = 18

# Notre moteur maison est environ 200 fois plus lent que Stockfish : on le
# borne par le temps, pas par la profondeur, sans quoi l'analyse ne finirait
# jamais.
TEMPS_ANALYSE_MAISON = 3.0

# Temps de reflexion par coup de l'adversaire, en mode partie.
TEMPS_ADVERSAIRE = 2.0
