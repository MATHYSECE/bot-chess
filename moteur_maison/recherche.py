"""
La recherche : explorer l'arbre des coups pour trouver le meilleur.

--- Negamax ---
Aux échecs, ce qui est bon pour moi est exactement mauvais pour l'adversaire.
On exploite cette symétrie pour n'écrire qu'une seule fonction au lieu de deux
(« maximiser » et « minimiser ») :

    valeur(position) = max sur les coups de ( - valeur(position après le coup) )

Le signe moins est tout l'algorithme. Chaque niveau retourne le point de vue.

--- L'élagage alpha-bêta ---
L'idée en une phrase : dès qu'un coup se révèle assez bon pour que l'adversaire
ne le laisse jamais arriver, inutile de savoir à quel point il est bon.

    alpha = ce que je me suis déjà garanti
    bêta  = ce que l'adversaire tolère au maximum

Si un coup donne un score ≥ bêta, l'adversaire aurait joué autrement plus haut
dans l'arbre : on abandonne cette branche (« coupure bêta »). Le résultat est
identique à celui d'une exploration complète, mais l'arbre exploré passe de
b^n à environ b^(n/2) — soit, à temps égal, deux fois plus de profondeur.

Cet exploit dépend entièrement de l'ORDRE des coups : si l'on essaie le
meilleur en premier, l'élagage est maximal. D'où l'importance du tri MVV-LVA
ci-dessous, et des techniques de l'étape 4b.

--- La recherche de quiescence ---
Le piège de toute recherche à profondeur fixe est « l'effet d'horizon » :
arrêter le calcul au milieu d'un échange et croire qu'on a gagné une dame,
alors que la reprise arrive au coup suivant. La parade est de ne jamais
s'arrêter sur une position agitée : arrivé à la profondeur 0, on continue à
explorer les seules captures jusqu'à atteindre le calme.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import chess

from moteur_maison.evaluation import evaluer
from moteur_maison.transposition import BORNE_INF, BORNE_SUP, EXACT, TableTransposition

# Score d'un mat. On soustrait la distance en demi-coups pour que le moteur
# préfère « mater en 2 » à « mater en 5 » : un mat plus proche vaut plus cher.
MAT = 30_000
SEUIL_MAT = 29_000       # au-delà, le score représente un mat, pas des pions
INFINI = 40_000

PLY_MAX = 100            # garde-fou contre une quiescence qui s'emballe

# Largeur de la premiere fenetre d'aspiration, en centipions. 30 = moins d'un
# tiers de pion : on parie que la profondeur suivante ne bougera pas beaucoup.
FENETRE_ASPIRATION = 30

# Au-dela, l'historique est divise par deux pour eviter que de vieux comptages
# ecrasent les recents.
SEUIL_HISTORIQUE = 60_000

# --- Etape 4c : elagages non surs ---
# Marge de securite de la futility inversee, par pli. 130 centipions, c'est a
# peu pres ce qu'un coup peut rapporter au maximum sans capture spectaculaire.
MARGE_FUTILITY = 130

# Profondeur minimale pour tenter le coup nul, et pour reduire les coups tardifs.
PROFONDEUR_MIN_NULL = 3
PROFONDEUR_MIN_LMR = 3

# Rang a partir duquel un coup tranquille est considere comme « tardif ».
RANG_LMR = 3

# Valeurs utilisées uniquement pour trier les captures, pas pour évaluer.
_VAL_TRI = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 10_000,
}


class TempsEcoule(Exception):
    """Levée au fond de l'arbre pour remonter d'un coup jusqu'à la surface."""


# --------------------------------------------------------------------------- #
# Scores de mat et table de transposition : le piège classique
# --------------------------------------------------------------------------- #
#
# « Mat en 3 » ne veut rien dire dans l'absolu : cela signifie « mat en 3 coups
# À PARTIR D'ICI ». Le score encode donc une distance, relative à l'endroit de
# l'arbre où on l'a trouvé.
#
# Si l'on range ce score tel quel et qu'on le relit depuis une autre profondeur,
# le moteur croit à un mat plus proche ou plus lointain qu'il ne l'est — et
# peut sacrifier sa dame pour un mat qui n'existe pas. C'est LE bug qui rend un
# moteur subtilement fou sans jamais le faire planter.
#
# La parade : ranger la distance depuis la RACINE, relire la distance depuis le
# nœud courant.


def _mat_vers_table(score: int, ply: int) -> int:
    """Convertit un score de mat relatif au nœud en score relatif à la racine."""
    if score > SEUIL_MAT:
        return score + ply
    if score < -SEUIL_MAT:
        return score - ply
    return score


def _mat_depuis_table(score: int, ply: int) -> int:
    """Opération inverse, à la relecture."""
    if score > SEUIL_MAT:
        return score - ply
    if score < -SEUIL_MAT:
        return score + ply
    return score


@dataclass
class Ligne:
    """Une variante trouvée à la racine : le coup, son score, la suite prévue."""

    coup: chess.Move
    score: int                                  # centipions, point de vue du trait
    pv: list[chess.Move] = field(default_factory=list)

    def mat_en(self) -> int | None:
        """Nombre de coups avant le mat, négatif si c'est nous qui le subissons."""
        if abs(self.score) < SEUIL_MAT:
            return None
        demi_coups = MAT - abs(self.score)
        coups = (demi_coups + 1) // 2
        return coups if self.score > 0 else -coups


@dataclass
class Contraintes:
    """Ce qui arrête la réflexion."""

    profondeur_max: int = 64
    temps_max: float | None = None       # en secondes
    noeuds_max: int | None = None
    multipv: int = 1


@dataclass
class Resultat:
    """Ce que la recherche a trouvé à une profondeur donnée."""

    profondeur: int
    lignes: list[Ligne]
    noeuds: int
    temps: float

    @property
    def meilleur_coup(self) -> chess.Move | None:
        return self.lignes[0].coup if self.lignes else None


class Recherche:
    """
    Le chercheur de coups.

    Un objet réutilisable : on l'instancie une fois, on l'appelle à chaque coup.
    À l'étape 4b il gardera sa table de transposition d'un appel à l'autre.
    """

    def __init__(self, sur_profondeur=None, utiliser_tt: bool = True,
                 utiliser_tri: bool = True, utiliser_elagage: bool = True):
        # Fonction appelée à la fin de chaque profondeur, pour que l'UCI puisse
        # publier une ligne « info » sans que la recherche connaisse le protocole.
        self.sur_profondeur = sur_profondeur
        self.arret = threading.Event()

        # La table survit d'un coup à l'autre : ce que le moteur a compris en
        # réfléchissant à son 12e coup reste utile au 13e, puisque les positions
        # analysées alors se retrouvent réellement sur l'échiquier.
        # L'interrupteur permet de mesurer exactement ce que la table rapporte.
        self.utiliser_tt = utiliser_tt
        self.tt = TableTransposition()

        # --- Étape 4b-2 : tri fin et fenêtres étroites ---
        self.utiliser_tri = utiliser_tri

        # Killer moves : deux coups tranquilles par niveau, ceux qui ont déjà
        # provoqué une coupure ailleurs dans l'arbre à la même profondeur.
        self._killers: list[list[chess.Move | None]] = [[None, None] for _ in range(PLY_MAX)]

        # Historique : [couleur][case de départ][case d'arrivée] -> combien de
        # fois ce coup a provoqué une coupure. Généralise les killers à tout
        # l'arbre au lieu d'un seul niveau.
        self._historique = [[[0] * 64 for _ in range(64)] for _ in range(2)]

        # --- Étape 4c : les élagages non sûrs ---
        # Contrairement à tout ce qui précède, ces techniques CHANGENT le
        # résultat : elles coupent des branches qui pourraient contenir le
        # meilleur coup. On les active par pari statistique, et on les valide
        # par des tests tactiques, pas par comparaison de scores.
        self.utiliser_elagage = utiliser_elagage

        self.noeuds = 0
        self._debut = 0.0
        self._echeance: float | None = None
        self._noeuds_max: int | None = None
        self._peut_arreter = False

        # Table de variante principale, dite « triangulaire » : la ligne `ply`
        # contient la meilleure suite trouvée depuis ce niveau.
        self._pv = [[None] * PLY_MAX for _ in range(PLY_MAX)]
        self._pv_long = [0] * PLY_MAX

        # Clés des positions traversées, pour détecter les répétitions.
        self._cles: list = []

    # ------------------------------------------------------------------ #
    # Point d'entrée
    # ------------------------------------------------------------------ #

    def chercher(self, echiquier: chess.Board, contraintes: Contraintes) -> Resultat:
        """
        Approfondissement itératif : on cherche à la profondeur 1, puis 2, etc.

        Chercher plusieurs fois de suite semble du gaspillage. C'est au
        contraire un gain net : la recherche à la profondeur n-1 fournit un
        excellent ordre de coups pour la profondeur n, et un meilleur ordre
        élague tellement mieux que le surcoût est largement remboursé. Bonus
        indispensable : on a toujours un coup jouable sous la main quand le
        temps s'épuise.
        """
        self.arret.clear()
        self.noeuds = 0
        self._debut = time.perf_counter()
        self._echeance = (
            self._debut + contraintes.temps_max if contraintes.temps_max else None
        )
        self._noeuds_max = contraintes.noeuds_max
        self._peut_arreter = False
        self._cles = self._cles_initiales(echiquier)

        plateau = echiquier.copy()
        multipv = max(1, contraintes.multipv)

        # Les killers sont propres à une position de départ : ceux d'un coup
        # précédent ne veulent plus rien dire. L'historique, lui, est conservé —
        # il se périme tout seul par division (voir `_noter_historique`).
        self._killers = [[None, None] for _ in range(PLY_MAX)]

        dernier = Resultat(0, [], 0, 0.0)
        ordre_racine: list[chess.Move] = []

        for profondeur in range(1, contraintes.profondeur_max + 1):
            try:
                # L'aspiration a besoin d'une estimation, donc d'au moins une
                # itération précédente. Et elle n'a de sens qu'en variante
                # unique : avec MultiPV, on veut le score exact de chaque ligne.
                if (self.utiliser_tri and multipv == 1
                        and profondeur >= 4 and dernier.lignes):
                    lignes = self._racine_aspiration(
                        plateau, profondeur, ordre_racine, dernier.lignes[0].score
                    )
                else:
                    lignes = self._racine(plateau, profondeur, multipv, ordre_racine)
            except TempsEcoule:
                break

            if not lignes:
                break

            # Les coups de cette itération, meilleur en tête, serviront d'ordre
            # de départ à la suivante.
            ordre_racine = [ligne.coup for ligne in lignes]
            dernier = Resultat(
                profondeur=profondeur,
                lignes=lignes,
                noeuds=self.noeuds,
                temps=time.perf_counter() - self._debut,
            )
            self._peut_arreter = True

            if self.sur_profondeur:
                self.sur_profondeur(dernier)

            # Un mat trouvé rend inutile toute recherche plus profonde.
            if lignes[0].mat_en() is not None and multipv == 1:
                break
            if self._temps_epuise() or self.arret.is_set():
                break

        return dernier

    # ------------------------------------------------------------------ #
    # Racine
    # ------------------------------------------------------------------ #

    def _racine_aspiration(
        self,
        plateau: chess.Board,
        profondeur: int,
        ordre_precedent: list[chess.Move],
        estimation: int,
    ) -> list[Ligne]:
        """
        Cherche dans une fenêtre étroite centrée sur le score de l'itération précédente.

        --- L'idée ---
        À la profondeur 9, on connaît déjà le résultat de la profondeur 8. Il
        est très rare qu'un pli de plus change l'évaluation de plus d'un tiers
        de pion. Plutôt que de chercher entre −∞ et +∞, on parie donc sur un
        résultat proche : chercher dans une fenêtre étroite provoque beaucoup
        plus de coupures, donc va beaucoup plus vite.

        --- Le prix du pari ---
        Si le vrai score tombe hors de la fenêtre, la recherche ne renvoie
        qu'une borne : il faut tout recommencer en plus large, et le temps passé
        est perdu. On élargit alors par quatre à chaque échec, puis on repasse
        en fenêtre complète si l'écart s'obstine — ce qui arrive typiquement
        quand le moteur vient de découvrir un mat ou une pièce perdue.

        Le pari est gagnant en moyenne : les échecs sont rares et les
        économies, constantes.
        """
        delta = FENETRE_ASPIRATION

        while True:
            alpha = estimation - delta
            beta = estimation + delta

            lignes = self._racine(plateau, profondeur, 1, ordre_precedent, alpha, beta)
            if not lignes:
                return lignes

            score = lignes[0].score
            if alpha < score < beta:
                return lignes              # le pari a tenu

            delta *= 4
            if delta > 1200:
                # Le score s'est effondré ou envolé : fenêtre complète.
                return self._racine(plateau, profondeur, 1, ordre_precedent)

    def _racine(
        self,
        plateau: chess.Board,
        profondeur: int,
        multipv: int,
        ordre_precedent: list[chess.Move],
        alpha_depart: int = -INFINI,
        beta: int = INFINI,
    ) -> list[Ligne]:
        """
        Recherche au niveau racine, avec gestion du multi-variantes.

        Pour obtenir N variantes distinctes, on relance simplement la recherche
        N fois en excluant à chaque tour les coups déjà retenus. C'est plus
        coûteux qu'un seul passage, mais c'est le seul moyen d'obtenir un score
        EXACT pour chaque variante : dans une recherche normale, les coups
        inférieurs ne reçoivent qu'une borne, pas une vraie évaluation.
        """
        tous = list(plateau.generate_legal_moves())
        if not tous:
            return []

        lignes: list[Ligne] = []
        exclus: set[chess.Move] = set()

        for _ in range(multipv):
            candidats = [c for c in self._ordre_racine(plateau, tous, ordre_precedent)
                         if c not in exclus]
            if not candidats:
                break

            alpha = alpha_depart
            meilleur = None
            meilleur_score = -INFINI
            meilleure_pv: list[chess.Move] = []

            for rang, coup in enumerate(candidats):
                score = self._essayer(plateau, coup, profondeur, alpha, beta, 1,
                                      premier=(rang == 0))

                if score > meilleur_score:
                    meilleur_score = score
                    meilleur = coup
                    self._noter_pv(coup, 0)
                    meilleure_pv = self._lire_pv()
                    if score > alpha:
                        alpha = score
                    if score >= beta:
                        break        # sort de la fenêtre d'aspiration

            lignes.append(Ligne(coup=meilleur, score=meilleur_score, pv=meilleure_pv))
            exclus.add(meilleur)

        return lignes

    @staticmethod
    def _a_des_pieces(plateau: chess.Board) -> bool:
        """
        Le camp au trait possède-t-il autre chose que des pions et son roi ?

        C'est le garde-fou anti-zugzwang du coup nul. Dans une finale de pions,
        « passer son tour » n'est pas une faveur mais un cadeau : la position
        peut être perdue précisément parce qu'on est obligé de jouer.
        """
        mien = plateau.occupied_co[plateau.turn]
        return bool(mien & ~plateau.pawns & ~plateau.kings)

    def _essayer(self, plateau, coup, profondeur, alpha, beta, ply,
                 premier: bool, reduction: int = 0) -> int:
        """
        Examine un coup, à fenêtre complète ou à fenêtre nulle selon son rang.

        --- La recherche à fenêtre nulle (PVS) ---
        Une fois le premier coup examiné à fond, on ne cherche plus à savoir
        COMBIEN valent les suivants, seulement S'ILS SONT PIRES. Une fenêtre
        large d'un seul centipion suffit à répondre à cette question, et coûte
        bien moins cher qu'une fenêtre complète.

        Si un coup surprend en dépassant quand même le premier, on le réexamine
        sérieusement. Le pari est le même que pour l'aspiration : les surprises
        sont rares si le tri est bon — et c'est justement pour ça que PVS et les
        killers vont ensemble. Un mauvais tri rendrait PVS contre-productif.
        """
        if premier or not self.utiliser_tri:
            return self._descendre(plateau, coup, profondeur - 1, -beta, -alpha, ply)

        # 1. Sondage à fenêtre nulle, éventuellement à profondeur réduite.
        score = self._descendre(plateau, coup, profondeur - 1 - reduction,
                                -alpha - 1, -alpha, ply)

        # 2. Le coup réduit a surpris : on le reprend à profondeur pleine.
        if reduction and score > alpha:
            score = self._descendre(plateau, coup, profondeur - 1, -alpha - 1, -alpha, ply)

        # 3. Il dépasse vraiment alpha : il faut sa valeur exacte.
        if alpha < score < beta:
            score = self._descendre(plateau, coup, profondeur - 1, -beta, -alpha, ply)
        return score

    def _ordre_racine(
        self,
        plateau: chess.Board,
        tous: list[chess.Move],
        precedent: list[chess.Move],
    ) -> list[chess.Move]:
        """Reprend l'ordre de l'itération précédente, puis trie le reste."""
        if not precedent:
            return self._trier(plateau, tous)
        connus = [c for c in precedent if c in tous]
        reste = self._trier(plateau, [c for c in tous if c not in precedent])
        return connus + reste

    # ------------------------------------------------------------------ #
    # Negamax
    # ------------------------------------------------------------------ #

    def _descendre(self, plateau, coup, profondeur, alpha, beta, ply) -> int:
        """Joue un coup, cherche, reprend le coup. Le signe moins est le negamax."""
        plateau.push(coup)
        self._cles.append(plateau._transposition_key())
        try:
            return -self._negamax(plateau, profondeur, alpha, beta, ply)
        finally:
            # `finally` garantit que l'échiquier est restauré même si le temps
            # s'épuise et qu'une exception traverse toute la pile d'appels.
            self._cles.pop()
            plateau.pop()

    def _negamax(self, plateau: chess.Board, profondeur: int,
                 alpha: int, beta: int, ply: int) -> int:
        self.noeuds += 1
        # Consulter l'horloge coûte cher : on ne le fait qu'un nœud sur 2048.
        if not self.noeuds & 2047:
            self._verifier_arret()

        self._pv_long[ply] = ply

        # La nulle par répétition dépend du CHEMIN parcouru, pas seulement de la
        # position. Elle doit donc être testée avant toute consultation de la
        # table, qui, elle, ignore l'historique.
        if self._est_nulle(plateau):
            return 0

        # « Mate distance pruning » : si un mat plus rapide est déjà garanti
        # ailleurs, cette branche ne peut plus rien apporter.
        if alpha < -MAT + ply:
            alpha = -MAT + ply
        if beta > MAT - ply - 1:
            beta = MAT - ply - 1
        if alpha >= beta:
            return alpha

        # La clé est déjà calculée : `_descendre` l'a empilée pour la détection
        # de répétition. La consultation de la table est donc gratuite.
        cle = self._cles[-1]
        alpha_initial = alpha
        coup_tt = None

        if self.utiliser_tt:
            entree = self.tt.lire(cle)
            if entree is not None:
                prof_tt, score_tt, drapeau, coup_tt = entree
                # Un score établi moins profondément que ce qu'on demande
                # aujourd'hui ne vaut rien — sauf son coup, toujours bon à trier.
                if prof_tt >= profondeur:
                    score_tt = _mat_depuis_table(score_tt, ply)
                    if drapeau == EXACT:
                        return score_tt
                    if drapeau == BORNE_INF and score_tt >= beta:
                        return score_tt
                    if drapeau == BORNE_SUP and score_tt <= alpha:
                        return score_tt

        if profondeur <= 0:
            return self._quiescence(plateau, alpha, beta, ply)

        en_echec = plateau.is_check()

        # ---------------------------------------------------------------- #
        # Étape 4c : les élagages non sûrs
        # ---------------------------------------------------------------- #
        # Deux conditions communes, valables pour les deux techniques :
        #   - jamais en échec : on n'a pas le loisir de faire des paris quand
        #     le roi est attaqué, il faut examiner les parades ;
        #   - jamais près d'un score de mat : ces raccourcis raisonnent en
        #     pions, ils n'ont aucune validité face à un mat forcé.
        if self.utiliser_elagage and not en_echec and abs(beta) < SEUIL_MAT:

            # --- Futility inversée (« static null move ») ---
            # Près des feuilles, si la position est DÉJÀ tellement bonne qu'un
            # coup adverse normal ne suffirait pas à la ramener sous bêta, on
            # coupe sans explorer. La marge représente ce qu'un coup peut
            # raisonnablement rapporter ; on la prend large pour ne pas couper
            # une position seulement un peu au-dessus.
            if profondeur <= 3:
                statique = evaluer(plateau)
                if statique - MARGE_FUTILITY * profondeur >= beta:
                    return beta

            # --- Coup nul (null-move pruning) ---
            # On offre à l'adversaire de jouer deux fois de suite. S'il n'arrive
            # même pas à faire tomber la position sous bêta avec ce cadeau, la
            # position est si solide qu'elle ne mérite pas d'être explorée.
            #
            # Le piège est le ZUGZWANG : dans certaines finales, être obligé de
            # jouer est un désavantage, et « passer son tour » serait donc un
            # cadeau empoisonné plutôt qu'une faveur. Le raisonnement s'effondre.
            # Le zugzwang exigeant peu de matériel, on exige que le camp au trait
            # possède au moins une pièce autre que des pions et son roi.
            if profondeur >= PROFONDEUR_MIN_NULL and self._a_des_pieces(plateau):
                reduction = 2 + profondeur // 6
                plateau.push(chess.Move.null())
                self._cles.append(plateau._transposition_key())
                try:
                    score = -self._negamax(
                        plateau, profondeur - 1 - reduction, -beta, -beta + 1, ply + 1
                    )
                finally:
                    self._cles.pop()
                    plateau.pop()

                # On renvoie bêta et non le score : un coup nul ne peut pas
                # prouver un mat, et laisser remonter un score de mat obtenu
                # ainsi contaminerait toute la recherche.
                if score >= beta:
                    return beta

        coups = self._trier(plateau, list(plateau.generate_legal_moves()), coup_tt, ply)
        if not coups:
            # Aucun coup légal : mat si l'on est en échec, pat sinon.
            return -MAT + ply if en_echec else 0

        # Recherche « fail-soft » : on renvoie la meilleure valeur réellement
        # constatée, et non la borne alpha ou bêta. C'est plus informatif pour
        # la table, qui range ainsi des bornes plus serrées.
        meilleur = -INFINI
        meilleur_coup = None

        tueurs = self._killers[ply]

        for rang, coup in enumerate(coups):
            # --- Réductions de coups tardifs (LMR) ---
            # Si le tri est bon, le meilleur coup est presque toujours dans les
            # trois premiers. Les suivants sont examinés moins profondément :
            # on parie qu'ils ne valent rien. Si l'un d'eux dépasse quand même
            # alpha, `_essayer` le réexamine à profondeur pleine — le pari
            # coûte alors du temps, mais ne fait jamais perdre le coup.
            #
            # On ne réduit jamais : les captures et promotions (déjà bien
            # triées et souvent décisives), les killers (démontrés bons
            # ailleurs), les coups qui DONNENT ÉCHEC, ni quoi que ce soit
            # quand on est soi-même en échec.
            #
            # L'exclusion des échecs n'est pas un raffinement facultatif : elle
            # a été ajoutée après que le test tactique a montré 4c ratant un mat
            # en 3. Le coup mateur était tranquille mais donnait échec ; réduit
            # de deux plis, le mat passait sous l'horizon, et la recherche
            # réduite ne dépassant jamais alpha, aucune relance à profondeur
            # pleine ne venait rattraper l'erreur.
            reduction = 0
            if (self.utiliser_elagage and rang >= RANG_LMR
                    and profondeur >= PROFONDEUR_MIN_LMR
                    and not en_echec
                    and not coup.promotion
                    and coup != tueurs[0] and coup != tueurs[1]
                    and not plateau.is_capture(coup)
                    and not plateau.gives_check(coup)):
                reduction = 1 if rang < 6 else 2
                # Ne jamais réduire au point de sauter la quiescence.
                reduction = min(reduction, profondeur - 2)

            score = self._essayer(plateau, coup, profondeur, alpha, beta, ply + 1,
                                  premier=(rang == 0), reduction=reduction)

            if score > meilleur:
                meilleur = score
                meilleur_coup = coup
                if score > alpha:
                    alpha = score
                    self._noter_pv(coup, ply)
                    if alpha >= beta:
                        # Coupure : l'adversaire évitera cette ligne. On retient
                        # le coup qui l'a provoquée, s'il est tranquille — les
                        # captures sont déjà bien triées par MVV-LVA.
                        if self.utiliser_tri and not coup.promotion \
                                and not plateau.is_capture(coup):
                            self._noter_killer(coup, ply)
                            self._noter_historique(plateau.turn, coup, profondeur)
                        break

        if self.utiliser_tt:
            if meilleur <= alpha_initial:
                drapeau = BORNE_SUP      # aucun coup n'a atteint alpha
            elif meilleur >= beta:
                drapeau = BORNE_INF      # coupure : la vraie valeur est au moins celle-ci
            else:
                drapeau = EXACT
            self.tt.ecrire(cle, profondeur, _mat_vers_table(meilleur, ply),
                           drapeau, meilleur_coup)

        return meilleur

    def _quiescence(self, plateau: chess.Board, alpha: int, beta: int, ply: int) -> int:
        """
        Prolonge la recherche jusqu'à une position calme.

        Deux régimes :
          - en échec, on examine TOUS les coups légaux. Se limiter aux captures
            ferait manquer un mat, et rien n'est plus faux qu'un moteur qui
            croit s'échapper d'un mat forcé ;
          - sinon, on ne regarde que les captures, avec le « stand pat » :
            ne rien faire est toujours une option, donc l'évaluation actuelle
            est un plancher.
        """
        self.noeuds += 1
        if not self.noeuds & 2047:
            self._verifier_arret()

        self._pv_long[ply] = ply

        if ply >= PLY_MAX - 1:
            return evaluer(plateau)

        en_echec = plateau.is_check()

        if en_echec:
            coups = self._trier(plateau, list(plateau.generate_legal_moves()))
            if not coups:
                return -MAT + ply
        else:
            immobile = evaluer(plateau)
            if immobile >= beta:
                return beta
            if immobile > alpha:
                alpha = immobile
            coups = self._trier(plateau, list(plateau.generate_legal_captures()))

        for coup in coups:
            plateau.push(coup)
            try:
                score = -self._quiescence(plateau, -beta, -alpha, ply + 1)
            finally:
                plateau.pop()

            if score >= beta:
                return beta
            if score > alpha:
                alpha = score

        return alpha

    # ------------------------------------------------------------------ #
    # Tri des coups
    # ------------------------------------------------------------------ #

    def _noter_killer(self, coup: chess.Move, ply: int) -> None:
        """
        Retient un coup tranquille ayant provoqué une coupure à ce niveau.

        Pourquoi ça marche : à un niveau donné de l'arbre, les positions sœurs
        se ressemblent beaucoup — elles ne diffèrent que par un coup joué plus
        haut. Une fourchette ou un mat qui fonctionne contre une réponse
        fonctionne très souvent contre les autres. On garde les deux derniers,
        le plus récent en tête.
        """
        tueurs = self._killers[ply]
        if tueurs[0] != coup:
            tueurs[1] = tueurs[0]
            tueurs[0] = coup

    def _noter_historique(self, couleur: chess.Color, coup: chess.Move, profondeur: int) -> None:
        """
        Compte les coupures par couple (case de départ, case d'arrivée).

        C'est la généralisation des killers : au lieu de ne valoir que pour un
        niveau, le compteur vaut pour tout l'arbre. Le bonus est le CARRÉ de la
        profondeur, parce qu'une coupure obtenue profondément a demandé
        beaucoup plus de travail — elle en dit donc bien plus long qu'une
        coupure trouvée à un pli de la surface.
        """
        table = self._historique[couleur]
        table[coup.from_square][coup.to_square] += profondeur * profondeur

        if table[coup.from_square][coup.to_square] > SEUIL_HISTORIQUE:
            # Division générale par deux : sans elle, les comptages accumulés en
            # début de partie écraseraient définitivement l'information récente.
            for depart in range(64):
                ligne = table[depart]
                for arrivee in range(64):
                    ligne[arrivee] >>= 1

    def _trier(self, plateau: chess.Board, coups: list[chess.Move],
               prioritaire: chess.Move | None = None,
               ply: int | None = None) -> list[chess.Move]:
        """
        Trie les coups pour maximiser l'élagage : captures juteuses en tête.

        MVV-LVA, pour « Most Valuable Victim, Least Valuable Aggressor » :
        prendre une dame avec un pion est le coup le plus prometteur qui soit,
        prendre un pion avec sa dame le moins. On multiplie la victime par 10
        pour qu'elle domine toujours l'agresseur dans le classement.

        `prioritaire` est le coup retenu par la table de transposition. Il passe
        avant tout le reste : c'est un coup déjà démontré bon dans cette
        position exacte, alors que MVV-LVA ne fait qu'une supposition.
        """
        if len(coups) < 2:
            return coups

        ep = plateau.ep_square
        type_a = plateau.piece_type_at
        notes = {}

        # Killers et historique ne s'appliquent qu'aux nœuds ordinaires : la
        # quiescence n'examine que des captures, déjà triées par MVV-LVA.
        fin = ply is not None and self.utiliser_tri
        tueurs = self._killers[ply] if fin else (None, None)
        histoire = self._historique[plateau.turn] if fin else None

        for coup in coups:
            victime = type_a(coup.to_square)
            if victime is None and coup.to_square == ep and type_a(coup.from_square) == chess.PAWN:
                victime = chess.PAWN    # prise en passant

            if coup == prioritaire:
                note = 1_000_000     # le coup de la table, toujours en premier
            elif victime is not None:
                note = 100_000 + _VAL_TRI[victime] * 10 - _VAL_TRI[type_a(coup.from_square)]
            elif coup.promotion:
                note = 90_000 + _VAL_TRI[coup.promotion]
            elif coup == tueurs[0]:
                note = 80_000
            elif coup == tueurs[1]:
                note = 79_000
            elif histoire is not None:
                # Plafonné pour qu'un compteur élevé ne passe jamais devant un
                # killer, qui est une information bien plus ciblée.
                note = min(histoire[coup.from_square][coup.to_square], 78_000)
            else:
                note = 0
            notes[coup] = note

        coups.sort(key=notes.__getitem__, reverse=True)
        return coups

    # ------------------------------------------------------------------ #
    # Nulles
    # ------------------------------------------------------------------ #

    def _cles_initiales(self, echiquier: chess.Board) -> list:
        """
        Reconstitue les positions déjà survenues dans la partie réelle.

        Sans cet historique, le moteur ne verrait pas qu'il répète une position
        déjà jouée deux fois et offrirait la nulle sans le savoir — ou passerait
        à côté d'une nulle salvatrice dans une position perdue.
        """
        temporaire = echiquier.copy()
        joues = []
        while temporaire.move_stack:
            joues.append(temporaire.pop())

        cles = [temporaire._transposition_key()]
        for coup in reversed(joues):
            temporaire.push(coup)
            cles.append(temporaire._transposition_key())
        return cles

    def _est_nulle(self, plateau: chess.Board) -> bool:
        """Répétition, règle des 50 coups, ou matériel insuffisant."""
        if plateau.halfmove_clock >= 100:
            return True

        # `is_insufficient_material` n'est pas gratuit : on ne l'appelle que
        # lorsqu'il reste assez peu de pièces pour que ce soit envisageable.
        if chess.popcount(plateau.occupied) <= 4 and plateau.is_insufficient_material():
            return True

        # Répétition : on remonte l'historique de deux en deux (seules les
        # positions où le même camp a le trait peuvent se répéter), sans
        # dépasser le dernier coup irréversible.
        cle = self._cles[-1]
        recul = min(plateau.halfmove_clock, len(self._cles) - 1)
        i = len(self._cles) - 3
        limite = len(self._cles) - 1 - recul
        while i >= limite:
            if self._cles[i] == cle:
                return True
            i -= 2
        return False

    # ------------------------------------------------------------------ #
    # Variante principale
    # ------------------------------------------------------------------ #

    def _noter_pv(self, coup: chess.Move, ply: int) -> None:
        """
        Enregistre le coup et recopie la suite trouvée un niveau plus bas.

        La table est dite « triangulaire » : chaque niveau ne remplit que la
        portion à droite de sa propre colonne, et hérite du reste de son enfant.
        """
        self._pv[ply][ply] = coup
        enfant = self._pv[ply + 1]
        ligne = self._pv[ply]
        for i in range(ply + 1, self._pv_long[ply + 1]):
            ligne[i] = enfant[i]
        self._pv_long[ply] = max(self._pv_long[ply + 1], ply + 1)

    def _lire_pv(self) -> list[chess.Move]:
        return [self._pv[0][i] for i in range(self._pv_long[0])]

    # ------------------------------------------------------------------ #
    # Arrêt
    # ------------------------------------------------------------------ #

    def _temps_epuise(self) -> bool:
        return self._echeance is not None and time.perf_counter() >= self._echeance

    def _verifier_arret(self) -> None:
        """
        Interrompt la recherche, sauf si l'on n'a encore aucun coup à proposer.

        La garde `_peut_arreter` est essentielle : abandonner avant la fin de
        la profondeur 1 renverrait « aucun coup », ce qui perd la partie sur-le-
        champ. On accepte donc de dépasser légèrement le temps imparti plutôt
        que de rendre un coup nul.
        """
        if not self._peut_arreter:
            return
        if self.arret.is_set() or self._temps_epuise():
            raise TempsEcoule
        if self._noeuds_max is not None and self.noeuds >= self._noeuds_max:
            raise TempsEcoule
