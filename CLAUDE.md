# TradingSim — Contexte projet pour Claude Code

## Qui je suis
Je suis Edgar, débutant complet en développement/informatique. Explique-moi
TOUJOURS pas à pas ce qui touche au terminal, aux fichiers, à VS Code, GitHub,
Supabase ou Streamlit Cloud — ne suppose jamais rien acquis. En parallèle,
Claude (l'assistant de chat, hors VS Code) me sert de chef de projet
technique : il me rédige les prompts à t'envoyer, donc mes prompts peuvent
parfois être formulés de façon assez précise même si je reste débutant.

## Description du projet
Application de bureau (Streamlit/Python) : simulateur de trading fictif
complet installée et utilisée en local sur mon PC, avec plusieurs onglets.

## Stack technique
- Frontend/backend : Streamlit (Python)
- Base de données : Supabase (PostgreSQL)
- Données de marché : yfinance (actions/indices/ETF, gratuit, sans clé) et
  API publique Kraken (crypto, gratuit, sans clé)
- Déploiement : Streamlit Community Cloud
- Dépôt GitHub privé : edgarlescot2003-prog/TradingSim, branche main

## Fonctionnalités actuelles

### Onglet Portefeuille
Capital de départ configurable (EUR), plusieurs portefeuilles en parallèle
possibles (jusqu'à 3 par compte), bouton reset optionnel, fiche de position
complète (P&L €/%, prix moyen d'achat, date d'entrée, poids %), graphique
de performance dans le temps, comparaison à un indice de référence (CAC40,
S&P500...).

**Répartition par catégorie** (carte "Points clés", `ui_portfolio._allocation_by_category`) :
basée sur la **marge engagée** de chaque position (montant investi / levier),
pas l'exposition brute (prix × quantité) — avant le prompt 18.4, une
position à levier gonflait sa part bien au-delà de sa taille réelle en
capital (x10 sur 500 € de marge affichait 50 000 € d'exposition), faisant
dépasser 100% la somme des parts. Dénominateur : cash + Σ marges des
positions ouvertes — volontairement PAS `valuation.total_value` (qui inclut
le P&L latent via `equity_contribution_eur`) : cette répartition montre
comment le CAPITAL est engagé, pas la valeur courante après gains/pertes.
`valuation.total_value` (topbar, Classement...) utilisait déjà cette même
logique de marge (`equity_contribution_eur = margin_eur + pnl_eur`), donc
aucun second bug à corriger là — seule la répartition par catégorie avait
la régression (exposition brute).

**Portefeuille officiel** : parmi ses portefeuilles, un seul est désigné
"officiel" (badge ⭐) — c'est le seul compté pour le Classement, les autres
sont purement fun/test. Désigné automatiquement au tout premier portefeuille
d'un compte fraîchement créé ; pour un compte préexistant (comme le mien),
désignation ponctuelle et définitive depuis l'onglet Admin (irréversible
depuis l'interface une fois posée). Suppression du portefeuille officiel
bloquée. **À faire de mon côté** : testutilisateur/oscar/edgarv2 ont chacun
déjà un portefeuille mais aucun n'a encore de portefeuille officiel désigné
— ils sont donc absents du Classement tant que je n'ai pas fait cette
désignation pour chacun depuis l'Admin.

### Onglet Trading
Actions + crypto + indices/ETF (couverture US/Europe/Asie) + Forex (15
paires majeures/croisées, tickers yfinance `XXXYYY=X`) + matières premières
(or, argent, pétrole WTI/Brent, gaz naturel, tickers `XX=F`) + obligations
via ETF obligataires (TLT/IEF/BND/AGG/SHY — jamais les tickers de rendement
d'État bruts type `^TNX`, qui sont des % non négociables, incompatibles
avec le système de marge/P&L/liquidation). Ces 3 dernières classes sont une
extension pure du système existant (même marge/levier/liquidation/TP-SL/
short, aucune règle spécifique type horaires 24/5 ou taille de contrat) et
suivent la même détection de catégorie que Crypto pour le formulaire d'ordre
(voir "Saisie par montant à risquer" ci-dessous). Effet de levier, ordres
au marché et à cours limité. Layout de la fiche d'un actif en 2 colonnes
façon Hyperliquid (desktop) : graphique à gauche, panneau d'ordre + TP/SL
à droite (empilé sur mobile) — voir `ui_trading._render_price_and_chart`
(fragment) et `_render_order_form`.

**3 actions distinctes (Long/Vendre/Short)** : le formulaire d'ordre
affiche toujours 3 boutons explicitement labellisés — Long (vert, libellé
"Acheter" jusqu'au prompt 18, renommé "Long" pour cohérence avec la
terminologie déjà utilisée pour la position elle-même — voir `side`
"Long"/"Short" dans l'historique des trades — sans revenir au sélecteur à 2
options `Long`/`Short` du tout premier prompt 9, dont le libellé changeait
selon le contexte), Vendre (gris-bleu neutre, `theme.SELL_NEUTRAL`, distinct
du vert ET du rouge), Short (rouge). Vendre n'est actif que si une position
longue est détenue sur l'actif consulté (désactivé + infobulle sinon,
jamais un formulaire vide/une erreur technique) ; Long est désactivé si une
position courte est ouverte, et Short si une position longue est ouverte
(long et short mutuellement exclusifs sur un même ticker, règle déjà
imposée par `Portfolio.buy`/`open_short`, seulement reflétée dans l'UI).
Quand un short est déjà ouvert, l'onglet Short affiche un sous-choix
Renforcer/Racheter (mêmes 2 actions qu'avant, déplacées sous cet onglet).
Voir `ui_trading._render_action_tabs` (nouveau sélecteur à 3) et
`_render_side_toggle` (sous-choix Renforcer/Racheter, réutilisé). Valeur
interne inchangée ("acheter", utilisée par `ACTION_BY_ORDER_TYPE`,
`Trade.action`...) : seul le libellé AFFICHÉ a changé, y compris dans
l'historique des trades/ordres en attente/page Historique, qui réaffichaient
cette valeur interne telle quelle via `.capitalize()` (donc "Achat") avant
le prompt 18 — passés par `theme.action_label()` désormais, seul point qui
sait que "achat" s'affiche "Long" (les 3 autres valeurs gardent leur
capitalisation par défaut). Une ligne "Long" (achat) affiche donc désormais
le même mot dans ses colonnes Sens ET Action — redondance visuelle assumée,
pas corrigée dans ce prompt (renommage demandé, pas une refonte de ce
tableau).
Attention CSS : la coloration de ces boutons (et de l'ancien sélecteur à 2)
demande un sélecteur à 3 classes (`.st-key-ts_light .st-key-{clé}.stElementContainer
.stButton > button`, même technique que `theme.badge_color`) — un simple
`.st-key-{clé} button` se fait écraser par la règle générique
`.st-key-ts_light .stButton > button` (spécificité plus élevée), malgré le
`!important` des deux côtés. Piège déjà tombé dedans une fois, à ne pas
reproduire sur un futur bouton coloré dans `.st-key-ts_light`.

Graphiques avec sélecteur d'échelle temporelle progressif
(1J/1S/1M/3M/6M/YTD/1A/5A/Tout), granularité maximale à chaque échelle.
Tickers cliquables depuis le Portefeuille pour rejoindre directement la
fiche Trading de l'actif.
Le prix affiché et son graphique se rafraîchissent automatiquement toutes
les 30 secondes via `@st.fragment(run_every=30)`, isolé du reste de la
page. Le formulaire d'ordre (hors fragment) lit le prix via
`st.session_state` sans dupliquer d'appel API. Zoom à la molette/pinch
désactivé sur le graphique (`scrollZoom: False`, jugé peu pratique) : le
sélecteur de période reste le seul moyen de changer l'échelle affichée ;
survol et double-clic (reset du zoom) restent actifs, gérés par Plotly
indépendamment de ce réglage.

**Confirmation d'ordre en toast** : le message vert après achat/vente/short/
ordre à cours limité placé utilise `st.toast(..., duration=6)` (~6 secondes,
voir `ORDER_CONFIRMATION_TOAST_SECONDS`) plutôt que `st.success()`, qui
disparaissait quasi instantanément à cause du `st.rerun()` juste après —
`st.toast` est le seul mécanisme Streamlit qui survit à ce rerun. Contrepartie
assumée : le message s'affiche désormais en haut à droite (notification
Streamlit standard) plutôt qu'en bandeau vert inline dans le formulaire.

**Saisie par montant à risquer (Crypto/Forex/Matières premières/
Obligations)** : pour ouvrir/renforcer une position sur l'une de ces 4
classes (achat, short), l'utilisateur saisit un **montant en euros** (sa
marge, plafonnée à son cash disponible) plutôt qu'une quantité brute — la
taille de position s'en déduit (`montant × levier`, converti en quantité
fractionnée au prix de référence choisi, marché ou cours limité). Routage
par `ui_trading._uses_amount_input`, basé sur `valuation.category_for`
(quoteType yfinance si connu, sinon repli par syntaxe de ticker — ex.
`BTC-USD`, `EURUSD=X`, `GC=F` — puisque `st.session_state.selected_quote_type`
n'est jamais renseigné après une navigation, voir `theme.go_to_trading` ;
les ETF obligataires sont eux identifiés par une liste de tickers explicite,
`valuation.BOND_ETF_TICKERS`, un ETF obligataire ayant le même quoteType
"ETF" qu'un ETF actions/indices classique). Pour une **action/ETF/indice**
classique, le champ reste une **quantité entière de titres** (comportement
historique) : une action ne se fractionne pas dans la réalité, contrairement
aux 4 classes ci-dessus (simplification volontaire pour Forex/matières
premières/obligations, qui ont pourtant de vraies tailles de contrat/lots
dans la réalité — hors scope ici). Pour **clôturer** une position (Vendre, Racheter), la saisie
reste par quantité dans tous les cas, inchangée. La formule de liquidation
ne dépend que du prix et du levier (pas de la quantité), donc inchangée par
ce remaniement, quelle que soit la classe d'actif. Un ordre au marché
d'ouverture peut aussi inclure directement jusqu'à 3 paliers Take Profit /
Stop Loss (case à cocher dans le formulaire), créés juste après l'exécution
sur la position fraîchement ouverte — au-delà, ou pour un ordre à cours
limité (impossible avant que la position n'existe), les paliers
supplémentaires s'ajoutent après coup depuis la section dédiée.

**Take Profit / Stop Loss (TP/SL) par paliers** : sur la fiche d'une
position détenue, possibilité d'empiler plusieurs paliers (prix cible EXACT
en €, quantité en % de la position **au moment de la création du palier**,
figée une fois pour toutes — jamais recalculée sur la quantité résiduelle).
Pas de contrainte de somme à 100%. Annulation possible tant que non
déclenché. **S'exécute même quand personne n'a l'app ouverte** : un
workflow GitHub Actions dédié (`.github/workflows/check-tp-sl.yml`,
`scripts/check_tp_sl.py`) vérifie tous les paliers actifs toutes les 15
minutes contre le prix courant (yfinance, `market_data.get_quote` — même
source que le reste de l'app pour crypto et actions, Kraken n'est utilisé
nulle part pour un prix courant, seulement pour l'historique intrajournalier
des graphiques). Un palier dont la position d'origine n'existe plus dans le
même sens (fermée/inversée entre-temps) est auto-annulé ; une quantité figée
supérieure à ce qui reste réellement est plafonnée à la quantité
disponible, jamais bloquante. Plusieurs paliers déclenchés en même temps sur
la même position s'exécutent du plus proche du prix d'achat moyen au plus
loin. Les ventes/rachats déclenchés automatiquement sont marqués comme tels
(`TradeRow.tp_sl_order_id`) et affichés avec le badge "Auto (TP/SL)" dans
l'historique des trades (Portefeuille) et la page Historique (colonne
"Origine", CSV compris).

**Liquidation automatique par marge de maintenance** : une position à levier
(leverage > 1 ; jamais une position x1, dont la perte est déjà plafonnée à
100% de la marge par construction) est fermée automatiquement dès que sa
perte latente atteint 80% de sa marge engagée (marge de maintenance à 20%,
formule centralisée dans `src/valuation.py`, `MAINTENANCE_LOSS_RATIO`) :
`prix_liquidation = prix_entrée × (1 − 0.8/levier)` en long,
`× (1 + 0.8/levier)` en short. Avant cette fonctionnalité, le "prix de
liquidation" affiché dans le formulaire d'ordre (`_render_order_summary`)
n'était qu'indicatif (formule à 100%, jamais vérifiée nulle part) : une
position pouvait perdre plus que sa marge sans être jamais clôturée, ce qui
aurait pu fausser le Classement en cas de solde de portefeuille négatif.

**S'exécute même quand personne n'a l'app ouverte**, comme le TP/SL : un
script dédié (`scripts/check_liquidation.py`) tourne toutes les 15 minutes
via le même workflow GitHub Actions que le TP/SL
(`.github/workflows/check-tp-sl.yml`, deux steps séquentiels dans le même
job) — **le TP/SL est toujours vérifié en premier** (action volontaire de
l'utilisateur, qui prime), la liquidation en second, pour qu'une position
qui déclenche les deux au même run sorte via son palier plutôt que par une
liquidation forcée. Une liquidation clôture TOUJOURS la position en entier
(pas de notion de palier/pourcentage comme pour le TP/SL). Réutilise
`Portfolio.sell()`/`cover_short()` (même logique que les clôtures manuelles
et le TP/SL) ; le trade créé est marqué `TradeRow.is_liquidation=True` et
affiché avec le badge "Liquidation auto" (distinct de "Auto (TP/SL)") dans
l'historique des trades et la page Historique. Un prix indisponible au
moment du check reporte simplement la vérification (jamais de liquidation
sur une donnée invalide).

Sur la fiche d'une position à levier détenue (onglet Trading), une jauge
(`ui_trading._render_maintenance_indicator`) affiche en direct le % de la
marge déjà perdu par rapport à ce seuil de 80%, pour que l'utilisateur
puisse réagir avant d'être liquidé.

### Onglet Cours
Ajout manuel de fiches de révision (pas d'automatisation via API pour
l'instant — décision volontaire), organisées par thème, recherche possible.

### Onglet Classement
Classement multi-utilisateurs trié par P&L en €, avec le P&L en % affiché
à côté. Ne prend en compte que le **portefeuille officiel** de chaque
utilisateur (voir Portefeuille officiel ci-dessus) — recalculé en temps
réel à chaque consultation, pour tout le monde. Ma propre ligne est repérée
par un "(toi)". Visible par tous les comptes connectés. Chaque nom est
cliquable et ouvre la page Historique de cet utilisateur (voir ci-dessous).

### Page Historique (accessible depuis le Classement)
Cliquer sur un nom dans le Classement ouvre l'historique complet de son
**portefeuille officiel** uniquement (jamais ses portefeuilles fun/test) :
tableau chronologique des ordres (date/heure, actif, sens, quantité, prix
d'exécution, montant total) avec export CSV, précédé de 4 métriques de
performance calculées sur la courbe de valeur du portefeuille (rendement
annualisé, volatilité annualisée, ratio de Sharpe, max drawdown). Le taux
sans risque du Sharpe (Euribor 3 mois) est une valeur fixe codée en dur
dans `src/history.py` (`RISK_FREE_RATE`, 2,64 %/an) — à mettre à jour ici
si le taux change significativement. En dessous de 30 jours de données
(`MIN_RELIABLE_DAYS`), les métriques restent affichées mais avec une
mention explicite du nombre de jours disponibles plutôt qu'une
annualisation silencieuse peu fiable.

Page **publique** : n'importe quel participant connecté peut consulter
l'historique et les métriques de risque de n'importe quel autre, en temps
réel pendant le concours — choix assumé pour la transparence/crédibilité du
concours (utile pour montrer les résultats aux professeurs MBFA en fin de
compétition), pas une fuite à corriger. Peut inciter à copier les positions
d'un leader ou changer les comportements en fin de concours : à garder en
tête si un participant s'en plaint, mais pas à remettre en question.

### Onglet News
Fil d'articles (titre, contenu, lien, image de couverture). Admin et
Contributeur peuvent publier librement (sans validation) ; suppression
réservée à l'Admin (y compris les news d'un Contributeur) ; lecture seule
pour un compte standard. Un article peut aussi être généré automatiquement
(voir "Notifications et engagement" ci-dessous) — affiché avec l'auteur
"Résumé automatique" (`NewsRow.is_system`), pas rattaché à un compte réel.

### Notifications et engagement
Trois fonctionnalités ajoutées pour donner des raisons de revenir sur l'app
pendant les 6 mois du concours, sous une contrainte stricte : **aucune ne
doit augmenter la fréquence/le volume d'appels aux API de prix**
(Kraken/Yahoo, déjà sous surveillance) — tout se construit à partir de
données déjà en base ou déjà récupérées ailleurs dans le même chargement de
page.

- **Résumé hebdomadaire automatique** (`src/weekly_summary.py`) : publié
  dans l'onglet News comme un article système (classement de la semaine des
  portefeuilles officiels, plus forte progression/baisse, actif le plus
  tradé). Pas de vrai scheduler dans ce projet (app Streamlit sans tâche de
  fond) : la génération est donc vérifiée à chaque démarrage du serveur
  (`weekly_summary.check_and_generate`, mis en cache 1h) plutôt qu'à heure
  fixe — un lundi sans connexion est rattrapé au prochain démarrage, quel
  que soit le jour. Dédoublonné par le titre exact de la semaine (pas de
  colonne dédiée), donc un titre d'article ne doit jamais être modifié à la
  main pour un résumé déjà publié.
- **Widget "Depuis le début du concours"** (`ui_portfolio._render_contest_progress`) :
  en tête de l'onglet Portefeuille (page d'accueil après connexion), variation
  du **portefeuille officiel** (pas forcément celui affiché/sélectionné) entre
  son capital de départ réel et sa valeur actuelle. Si le portefeuille officiel
  est celui déjà affiché, la valeur est en direct (gratuite, déjà calculée) ;
  sinon, repli sur le dernier point connu de sa courbe de valeur (peut être
  daté de plusieurs jours) plutôt qu'un nouvel appel de prix.
- **Alerte de variation de prix** : bannière affichée sur tous les onglets
  (`theme.render_movers_alert`, seuil `valuation.MOVER_THRESHOLD_PCT` = 5 %)
  quand une position **détenue** du portefeuille actif bouge de plus du seuil
  depuis la clôture précédente. Construite à partir des snapshots déjà
  calculés à chaque chargement de page (`valuation.total_value`, déjà
  nécessaire à l'affichage du P&L) — zéro appel réseau supplémentaire.
  Volontairement limitée aux positions détenues : couvrir aussi les actifs
  seulement "suivis" (recherchés sans être possédés) nécessiterait des
  appels API dédiés, ce qui violerait la contrainte ci-dessus.

### Onglet Règlement
Contenu statique du règlement du concours (participants, capital de départ,
durée, opérations autorisées, actifs éligibles, classement, récompense).
Chargé depuis `content/reglement.md` — un simple fichier texte séparé du
code, éditable directement sur GitHub (aucun redéploiement complexe, juste
un commit) sans toucher au code Python. Purement informatif : pas de case à
cocher/validation obligatoire pour utiliser l'app.

### Esthétique
Thème sombre partout (fond en dégradé fixe teal -> bleu-marine, inspiration
Revolut — remplace le thème clair des prompts 1 à 7 ; la structure posée par
ces prompts reste elle inchangée : pas de cases/bordures, séparation par
espacement, police monospace pour tous les chiffres) : dégradé du haut vers
le bas de l'écran (`#1B7A8C` -> `#0F4C5C` -> `#0A2A33`, `background-
attachment: fixed`), texte blanc uniforme (hiérarchie par taille/poids, pas
par variation de couleur — un blanc atténué en transparence pour le texte
secondaire), orange (`#F97316`) pour les éléments interactifs (boutons,
liens, onglet actif) — pas de bleu, trop proche de la teinte du dégradé de
fond pour bien s'en détacher — vert/rouge éclaircis (variantes 400) réservés
aux gains/pertes. Palette de badges par catégorie d'actif également
éclaircie pour rester lisible sur le dégradé (voir `theme.CATEGORY_COLORS`
et `theme.BADGE_DARK_TEXT`, la plupart des catégories basculant en texte
sombre sur badge clair avec cette palette). Palette pilotée par les
constantes de `src/theme.py` (BG/BG_GRADIENT/PANEL/BORDER/TEXT/MUTED/GREEN/
RED/ACCENT) et par `.streamlit/config.toml` (`[theme]`, `base = "dark"`
depuis ce changement — nécessaire en plus du CSS injecté pour que les
composants internes de Streamlit/BaseWeb — menus déroulants, popovers —
suivent aussi le thème sombre).

**Barre de valeur (topbar, `theme.render_topbar`)** : 3 indicateurs à droite
du logo — valeur totale, **liquidité disponible** (`portfolio.cash`, même
valeur que le garde-fou déjà utilisé pour refuser un ordre qui dépasserait
le solde, pas un nouveau calcul) et P&L du jour. Barre en `position: sticky`
(pas `fixed`), volontairement : passer sur 2 lignes si ça ne tient pas sur
une (voir Responsive mobile ci-dessous) ne recouvre jamais rien en dessous.

**Barre d'onglets sticky en desktop uniquement, topbar NON sticky**
(`.st-key-ts_tabbar` / `.ts-topbar`, prompt 19) : seule la barre d'onglets
reste fixée en haut au défilement (`position: sticky; top: 0`) — la topbar
(Valeur totale/Liquidité/P&L) défile normalement avec le reste du contenu.
Ce n'était PAS le comportement d'origine du prompt 19 : la topbar avait
`position: sticky` depuis bien avant ce prompt, et la première version
gardait ce comportement (les deux sticky, tabbar calée sous la topbar).
Edgar a demandé cette retouche une fois le sticky réellement fonctionnel
pour la première fois (voir le bug ci-dessous) : seule la barre d'onglets
doit rester visible en permanence. Fond de la barre d'onglets **plein**
(`BG_GRADIENT_TOP`, la teinte du haut du dégradé de fond — pas transparent
comme la topbar) : demandé par Edgar après avoir vu le texte défiler EN
TRANSPARENCE derrière les libellés d'onglets une fois réellement collée
(illisible) ; `BG_GRADIENT_TOP` reste cohérent avec le dégradé fixe de la
page (`background-attachment: fixed`) puisque c'est déjà la teinte qui s'y
affiche normalement en haut du viewport. Padding horizontal ajouté en même
temps (les onglets touchaient les bords du fond plein) — la marge droite
(7.5rem, comme la topbar) réserve la place de la barre d'outils native
Streamlit (stToolbar), qui flotte en haut à droite du viewport et peut
désormais chevaucher la barre d'onglets une fois collée (elle chevauchait
avant la topbar, qui n'est plus concernée). `position: sticky` (jamais
`fixed`) : `fixed` s'ancrerait au viewport entier et entrerait en conflit
de superposition avec le panneau latéral. Repasse en flux normal
(`position: static`) sur mobile.

**Bug réel découvert (et corrigé) en implémentant la 1ère version de ce
prompt** : la sticky de `.st-key-ts_tabbar` ne fonctionnait PAS du tout au
premier essai (repéré par Edgar : "reste toujours en haut" = ne s'accroche
jamais, défile comme avant). Diagnostic fait avec Playwright + un serveur
Streamlit local jetable (compte de test, cf. règle habituelle) :
**`.ts-topbar` était en fait déjà cassée elle aussi**, et l'était
probablement depuis toujours — jamais repéré faute d'avoir vraiment scrollé
une page assez longue en conditions réelles pendant les tests visuels
précédents (prompts 12/13/16, sans doute sur des pages trop courtes pour
que ça se voie). Cause : Streamlit enveloppe chaque élément dans une chaîne
de divs intermédiaires (`stElementContainer`, `stMarkdownContainer`,
`stVerticalBlock`, `stLayoutWrapper`, plus des divs sans `data-testid`)
entre le contenu réel et `[data-testid="stMainBlockContainer"]` — lui-même
enfant direct de `[data-testid="stMain"]`, qui est le VRAI conteneur qui
défile (`overflow: auto` ; `window.scrollY` reste à 0 même en scrollant la
page, tout se passe dans `stMain.scrollTop`). Une de ces enveloppes
intermédiaires empêche `position: sticky` de fonctionner pour tout ce
qu'elle contient, sans qu'aucune propriété individuelle testée isolément
(display, min-height, align-items, flex-grow/basis) n'ait suffi à elle
seule à expliquer/corriger le problème — seul un `display: contents` sur la
TOTALITÉ de la chaîne d'enveloppes (déclarée ou non) entre l'élément et
`stMainBlockContainer` règle le problème de façon fiable et reproductible.
Correctif : règle CSS `[data-testid="stMainBlockContainer"] :has(.st-key-ts_tabbar)
{ display: contents !important; }` (voir `theme.py`, juste après
`.ts-topbar` — ne cible plus que la barre d'onglets depuis que la topbar
n'est plus sticky, elle n'a donc plus besoin de ce correctif) — cible
PRÉCISÉMENT les enveloppes qui contiennent cet élément, quelle que soit
leur profondeur, sans toucher aux enveloppes identiques ailleurs sur la
page ; `display: contents` supprime seulement la boîte de l'enveloppe
(aucun padding/marge/bordure propre à perdre), le contenu reste normalement
stylé. **Vérifié visuellement avec un vrai Chromium (Playwright,
screenshots + mesures de position avant/après scroll)**, à chaque étape
(bug initial, puis retouche demandée par Edgar) : testé aussi bien en
scrollant à la souris qu'en forçant `scrollTop` directement.

**2ème bug réel découvert en implémentant la retouche ci-dessus** : une fois
le sticky et le fond bleu en place, Edgar a signalé "visuellement c'est
top mais les onglets ne sont pas cliquables". Reproduit avec Playwright
(`elementFromPoint` au centre d'un bouton d'onglet, barre collée après
scroll) : le clic était intercepté par `[data-testid="stToolbar"]`, la
barre d'outils native Streamlit (icônes Partager/étoile/crayon, bouton
replier/déplier le panneau latéral...). Cause : `[data-testid="stHeader"]`
(son parent) est rendu invisible par nos soins (`background: transparent;
height: 0`, tout en haut de ce bloc CSS) pour le remplacer visuellement par
notre topbar — mais `stToolbar` lui-même garde sa taille RÉELLE (~60px de
haut) et s'étend sur TOUTE la largeur du viewport, à un z-index natif très
élevé (~999990), avec son propre `pointer-events: auto` explicite dans la
feuille de style native de Streamlit (donc PAS neutralisé par un
`pointer-events: none` posé seulement sur son parent stHeader — vérifié :
`pointer-events` est hérité par défaut, mais une valeur explicite sur
l'enfant l'emporte toujours sur l'héritage, exactement ce que fait
Streamlit ici). Cette zone invisible captait donc tous les clics dans cette
bande, y compris sur nos propres onglets — jamais un problème avant
puisque rien d'autre de cliquable ne s'y trouvait (le sticky ne
fonctionnait pas, voir plus haut, et même une fois réparé la topbar sticky
n'avait rien de cliquable dans cette zone). Correctif : `pointer-events:
none !important` sur `stToolbar` lui-même (pas seulement stHeader),
`pointer-events: auto !important` restauré sur ses boutons/liens réels
(`stExpandSidebarButton` compris, vérifié toujours cliquable après coup) —
voir `theme.py`, juste après le masquage de `stHeader`. Revérifié avec
Playwright (`elementFromPoint` ne renvoie plus `stToolbar` mais bien
l'élément réel visé, clic bout-en-bout fonctionnel sur un onglet après
scroll, bouton replier/déplier le panneau latéral toujours opérationnel).

**Responsive mobile** : passe faite (media queries `@media max-width:640px`
dans `src/theme.py`) — échelle de police/paddings réduite globalement,
tableaux en cartes empilées sur petit écran, graphiques Trading avec
toolbar masquée + zoom par défaut sur les 3 derniers mois + sélecteur de
période en une ligne défilante. Validé sur écran ~375-414px **avec 2
indicateurs dans la topbar** ; depuis l'ajout de la liquidité disponible (3
indicateurs), la topbar mobile n'est plus forcée en `nowrap` et peut passer
sur 2 lignes. Depuis validé visuellement (serveur local + Playwright,
prompts 12/13/16) : rendu correct.

**Zoom/pan par glisser désactivé sur tous les graphiques Plotly (desktop ET
mobile)**, `dragmode=False` dans `theme.plotly_layout` + `scrollZoom: False`
dans `theme.PLOTLY_CONFIG` (avant prompt 18 : seul le graphique Trading avait
`scrollZoom` désactivé, en config ad hoc à son appel ; le graphique
Portefeuille avait lui son zoom/pan/double-clic totalement neutralisés sur
mobile uniquement via une règle CSS `pointer-events: none` sur `.nsewdrag`,
la couche Plotly qui capte ces interactions — un blocage large qui cassait
aussi le double-clic de réinitialisation du zoom, alors qu'il devait rester
utilisable). Le sélecteur de période reste le seul moyen normal de changer
l'échelle affichée. Double-clic (reset du zoom) conservé partout, y compris
mobile désormais : indépendant de `dragmode` côté Plotly.js, c'est justement
ce qui permet de couper le premier sans le second — impossible à faire
sélectivement en CSS pur (`pointer-events` est tout ou rien sur un même
élément), d'où le passage par la config Python (uniforme desktop/mobile,
Streamlit ne permettant pas de config Plotly différente par largeur d'écran
côté serveur). Effet de bord assumé sur desktop : le clic-glisser direct
pour dessiner un rectangle de zoom (dragmode par défaut de Plotly) ne
fonctionne plus tel quel ; la modebar (visible desktop uniquement, boutons
Zoom/Pan/Reset) reste le chemin normal pour ça, cohérent avec le sélecteur
de période déjà présenté comme le moyen principal de changer l'échelle.
Vérifié par `AppTest` (rendu sans exception) ; le comportement visuel réel
du double-clic sur un vrai écran tactile reste à confirmer manuellement par
Edgar, faute d'outil de navigateur mobile disponible dans cette session.

**Listes compactes mobile** (`theme.render_compact_list`) : Positions,
Historique des trades, récap "Positions ouvertes" (Portefeuille), recherche
d'actifs/récents/suggestions et encadrés d'accueil Trading (Indices
majeurs, Top capitalisation...) basculent tous en 1 ligne HTML compacte
par élément sur mobile plutôt qu'en grosse carte empilée (rendu desktop
`render_table_light` masqué en contrepartie, voir le media query dans
`theme.py`). **Toujours passer `detail=` avec un `st.button` de navigation
(`theme.go_to_trading`)** à chaque appel de `render_compact_list` — sans
lui, la ligne compacte n'a strictement aucune interaction possible sur
mobile (bug réel vécu au prompt 12, corrigé au prompt 13 : impossible
d'ouvrir un actif depuis ces listes sur petit écran, plusieurs mois avant
qu'un vrai écran mobile ne le révèle si non testé explicitement).

**Panneau latéral natif Streamlit** : replié par défaut au chargement,
desktop compris (`st.set_page_config(..., initial_sidebar_state="collapsed")`,
`app.py`) — la navigation de l'app passe par sa propre barre d'onglets, pas
par ce panneau, qui n'a donc plus besoin de s'ouvrir en grand par défaut.
Reste entièrement dépliable/repliable via ses icônes natives (jamais
masquées côté CSS) : "Se déconnecter" et le sélecteur de portefeuille n'ont
pas d'autre point d'accès dans l'app, à un clic près derrière l'icône `»`.
**Piège déjà tombé dedans une fois** (régression du prompt 12, corrigée au
prompt 16) : masquer l'icône de repli INTERNE au panneau (au lieu de
forcer l'état initial replié) le laisse coincé ouvert dès qu'il s'ouvre,
sans aucun moyen de le refermer — ne jamais masquer
`stSidebarCollapseButton`/`stExpandSidebarButton` en CSS, seul
`initial_sidebar_state` doit piloter l'état par défaut.

Page Connexion/Inscription centrée (horizontalement de façon robuste,
verticalement de façon approximative — `st.container(key="ts_login_page")`
dans `ui_auth.py` + CSS dans `theme.py`) plutôt que collée en haut à
gauche. Bandeau de valeur (topbar) en fond transparent (se fond dans le
dégradé) plutôt que le fond plus sombre résiduel du thème clair d'origine.
Barre de recherche (Trading) avec fond/contour propres pour se détacher de
la page. Titre (nom + ticker) affiché en haut de la fiche d'un actif
consulté. Résumés hebdomadaires automatiques (News) ouvrables en modal
comme un article normal (le bouton dépendait d'un seuil de troncature à
280 caractères que ces résumés courts n'atteignaient presque jamais).

### Comptes et rôles (3 niveaux)
- **Admin** (moi) : tous les droits — gestion des comptes, seul à pouvoir
  supprimer un cours ou une news (y compris ceux d'un Contributeur).
- **Contributeur** : peut publier des news librement (sans validation),
  ne peut en supprimer aucune. Mêmes droits que Standard partout ailleurs.
  Promotion depuis l'Admin, pas de rétrogradation possible depuis l'UI.
- **Standard** : rôle par défaut à l'inscription. Portefeuille et trading
  isolés, peut ajouter/modifier ses propres cours mais pas les supprimer,
  lecture seule sur News.
Authentification par mot de passe haché (bcrypt). Un compte désactivé par
l'Admin est bloqué immédiatement, sans perte de données.

## Base de données
Connexion via Session Pooler IMPÉRATIVEMENT
(`aws-0-eu-west-2.pooler.supabase.com`), JAMAIS le format "Direct
connection" (`db.xxx.supabase.co`) qui échoue sur Streamlit Cloud.
Isolation stricte des données par `user_id` sur chaque requête.

Logique de connexion scindée en deux : `src/db_core.py` (aucune dépendance à
Streamlit — lecture de `DATABASE_URL` uniquement via variable
d'environnement, migrations de schéma via `db_core.ensure_schema`) utilisé
par les scripts indépendants de l'app (sauvegarde/restauration/TP-SL,
exécutés par GitHub Actions ou en local) ; `src/db.py` (dépend de
Streamlit) ajoute par-dessus le repli sur `st.secrets` et la mise en cache
par processus serveur, pour l'app elle-même. Ne jamais réintroduire un
`import streamlit` dans un module utilisé par `scripts/backup_db.py`,
`scripts/restore_db.py`, `scripts/check_tp_sl.py` ou
`scripts/check_liquidation.py` — c'est exactement ce qui a fait échouer le
workflow de sauvegarde une première fois (`ModuleNotFoundError: streamlit`,
l'environnement GitHub Actions n'installant volontairement pas Streamlit) ;
même logique pour `src/portfolio_repo.py` (chargement/sauvegarde d'UN
portefeuille par `portfolio_id`, sans dépendance à Streamlit, réutilisé par
`storage.py`, `scripts/check_tp_sl.py` ET `scripts/check_liquidation.py`) et
pour `src/valuation.py` (formules de P&L/marge/liquidation, réutilisées par
`scripts/check_liquidation.py` sans jamais y importer Streamlit).

Deux workflows GitHub Actions tournent sur ce même modèle (`db_core`,
secret `DATABASE_URL` du dépôt, aucune dépendance à Streamlit) : sauvegarde
quotidienne (`backup.yml`) et vérification TP/SL + liquidation toutes les 15
minutes (`check-tp-sl.yml`, deux steps séquentiels dans le même job — voir
"Liquidation automatique par marge de maintenance" ci-dessus pour l'ordre de
priorité entre les deux). Contrairement aux scripts de test habituels,
`scripts/check_tp_sl.py` et `scripts/check_liquidation.py` traitent
respectivement TOUS les paliers actifs et TOUTES les positions à levier de
TOUS les comptes à chaque exécution (c'est leur rôle) : les relancer
manuellement en local exécute donc pour de vrai n'importe quel palier ou
liquidation réel déclenché à ce moment-là, pas seulement ceux d'un compte de
test.

**Concurrence sur `portfolio_repo.save_portfolio`** : verrouille la ligne
`portfolios` (`session.get(PortfolioRow, portfolio.id, with_for_update=True)`)
pour toute la durée de la transaction, avant le DELETE-puis-INSERT complet
de positions/trades/pending_orders/value_history. Nécessaire car une
session utilisateur et le cron `check-tp-sl.yml` (toutes les 15 min sur
tous les portefeuilles à paliers/positions leviées actifs) peuvent
sauvegarder le MÊME portefeuille en même temps — sans ce verrou, repéré en
conditions réelles (stress test, prompt 11) : crash `IntegrityError` sur
la contrainte unique de `positions` (portfolio_id, ticker), le panneau
Trading restant inutilisable jusqu'à résolution spontanée. `positions` a
en plus un upsert `ON CONFLICT` explicite (même idiome que `value_history`,
qui avait déjà ce correctif avant `positions`) ; `trades`/`pending_orders`
n'ont pas de contrainte unique exploitable pour un upsert, d'où le besoin
du verrou (qui protège les 4 tables à la fois, pas seulement `positions`).
**Limite connue, non corrigée** : le verrou évite le crash mais pas la
perte silencieuse d'une modification si deux écritures concurrentes
touchent des éléments DIFFÉRENTS du même portefeuille (chacune remplace
tout l'état, pas seulement ses propres changements) — risque résiduel
accepté, hors périmètre de ce correctif (prompt 15).

**Sauvegarde automatique** : chaque nuit, un workflow GitHub Actions
(`.github/workflows/backup.yml`) exporte toutes les tables en CSV dans
`backups/AAAA-MM-JJ/` (rotation : 14 sauvegardes conservées), commité
directement dans le dépôt — gratuit, aucun service tiers. Voir
`backups/README.md` pour la mise en place du secret GitHub `DATABASE_URL`
(à faire une fois) et la marche à suivre pour restaurer
(`scripts/restore_db.py`) en cas de problème.

## Tâches en cours / pas encore faites
- Secret GitHub `DATABASE_URL` déjà configuré par Edgar (sauvegarde
  automatique nocturne) ; le workflow avait échoué une première fois
  (`ModuleNotFoundError: streamlit`, corrigé en isolant `src/db_core.py` de
  Streamlit) — à confirmer que le prochain run passe au vert dans l'onglet
  Actions du dépôt GitHub.
- Désigner le portefeuille officiel de testutilisateur/oscar/edgarv2 depuis
  l'Admin (voir "Portefeuille officiel" ci-dessus) — sinon ils restent
  absents du Classement.
- Cookie de session persistant : mis de côté pour l'instant, pas urgent.
- Pas de garde-fou explicite anti-double-soumission sur les ordres (achat/
  vente) : aucun bug observé en pratique (protégé de fait par le modèle
  mono-thread de Streamlit), mais signalé comme point fragile à surveiller
  si l'app évolue vers plus d'asynchrone. Volontairement laissé de côté.
- Bug mineur non résolu, à confirmer en usage réel avant de le traiter :
  revisiter l'onglet Trading juste après avoir quitté la fiche d'un actif
  (bouton "Retour à l'accueil") peut occasionnellement rester bloqué
  plusieurs dizaines de secondes — probablement lié au fragment
  d'auto-rafraîchissement (`run_every=30`) de cette fiche qui continue de
  tourner en arrière-plan après en être sorti — pas confirmé, à garder en
  tête en le retraitant. La 2ème cause suspectée initialement (le
  formulaire d'ordre, hors fragment, forçant un rerun complet à chaque
  interaction) a été corrigée au prompt 17 (voir diagnostic de lenteur
  ci-dessous) ; si ce bug persiste malgré ça, il est donc isolé au
  fragment du graphique.
- **Diagnostic de lenteur (prompt 14) fait, 2 corrections sur 2 appliquées** :
  2 causes identifiées pour la lenteur signalée au changement d'onglet et
  sur le formulaire d'ordre. (1) `_render_order_form` (`ui_trading.py`)
  n'était pas isolé dans son propre `@st.fragment`, contrairement au
  graphique — chaque interaction du formulaire (levier, montant...)
  reconstruisait et réenvoyait la figure Plotly pour rien. **Corrigé au
  prompt 17** : `_render_order_form` + `_render_tp_sl_section` vivent
  maintenant dans leur propre `@st.fragment` (`_render_order_panel`),
  séparé de celui du graphique (`_render_price_and_chart`) — une
  interaction sur le formulaire ne reconstruit plus la figure Plotly.
  `st.rerun(scope="app")` explicite uniquement aux 2 points de validation
  réussie d'un ordre (marché et cours limité) dans `_render_order_form`,
  pour que la topbar (valeur totale/liquidité/P&L jour) se rafraîchisse
  bien malgré l'isolation du fragment — les reruns internes au fragment
  (paliers TP/SL créés/annulés, ordres en attente annulés) restent volontairement
  scopés au fragment seul, ces actions ne changeant pas la topbar. Vérifié
  par `streamlit.testing.v1.AppTest` (changement de levier/montant/mode
  seuls, validation d'ordre, création de palier TP/SL — aucune exception) ;
  la mesure de l'amélioration réelle (absence de reconstruction visible du
  graphique) nécessite un test manuel dans un navigateur, non exécuté ici
  faute d'outil de navigation disponible dans cette session — à confirmer
  par Edgar en local à l'occasion. (2) `valuation.total_value(portfolio)`
  tournait sans condition à CHAQUE rerun (app.py, avant le routage
  d'onglet), y compris vers un onglet qui n'en a pas besoin (Tutoriel,
  Règlement...). **Corrigé au prompt 18** : cache manuel en
  `session_state` + timestamp (`storage.get_cached_total_value`, TTL 5s —
  `st.cache_data` écarté, `Portfolio` étant un objet mutable non hashable
  nativement), clé par `portfolio.id` (changer de portefeuille actif
  invalide naturellement le cache). Vit dans `storage.py` (pas `app.py` ni
  `valuation.py`) pour rester testable isolément et parce que
  `storage.py` dépend déjà de Streamlit, contrairement à `valuation.py`
  qui doit rester réutilisable par `scripts/check_liquidation.py` sans
  cette dépendance. Invalidation explicite (`storage.invalidate_valuation_cache`)
  à chaque endroit qui change la valeur du portefeuille actif pendant la
  session : les 2 points de validation d'ordre dans `_render_order_form`
  (déjà à côté du `storage.save_portfolio()` du prompt 17), l'exécution
  automatique d'un ordre à cours limité (`app.py`, `order_engine.process_pending_orders`)
  et la réinitialisation d'un portefeuille (`ui_portfolio.py`) — jamais après
  la simple pose/annulation d'un ordre à cours limité, qui ne touche ni le
  cash ni les positions avant son exécution réelle (`Portfolio.place_limit_order`).
  Vérifié par `AppTest` (cache chaud sur plusieurs reruns successifs = 1
  seul appel réel à `valuation.total_value`, fraîcheur immédiate après
  invalidation, cache manqué au changement de portefeuille actif). Correction
  triviale déjà appliquée en marge (`search_history.get_recent`, cache 10s
  — tournait aussi sans condition à chaque rerun de la page Trading).
- Audit de charge (stress test) fait sur l'app déployée : isolation
  multi-comptes, cohérence Supabase (pas de ligne orpheline), portefeuille
  officiel, cache API sous charge légère (5 comptes) — tout validé. Pas
  testé : comportement exact si un vrai rate-limit Yahoo/Kraken est atteint
  (jamais déclenché pendant l'audit), ni un ordre à la limite exacte du
  solde disponible (couverture partielle).

## Règles impératives à ne jamais oublier
- Toujours vérifier le format Session Pooler (pas Direct connection)
  quand on régénère un mot de passe Supabase
- Ne JAMAIS réafficher un mot de passe/chaîne de connexion en clair dans
  tes réponses
- Python 3.11 ou 3.12 sur Streamlit Cloud (éviter 3.14, incompatibilités
  connues avec psycopg2/Starlette)
- Une fois une tâche terminée et testée, commit et push toi-même
  (git add -A / git commit -m "..." / git push) plutôt que de me demander
  de le faire manuellement
- Après un push, si l'app déployée affiche une erreur (ex: ImportError sur
  un nom qui existe pourtant dans le fichier poussé sur GitHub), c'est
  généralement un déploiement resté sur une version en cache côté
  Streamlit Cloud, pas une vraie erreur de code : rebooter l'app suffit
  (share.streamlit.io -> l'app -> menu ⋮ -> "Reboot app"), pas besoin de
  chercher un bug ailleurs en premier réflexe.
- Toute modification de schéma Supabase (nouvelle colonne...) doit être
  migrée explicitement dans `src/db.py::init_db()` (ex: `ALTER TABLE ...
  ADD COLUMN IF NOT EXISTS`) — `create_all()` ne touche jamais une table
  déjà existante.
- Avant de tester une fonctionnalité multi-comptes, créer des comptes
  jetables directement via `auth.create_user(...)` (script Python, pas
  l'UI d'inscription) puis les supprimer via `auth.delete_user(...)` une
  fois fini — jamais tester sur les comptes réels d'Edgar/participants
  sans le dire explicitement.
- Le Session Pooler Supabase limite à **15 connexions simultanées**
  (`EMAXCONNSESSION`). Un enchaînement de scripts de test/serveur local qui
  ouvrent chacun leur propre `create_engine_from_env()` sans le disposer
  peut épuiser ce quota (vécu plusieurs fois lors de sessions de test
  intensives) — l'erreur se résout seule après quelques secondes/dizaines
  de secondes (connexions recyclées), pas la peine de chercher un bug
  ailleurs si ce message précis apparaît pendant une série de tests.