"""Contenu de l'onglet Tutoriel (ex-onglet Cours, entièrement remplacé) :
guide de prise en main pas à pas, contenu statique rédigé une fois pour
toutes (pas de CRUD comme l'ancien onglet Cours) — l'intro reste toujours
visible en haut de page, chaque chapitre est replié dans son propre
st.expander pour ne pas noyer le débutant sous un mur de texte d'un coup.
"""

import streamlit as st

INTRO = (
    "Tu ne connais rien au trading ? Aucun problème, c'est exactement pour ça que cette "
    "appli existe. Ici tu vas gérer un portefeuille avec de l'argent **virtuel**, sur des "
    "prix **réels** du marché. Zéro risque, tout l'apprentissage.\n\n"
    "Ce guide t'explique tout ce dont tu as besoin pour te lancer, dans l'ordre. Prends "
    "10 minutes pour le lire avant ton premier ordre, tu gagneras un temps fou après."
)

CHAPTERS = [
    ("1. Se connecter", """
**Petit point important** : il n'y a pas de session "permanente". Si tu fermes ton onglet ou ton navigateur, tu seras déconnecté et il faudra te reconnecter à ta prochaine visite. C'est normal, pas de panique si ça t'arrive.
"""),
    ("2. Comprendre ton portefeuille", """
Quand tu démarres, tu as un **portefeuille** avec un capital de départ virtuel.

### Ce que tu vois sur ton portefeuille

En haut de la page : la **valeur totale** de ton portefeuille et son évolution sur la journée.

Ensuite, une carte "Points clés" avec trois chiffres qu'il ne faut **pas confondre** :

- **Gain du jour** : la différence entre la valeur de ton portefeuille aujourd'hui et sa valeur la dernière fois que tu t'es connecté (un autre jour). Ce n'est pas forcément "depuis l'ouverture des marchés ce matin".
- **Gain total** : le gain ou la perte cumulée sur chaque position depuis le prix auquel tu l'as achetée. Ça peut remonter à plusieurs semaines.
- **Répartition par catégorie** : comment ton argent est réparti entre actions, cryptos, indices/ETF, etc. C'est calculé automatiquement, tu n'as rien à saisir.

**Pourquoi ces deux gains peuvent être très différents** : imagine que tu achètes une action *après* qu'elle ait déjà bien monté dans la journée. Ton **Gain du jour** peut être positif (le marché continue de monter un peu), alors que ton **Gain total** est négatif (tu as acheté "cher" par rapport à ton prix d'achat). Les deux indicateurs répondent à des questions différentes, c'est totalement normal que les chiffres divergent.

### Le tableau de tes positions

Chaque ligne = une position ouverte. Tu y retrouves le prix actuel, la quantité, le sens (voir plus bas), et surtout deux colonnes de gain :

- **Gain du jour** (€ et %) : comparé au prix de clôture d'hier.
- **Gain total** (€ et %) : comparé à ton prix d'achat moyen.

Tu peux cliquer sur le nom ou le symbole d'un actif à tout moment : ça t'amène directement sur sa fiche dans l'onglet Trading.

### La courbe de valeur

Elle retrace l'évolution de ton portefeuille jour après jour (pas heure par heure). Tu peux filtrer sur différentes périodes et même comparer ta performance à un indice de référence (CAC 40, S&P 500, etc.) pour voir si tu fais mieux ou moins bien que "le marché".

### L'historique de tes trades

Chaque achat, vente, ouverture ou clôture de position est gardé en mémoire, avec le gain ou la perte réalisée à chaque fois. Pratique pour te relire et comprendre tes propres décisions.
"""),
    ("3. Trouver un actif à trader", """
Direction l'onglet **Trading**. Sur la page d'accueil, tu trouveras des vitrines toutes prêtes : indices majeurs, plus grosses capitalisations, cryptos les plus suivies, et Forex/matières premières.

Tu cherches un actif précis ? Utilise la barre de recherche : tape un nom ou un ticker (le "code" d'une action, par exemple `AAPL` pour Apple). Si rien ne sort et que tu connais le ticker exact, tu peux le taper directement.

Une fois sur la fiche d'un actif, tu as le prix (dans sa devise d'origine et converti en euros), et un graphique que tu peux personnaliser : différentes périodes (du jour à plusieurs années), et deux styles d'affichage — courbe simple ou **chandeliers** (bougies japonaises, le format classique en trading, à découvrir si tu ne connais pas).
"""),
    ("4. Comprendre Long vs Short", """
C'est une notion à bien avoir en tête avant de passer ton premier ordre.

- **Position longue (Long)** : tu achètes un actif en pariant qu'il va **monter**. C'est le réflexe classique : "j'achète, puis je revends plus cher".
- **Position courte (Short)** : tu paries que l'actif va **baisser**, sans même le posséder au départ. Si le prix baisse effectivement, tu gagnes de l'argent. Si le prix monte, tu en perds. C'est l'inverse du Long.

Sur TradingSim, tu ne peux pas être Long **et** Short en même temps sur le même actif dans un même portefeuille. Il faut fermer une position avant d'en ouvrir une dans l'autre sens.
"""),
    ("5. Comprendre le levier et la marge (à lire avant de trader !)", """
Alors, on va être clair : c'est la partie la plus technique, mais aussi la plus fun à comprendre, alors accroche-toi, ça va bien se passer.

### Le levier, c'est quoi ?

Le **levier** te permet de contrôler une position plus grosse que l'argent que tu engages réellement. Sur TradingSim, tu peux choisir un levier de x1 (pas de levier, tu joues avec ton argent réel dans le simu) jusqu'à x20.

Exemple simple : avec 100€ et un levier x10, tu contrôles une position de 1000€. Si l'actif monte de 5%, ton gain est calculé sur les 1000€, pas sur tes 100€, ton gain est donc **amplifié**. Mais attention, ça marche aussi à la baisse : une perte est amplifiée exactement de la même façon.

Plus le levier est élevé, plus les mouvements de prix ont un impact fort sur ton portefeuille, dans les deux sens.

### La marge, c'est quoi ?

C'est la somme réellement débitée de ton cash disponible pour ouvrir une position à levier. Dans l'exemple au-dessus (position de 1000€ à levier x10), ta marge est de 100€ : c'est ce qui sort réellement de ton cash, pas les 1000€ complets.

### Un point important à connaître : la liquidation automatique

Le simulateur t'affiche un "prix de liquidation auto. estimé" quand tu prépares un ordre à levier. Ce n'est **pas** qu'une info indicative : au-delà de x1, une position est réellement **fermée automatiquement** dès que sa perte latente atteint 80% de la marge engagée (marge de maintenance à 20%, comme sur un vrai broker) — même si tu n'as pas l'application ouverte, vérifié toutes les 15 minutes en arrière-plan. Ta perte reste donc plafonnée à environ 80% de ta marge, elle ne peut pas dépasser 100% de ce que tu as engagé.

Une position sans levier (x1) n'est en revanche jamais liquidée automatiquement : elle reste ouverte quoi qu'il arrive, c'est toi qui décides quand la clôturer.

Sur la fiche d'une position à levier que tu détiens, une jauge t'indique en direct où tu en es par rapport à ce seuil — surveille-la, surtout à fort levier, pour réagir avant d'être liquidé si tu préfères garder la main sur ta sortie !
"""),
    ("6. Passer un ordre", """
Une fois sur la fiche d'un actif, tu trouveras un formulaire pour passer ton ordre. Les options proposées changent selon ta situation :

- Tu n'as aucune position sur ce ticker → tu peux **Acheter** (Long) ou **Vendre à découvert** (Short).
- Tu as déjà une position Longue → tu peux **Acheter plus** (renforcer) ou **Vendre** (clôturer).
- Tu as déjà une position Courte → tu peux **Vendre plus à découvert** (renforcer) ou **Racheter** (clôturer).

Si tu renforces une position existante, ton prix moyen d'achat est recalculé automatiquement en tenant compte du nouveau prix — pas juste écrasé par le dernier prix payé.

### Le montant à risquer, pas la quantité — pour la crypto seulement

Pour ouvrir ou renforcer une position **sur une crypto** (achat, vente à découvert), tu ne saisis pas directement une quantité — tu indiques le **montant en euros que tu acceptes d'engager** (ta marge), exactement comme sur les plateformes de trading à effet de levier usuelles (Binance Futures, eToro...). La taille de ta position s'en déduit automatiquement :

`Taille de position (€) = Montant à risquer (€) × Levier`, puis convertie en quantité fractionnée au prix courant.

Exemple : 500 € engagés avec un levier x2 → une position de 1000 €. Le montant à risquer ne peut jamais dépasser ton cash disponible.

Pour une **action, un ETF ou un indice**, en revanche, tu indiques directement un **nombre entier de titres** (une action ne se fractionne pas dans la réalité, contrairement à une crypto) — le coût total et la marge nécessaire s'affichent juste en dessous une fois la quantité choisie. Pour **clôturer** une position existante (Vendre, Racheter), c'est dans tous les cas bien une quantité que tu indiques, quelle que soit la classe d'actif.

### Ordre au marché vs ordre à cours limité

- **Ordre au marché** : exécution immédiate, au prix affiché à l'instant T.
- **Ordre à cours limité** : tu fixes un prix cible, et l'ordre s'exécute automatiquement seulement quand le marché atteint ce niveau. Tu peux voir tous tes ordres en attente et les annuler à tout moment si tu changes d'avis.

Avant de valider, un récapitulatif t'indique le coût total, la marge nécessaire, et une simulation de ton gain/perte si le prix bouge de ±5% ou ±10%. Prends toujours 5 secondes pour le relire avant de cliquer.

Pour un ordre **au marché** qui ouvre ou renforce une position, tu peux aussi cocher "Ajouter un ou plusieurs paliers Take Profit / Stop Loss dès l'ouverture" pour poser tes paliers de sortie automatique en même temps que ton achat — sans avoir à y revenir juste après (voir le chapitre suivant sur le Take Profit / Stop Loss si tu ne connais pas encore ce mécanisme).
"""),
    ("Take Profit / Stop Loss : automatiser tes sorties", """
Sur la fiche d'une position que tu détiens, une section **Take Profit / Stop Loss** te permet de poser des paliers de sortie automatique : un prix cible **exact** (pas un pourcentage) et le **pourcentage de ta position** à vendre quand ce prix est atteint.

- **Take Profit** : tu sors (partiellement) avec un gain quand le prix atteint un niveau que tu juges satisfaisant.
- **Stop Loss** : tu limites ta perte si le prix se retourne contre toi.

Tu peux empiler plusieurs paliers sur la même position (ex : Take Profit à +10% pour la moitié, Stop Loss à -5% pour l'autre moitié) — rien n'oblige à couvrir 100% de la position, le reste continue de vivre comme une position normale.

Point important : le pourcentage d'un palier est calculé sur la quantité que tu détenais **au moment où tu as créé ce palier**, pas sur ce qu'il te reste au moment où il se déclenche. Si tu vends une partie de ta position entre-temps par un autre moyen, le palier s'ajuste automatiquement à ce qu'il reste réellement disponible plutôt que d'échouer.

Ces paliers sont vérifiés et exécutés automatiquement toutes les 15 minutes, **même si tu n'as pas l'application ouverte** — tu peux fermer ton navigateur, ton palier continuera de fonctionner. Tu peux annuler un palier à tout moment tant qu'il ne s'est pas encore déclenché. Une vente déclenchée ainsi apparaît dans ton historique avec la mention "Auto (TP/SL)", pour bien la distinguer d'une vente que tu as faite toi-même — à ne pas confondre avec la mention "Liquidation auto" (voir le chapitre précédent), qui signale elle une clôture forcée par manque de marge, pas un palier que tu as posé volontairement.
"""),
    ("7. Le classement", """
Dans l'onglet **Classement**, tu retrouves tous les participants triés par performance (P&L en euros et en %), recalculé en direct sur les prix actuels du marché. Ta ligne est repérée par "(toi)" pour la retrouver facilement. Si tu as plusieurs portefeuilles, seul ton **portefeuille officiel** (unique et défini une fois pour toutes) compte pour ton classement — tes éventuels autres portefeuilles fun/test n'y sont jamais comptabilisés. Clique sur un nom (le tien ou celui d'un autre participant) pour voir le détail de ses ordres et ses métriques de performance dans la page **Historique**.
"""),
    ("Pour résumer en 3 points avant de te lancer", """
1. **Long** = tu paries à la hausse, **Short** = tu paries à la baisse.
2. Le **levier** amplifie tes gains ET tes pertes — commence petit (x1 ou x2) le temps de bien comprendre le mécanisme.
3. Une position à levier est **liquidée automatiquement** si sa perte atteint 80% de la marge engagée : reste attentif à tes positions ouvertes, surtout à fort levier.

Le reste, c'est de la pratique. Lance-toi, explore, et n'hésite pas à revenir sur ce tutoriel si un terme te bloque. Bon trade à toi !
"""),
]


def render() -> None:
    # st.title (h1), pas st.subheader : ce texte fait partie du sélecteur CSS
    # mobile `body:has([data-testid="stExpandSidebarButton"]) h1` (voir
    # theme.py, testé réellement à 390px) qui évite le chevauchement avec le
    # bouton de réouverture du panneau latéral quand celui-ci est replié —
    # un changement de niveau de titre ici casserait ce correctif silencieusement.
    st.title("Bienvenue sur TradingSim")
    st.markdown(INTRO)
    st.divider()
    for title, content in CHAPTERS:
        with st.expander(title):
            st.markdown(content)
