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
Actions + crypto + indices/ETF (couverture US/Europe/Asie), positions
longues et courtes (short), effet de levier, ordres au marché et à cours
limité. Graphiques avec sélecteur d'échelle temporelle progressif
(1J/1S/1M/3M/6M/YTD/1A/5A/Tout), granularité maximale à chaque échelle.
Tickers cliquables depuis le Portefeuille pour rejoindre directement la
fiche Trading de l'actif.
Le prix affiché et son graphique se rafraîchissent automatiquement toutes
les 30 secondes via `@st.fragment(run_every=30)`, isolé du reste de la
page. Le formulaire d'ordre (hors fragment) lit le prix via
`st.session_state` sans dupliquer d'appel API.

**Saisie par montant à risquer (crypto uniquement)** : pour ouvrir/renforcer
une position sur une **crypto** (achat, short), l'utilisateur saisit un
**montant en euros** (sa marge, plafonnée à son cash disponible) plutôt
qu'une quantité brute — la taille de position s'en déduit (`montant ×
levier`, converti en quantité fractionnée au prix de référence choisi,
marché ou cours limité). Pour une **action/ETF/indice** (tout ce qui n'est
pas identifié comme crypto par `ui_trading._is_crypto`, la même détection
déjà utilisée pour choisir la source du graphique Kraken vs Yahoo), le champ
reste une **quantité entière de titres** classique (comportement
historique) : une action ne se fractionne pas dans la réalité, contrairement
à une crypto. Pour **clôturer** une position (Vendre, Racheter), la saisie
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
Thème clair partout (plus de thème sombre — la démarcation entre un onglet
clair et le reste en sombre était trop dérangeante) : fond quasi-blanc,
police monospace pour tous les chiffres, bleu discret pour les éléments
interactifs (boutons, liens, onglet actif), vert/rouge réservés aux
gains/pertes. Palette pilotée par les constantes de `src/theme.py`
(BG/PANEL/BORDER/TEXT/MUTED/GREEN/RED/ACCENT) et par `.streamlit/config.toml`
(`[theme]`, nécessaire en plus du CSS injecté pour que les composants
internes de Streamlit/BaseWeb — menus déroulants, popovers — suivent aussi
le thème clair).

**Responsive mobile** : passe faite (media queries `@media max-width:640px`
dans `src/theme.py`) — échelle de police/paddings réduite globalement,
tableaux en cartes empilées sur petit écran, graphiques Trading avec
toolbar masquée + zoom par défaut sur les 3 derniers mois + sélecteur de
période en une ligne défilante. Validé sur écran ~375-414px.

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
  tourner en arrière-plan après en être sorti.
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