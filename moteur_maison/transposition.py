"""
La table de transposition : le carnet de notes du moteur.

--- Pourquoi « transposition » ---
Aux échecs, des chemins différents mènent à la même position :

    1.e4 e5 2.Cf3     et     1.Cf3 e5 2.e4

donnent un échiquier rigoureusement identique. On dit que les deux lignes
*transposent*. Sans mémoire, le moteur analyse la position deux fois, et bien
plus que deux fois en réalité : à la profondeur 8, une même position peut être
atteinte par des dizaines de chemins.

--- Le gain principal n'est pas celui qu'on croit ---
Éviter des recalculs fait gagner du temps, c'est vrai. Mais le vrai bénéfice est
ailleurs : chaque entrée retient aussi **le meilleur coup trouvé**. En le
réessayant en premier, on redonne à l'élagage alpha-bêta les conditions où il
divise l'arbre par deux. La mémoire sert surtout à mieux trier.

--- Les trois sortes de scores ---
Un nœud ne renvoie pas toujours une valeur exacte. Après un élagage, on sait
seulement « c'est au moins tant » ou « c'est au plus tant ». Il faut ranger
cette nuance avec le score, sinon on réutiliserait une borne comme une
certitude — et le moteur jouerait sur des évaluations fausses :

    EXACT      la vraie valeur, obtenue sans coupure
    BORNE_INF  la valeur est au moins celle-ci (coupure bêta)
    BORNE_SUP  la valeur est au plus celle-ci (aucun coup n'a dépassé alpha)

--- Choix de structure ---
Mesuré : un accès coûte 1,0 µs, contre 38 µs pour générer les coups d'une
position. La table représente donc moins de 3 % du coût d'un nœud, et il est
inutile de l'optimiser. On prend le plus SÛR : un dictionnaire Python indexé
par la clé complète, ce qui rend toute collision impossible. Les moteurs écrits
en C utilisent un tableau de taille fixe indexé par un hachage, au prix de
collisions rares mais réelles ; ici, rien ne nous y oblige.
"""

from __future__ import annotations

import chess

# Nature du score rangé dans une entrée.
EXACT = 0
BORNE_INF = 1
BORNE_SUP = 2

# Au-delà de ce nombre d'entrées, on vide la table. 500 000 entrées occupent
# environ 165 Mo, ce qui est confortable sur une machine de 32 Go.
ENTREES_MAX = 500_000


class TableTransposition:
    """
    Mémoire des positions déjà analysées.

    Une entrée est un simple tuple `(profondeur, score, drapeau, coup)` :
      profondeur  à quelle profondeur ce score a été établi. Un score obtenu à
                  la profondeur 3 ne vaut rien pour une recherche à 8 ;
      score       la valeur trouvée, en centipions ;
      drapeau     EXACT, BORNE_INF ou BORNE_SUP (voir ci-dessus) ;
      coup        le meilleur coup, à réessayer en premier.
    """

    def __init__(self, entrees_max: int = ENTREES_MAX):
        self.entrees_max = entrees_max
        self._table: dict[tuple, tuple] = {}
        self.lectures = 0
        self.trouvees = 0

    def lire(self, cle: tuple) -> tuple | None:
        self.lectures += 1
        entree = self._table.get(cle)
        if entree is not None:
            self.trouvees += 1
        return entree

    def ecrire(self, cle: tuple, profondeur: int, score: int,
               drapeau: int, coup: chess.Move | None) -> None:
        """
        Range une entrée, en écrasant systématiquement la précédente.

        Les moteurs sérieux emploient des stratégies de remplacement plus
        fines (garder l'entrée la plus profonde, vieillir les entrées d'une
        recherche à l'autre). Ici l'écrasement simple suffit : on n'écrit
        jamais depuis la recherche de quiescence, donc toutes les entrées
        proviennent de recherches d'au moins un pli.
        """
        if len(self._table) >= self.entrees_max:
            # Vidage brutal plutôt qu'éviction fine : cela n'arrive qu'après
            # plusieurs minutes de réflexion, et coûte moins cher à gérer.
            self._table.clear()
        self._table[cle] = (profondeur, score, drapeau, coup)

    def vider(self) -> None:
        self._table.clear()
        self.lectures = 0
        self.trouvees = 0

    def __len__(self) -> int:
        return len(self._table)

    @property
    def taux(self) -> float:
        """Proportion de consultations qui ont trouvé quelque chose."""
        return self.trouvees / self.lectures if self.lectures else 0.0
