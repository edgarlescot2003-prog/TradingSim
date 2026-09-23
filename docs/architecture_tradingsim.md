# Architecture technique de TradingSim

## A qui s'adresse ce document

Ce document explique le fonctionnement de TradingSim a une personne qui connait
les bases de Python, mais qui ne connait pas encore bien Streamlit, SQLAlchemy,
Supabase, yfinance ou GitHub Actions.

L'objectif n'est pas seulement de lister les fichiers. Il s'agit de comprendre
qui prend les decisions, ou les donnees vivent, et comment une action utilisateur
traverse le systeme.

---

## 1. Vue d'ensemble

TradingSim est un simulateur de trading fictif : chaque utilisateur possede un
ou plusieurs portefeuilles, consulte des actifs de marche, passe des ordres et
voit ses gains ou pertes. L'application est une interface Streamlit en Python,
la logique financiere est implementee dans des modules Python purs, et l'etat
persistant est stocke dans une base PostgreSQL fournie par Supabase.

Les prix viennent principalement de Yahoo Finance via `yfinance`; certains
historiques crypto utilisent aussi Kraken. Des workflows GitHub Actions executent
les controles qui doivent continuer meme lorsque personne n'a ouvert l'application,
notamment les TP/SL, les liquidations et les snapshots de la page Admin News.

Schema general :

```text
Utilisateur
    |
    v
Streamlit (app.py)
    |-- authentification et navigation
    |-- pages ui_*.py
    |-- logique metier : portfolio.py, valuation.py, order_engine.py
    |
    v
SQLAlchemy + psycopg
    |
    v
Supabase PostgreSQL
    |-- utilisateurs et portefeuilles
    |-- positions, trades, ordres
    |-- snapshots de valeur et de prix

GitHub Actions (taches planifiees)
    |-- lit Supabase
    |-- appelle les APIs de marche quand necessaire
    |-- execute TP/SL, liquidations, snapshots
    |-- ecrit les resultats dans Supabase
```

Une idee importante : Streamlit n'est pas un serveur classique qui attend des
requete HTTP une par une. Une interaction provoque generalement un rerun du
script `app.py`. Le code doit donc etre organise pour que chaque rerun soit
correct, rapide et idempotent.

---

## 2. Stack technique

### Python

Python est le langage de toute l'application : interface, calcul financier,
connexion a la base, scripts et tests.

Exemple : `Portfolio.buy()` dans `src/portfolio.py` verifie la quantite, le
levier et le cash, puis cree ou augmente une position.

### Streamlit

Streamlit transforme un script Python en interface web. Les widgets sont des
appels Python : `st.button`, `st.selectbox`, `st.number_input`, `st.dataframe`,
etc.

Dans `app.py`, le script initialise la page, verifie la session d'authentification,
charge le portefeuille actif, puis rend l'onglet courant :

```python
if st.session_state.active_tab == "trading":
    ui_trading.render(portfolio)
elif st.session_state.active_tab == "classement":
    ui_leaderboard.render(user_id)
```

Streamlit utilise `st.session_state` pour conserver des informations entre deux
reruns : utilisateur connecte, onglet courant, portefeuille actif et caches de
session.

Les fragments Streamlit (`@st.fragment`) isolent certains rafraichissements,
par exemple le graphique de prix ou le formulaire d'ordre. Cela evite de
reconstruire toute la page pour chaque petite interaction.

### Supabase / PostgreSQL

Supabase fournit la base PostgreSQL distante et son infrastructure. Dans ce
projet, Supabase est utilise comme base de donnees, pas comme systeme
d'authentification : l'authentification est geree par les tables et fonctions
Python du projet.

La connexion utilise obligatoirement le Session Pooler Supabase. L'URL n'est
jamais ecrite dans le code :

- localement : variable `DATABASE_URL` dans `.env` ;
- Streamlit Cloud : secret Streamlit ;
- GitHub Actions : secret GitHub `DATABASE_URL`.

### SQLAlchemy

SQLAlchemy est l'ORM et la couche SQL. Les classes Python de `src/db_models.py`
representent les tables PostgreSQL.

Exemple :

```python
select(PortfolioRow).where(PortfolioRow.user_id == user_id)
```

Cette requete charge les portefeuilles d'un utilisateur sans construire une
chaine SQL manuellement.

### psycopg

`psycopg[binary]` est le pilote PostgreSQL utilise par SQLAlchemy pour parler
concretement a Supabase.

La chaine de connexion est normalisee dans `src/db_core.py`, qui force le
pilote `postgresql+psycopg` et `sslmode=require`.

### pandas

pandas sert surtout a manipuler les donnees tabulaires et les CSV de sauvegarde.

Exemples :

- `scripts/backup_db.py` exporte les tables en CSV avec `pd.read_sql_table` ;
- `scripts/restore_db.py` relit les CSV avec `pd.read_csv` ;
- des historiques de prix sont manipules sous forme de `DataFrame`.

pandas n'est pas le stockage principal de l'application : la base Supabase reste
la source durable.

### yfinance

`yfinance` fournit les prix Yahoo Finance pour les actions, indices, ETF,
forex, matieres premieres et une partie des crypto-actifs.

Dans `src/market_data.py` :

```python
info = yf.Ticker(ticker).fast_info
price = info.get("last_price")
```

Le module centralise les appels dans `get_quote`, `get_history` et
`get_history_with_fallback`. Le cache de prix courant dure 20 secondes et le
cache de taux de change dure 5 minutes.

### requests et Kraken

`requests` est utilise pour les appels HTTP directs necessaires a l'API
publique Kraken. `src/kraken_data.py` sert surtout aux historiques intrajournaliers
crypto pour les graphiques.

Kraken n'est pas utilise pour le carnet d'ordres : le carnet affiche dans Trading
est une simulation visuelle locale dans `src/orderbook_sim.py`.

### Plotly

Plotly dessine les graphiques interactifs : prix, courbes de portefeuille,
marqueurs de trades et comparaison de performance.

Une figure Plotly est construite cote Python, puis envoyee a Streamlit. Les
options de zoom, modebar et plein ecran sont configurees dans `src/theme.py`
et `src/ui_trading.py`.

### bcrypt

bcrypt ne stocke jamais le mot de passe en clair. Lors de l'inscription,
`auth.hash_password()` produit un hash. Lors de la connexion,
`auth.verify_password()` compare le mot de passe saisi au hash.

Un mot de passe oublie ne peut pas etre relu : il faut le remplacer par un
nouveau mot de passe, comme le fait `scripts/reset_password.py`.

### starlette

Starlette est une dependance de Streamlit. Elle est explicitement verrouillee
dans `requirements.txt` parce qu'une version plus recente posait un probleme
avec le middleware gzip de Streamlit.

### pytest / scripts de test

Les tests actuels sont des scripts Python autonomes dans `tests/`.

- `test_orderbook_sim.py` teste la logique pure du carnet simule ;
- `test_orderbook_no_network.py` utilise des fonctions pieges pour verifier que
  le rendu du carnet ne declenche aucun appel reseau ;
- `test_diversification.py` teste des comportements de donnees de marche et de
  categorisation.

---

## 3. Architecture des donnees

### Principe general

Chaque table metier porte autant que possible un `user_id`. Cela simplifie le
scoping : une requete de portefeuille est toujours rattachee a l'utilisateur
connecte et ne doit jamais pouvoir lire les donnees d'un autre compte.

Les identifiants principaux sont des UUID. Les dates sont stockees comme chaines
ISO 8601, par exemple `2026-09-23T18:42:00+00:00`. Ce choix reste compatible
avec les anciennes dataclasses et les scripts independants.

### Relations principales

```text
users
  |
  | 1 -> plusieurs
  v
portfolios
  |
  | 1 -> plusieurs
  +--> positions
  +--> trades
  +--> pending_orders
  +--> tp_sl_orders
  +--> value_history
  +--> portfolio_value_snapshots

users + actifs
  |
  v
market_price_snapshots
```

Un utilisateur peut avoir jusqu'a plusieurs portefeuilles. Un seul peut etre
marque `is_official=True`; c'est celui qui compte dans le classement.

### Table `users`

Contient les comptes :

- `id` : UUID du compte ;
- `username` : identifiant de connexion unique ;
- `password_hash` : hash bcrypt ;
- `role` : `admin`, `contributor` ou `standard` ;
- `is_active` : blocage ou activation du compte ;
- `created_at` : date de creation ;
- `active_portfolio_id` : portefeuille selectionne a la derniere visite.

### Table `portfolios`

Contient l'etat principal de chaque portefeuille :

- `user_id` : proprietaire ;
- `name` : nom affiche ;
- `initial_capital` : capital de depart ;
- `cash` : liquidite actuellement disponible ;
- `is_official` : inclusion dans le classement ;
- `created_at` : date de creation.

Les positions, trades et ordres ne sont pas stockes dans un champ JSON du
portefeuille. Ils sont dans des tables filles reliees par `portfolio_id`.

### Table `positions`

Une ligne represente une position actuellement ouverte sur un ticker :

- quantite ;
- prix moyen ;
- devise ;
- sens `long` ou `short` ;
- marge engagee ;
- date d'entree.

Une position totalement fermee est supprimee de cette table, mais ses trades
restent dans `trades`.

### Table `trades`

Chaque operation executee est conservee : achat, vente, ouverture short ou
rachat short.

Les champs importants sont :

- `date` ;
- `ticker`, `quantity`, `price_eur` ;
- `leverage` ;
- `realized_pnl_eur` pour le P&L realise lors d'une cloture ;
- `tp_sl_order_id` si le trade vient d'un palier automatique ;
- `is_liquidation` pour une liquidation de maintenance.

Cette table est l'historique des actions. Elle est differente de `positions`,
qui represente seulement l'etat actuel.

### Table `pending_orders`

Contient les ordres a cours limite non encore executes. Ils sont examines par
`order_engine.py` depuis leur champ `last_checked_at`.

### Table `tp_sl_orders`

Contient les paliers Take Profit et Stop Loss : prix cible, sens, type, quantite
initiale, quantite figee au declenchement, statut et dates d'execution.

Les paliers sont verifies par le workflow GitHub Actions, meme si l'utilisateur
n'a pas l'application ouverte.

### Table `value_history`

Contient les points de courbe de valeur enregistres par l'application, avec :

- portefeuille ;
- utilisateur ;
- date ;
- valeur totale en euros.

Cette table sert aux graphiques de performance et aux metriques d'historique.
Elle est mise a jour quand l'application consulte et valorise le portefeuille.

### Tables de la page Admin News

`market_price_snapshots` stocke les prix en euros collectes periodiquement :

- ticker ;
- nom ;
- categorie ;
- date de collecte ;
- prix en euros.

`portfolio_value_snapshots` stocke une photo periodique de la valeur des
portefeuilles officiels. La page Admin News peut ainsi calculer les progressions
24 h et 7 jours sans appeler Yahoo Finance lors de l'affichage.

Ces tables sont alimentees par `scripts/record_admin_snapshots.py`, ajoute au
workflow TP/SL existant.

### Tables de contenu

- `courses` : fiches de revision ;
- `news` : articles visibles dans l'onglet News ;
- `search_history` : derniers actifs recherches par utilisateur.

Les cours et news sont du contenu partage. La suppression d'un auteur detache
le contenu (`user_id=NULL`) au lieu de supprimer automatiquement l'article.

---

## 4. APIs externes

### Yahoo Finance via yfinance

Yahoo Finance est utilise pour :

- prix courants ;
- prix de cloture precedente ;
- historiques OHLC pour les graphiques ;
- historiques utilises pour verifier les ordres limites ;
- taux de change pour convertir en euros ;
- quelques informations de categorisation et de profil.

Le module `src/market_data.py` est le point central. Les autres modules ne
devraient pas appeler yfinance directement.

La frequence depend du contexte :

- fiche Trading : rafraichissement du prix environ toutes les 30 secondes ;
- formulaire et revalorisation : cache de prix de 20 secondes ;
- ordres limites en attente : controle au maximum toutes les 15 secondes dans
  l'application, plus le workflow automatique selon le besoin ;
- TP/SL et liquidations : workflow toutes les 15 minutes ;
- snapshots Admin News : workflow toutes les 15 minutes.

### Kraken

Kraken fournit des historiques crypto lorsque le code demande des donnees
intrajournalieres adaptees aux graphiques. Ce n'est pas une source de streaming
continu et ce n'est pas un vrai carnet d'ordres dans l'application.

### Regle de limitation des appels

La page Admin News ne contacte aucune API externe. Elle lit uniquement les
snapshots deja en base. Cette separation est essentielle : ouvrir la page Admin
ne doit pas declencher une rafale d'appels yfinance pour tous les actifs et tous
les participants.

---

## 5. Flux principal : passer un ordre au marche

Voici le chemin conceptuel d'un ordre Long au marche.

### Etape 1 : affichage

`app.py` charge le portefeuille actif depuis `storage.load_all()`. La page
`ui_trading.py` affiche l'actif et le formulaire d'ordre.

Le prix affiche dans le formulaire vient d'un fragment de prix et est depose
dans `st.session_state` pour eviter que chaque changement de champ ne reconstruise
le graphique ou ne rappelle inutilement l'API.

### Etape 2 : validation de l'interface

L'utilisateur choisit :

- Long ou Short ;
- marche ou limite ;
- quantite ou montant a risquer selon la categorie ;
- levier ;
- eventuellement TP/SL.

`ui_trading.py` transforme le choix d'interface en action canonique :
`achat`, `vente`, `ouverture short` ou `rachat short`.

### Etape 3 : regles financieres

Pour un Long, le formulaire appelle `portfolio.buy(...)`.

`Portfolio.buy()` :

1. refuse une quantite ou un levier invalides ;
2. refuse l'ouverture opposee a une position Short existante ;
3. calcule la marge `quantite * prix / levier` ;
4. verifie le cash disponible ;
5. cree ou augmente `Position` ;
6. diminue le cash ;
7. ajoute un objet `Trade` a l'historique.

Le levier ne supprime pas le risque : il diminue le cash immobilise, mais amplifie
le P&L par rapport a la marge.

### Etape 4 : persistance

`storage.save_portfolio(portfolio)` transmet l'utilisateur courant a
`portfolio_repo.save_portfolio()`.

La sauvegarde :

- verrouille la ligne du portefeuille avec `SELECT ... FOR UPDATE` ;
- met a jour le cash et les metadonnees ;
- remplace les lignes de positions, trades, ordres et historique lies a ce
  portefeuille ;
- committe la transaction.

Le verrou est important car un utilisateur et un workflow automatique peuvent
modifier le meme portefeuille en meme temps.

### Etape 5 : recalcul de l'interface

L'application invalide le cache de valorisation, relance un rerun Streamlit,
recalcule la valeur totale, le P&L et la topbar, puis affiche le portefeuille
mis a jour.

### Flux d'un ordre limite

Un ordre limite n'est pas execute immediatement. Il est stocke dans
`pending_orders` avec un prix cible. `order_engine.process_pending_orders()`
recupere l'historique depuis `last_checked_at`, cherche si le Haut ou le Bas
d'une bougie a franchi le seuil, puis appelle `Portfolio.buy`, `sell`,
`open_short` ou `cover_short`.

---

## 6. Hebergement et deploiement

### Developpement local

En local, on peut lancer l'application depuis la racine du projet :

```powershell
streamlit run app.py
```

Le fichier `.env` local contient la connexion `DATABASE_URL`. Il ne doit jamais
etre committe.

### Streamlit Community Cloud

L'application est hebergee sur Streamlit Community Cloud. Le depot GitHub est
la source du code deploye.

Le fonctionnement typique est :

```text
git add ...
git commit -m "..."
git push origin main
        |
        v
Streamlit Cloud detecte le nouveau commit
        |
        v
Installation de requirements.txt
        |
        v
Redemarrage de l'application
```

Les secrets de la base sont configures dans les secrets Streamlit Cloud, pas
dans GitHub ni dans le code Python.

Apres un push, une application Streamlit Cloud peut parfois rester sur un
ancien processus ou une version en cache. Un **Reboot app** depuis le menu de
Streamlit Cloud force le redemarrage.

### GitHub Actions

Les workflows ne servent pas a deployer l'interface. Ils executent des taches
planifiees cote serveur :

- `backup.yml` : sauvegarde quotidienne de toutes les tables dans `backups/`
  et commit automatique dans GitHub ;
- `check-tp-sl.yml` : toutes les 15 minutes, verification TP/SL, liquidations,
  puis snapshots Admin News.

Les workflows installent volontairement un sous-ensemble des dependances. Ils
n'importent pas Streamlit, car les scripts doivent pouvoir fonctionner dans un
environnement Python minimal.

---

## 7. Points techniques les plus complexes

### Le modele de marge et du levier

Le projet ne simule pas un achat comptant simpliste. A l'ouverture, seul le
notionnel divise par le levier est retire du cash. Le P&L, lui, est calcule sur
la quantite totale.

Cela impose de distinguer :

- notionnel ;
- marge ;
- exposition ;
- contribution a l'equity ;
- P&L latent ;
- P&L realise.

Ces formules sont centralisees dans `portfolio.py` et `valuation.py` pour
limiter les divergences entre Trading, Portefeuille, Classement et liquidations.

### Les positions Long et Short

Une position Short n'est pas une position Long avec un signe visuel inverse.
Les formules de P&L, la liquidation, les actions de cloture et les conditions
TP/SL sont differentes. Le moteur interdit aussi Long et Short simultanes sur
le meme ticker dans un portefeuille.

### Les taches hors ligne de l'application

Streamlit n'est pas un scheduler. Si personne n'ouvre l'application, un simple
code place dans `app.py` ne peut pas executer un TP/SL.

C'est pourquoi les workflows GitHub Actions appellent des scripts autonomes
comme `scripts/check_tp_sl.py` et `scripts/check_liquidation.py`. Ces scripts
n'importent pas Streamlit et utilisent `db_core.py`, `portfolio_repo.py` et les
modules metier partages.

### La concurrence Supabase

La sauvegarde d'un portefeuille est un remplacement complet des lignes filles.
Deux sauvegardes simultanees peuvent donc se marcher dessus. Le verrou de ligne
avec `with_for_update=True` serialise les sauvegardes du meme portefeuille et
protege les positions, trades, ordres et snapshots pendant la transaction.

Cela evite les erreurs d'unicite et les suppressions entrelacees, mais ne
resout pas completement le cas de deux modifications differentes concurrentes :
la derniere sauvegarde peut encore ecraser un changement de la premiere.

### La limitation des APIs de marche

Les APIs gratuites peuvent limiter les requetes. Le projet utilise donc :

- un module central `market_data.py` ;
- des caches courts ;
- des appels paralleles limites a quelques workers ;
- des appels isoles des pages quand c'est possible ;
- des snapshots en base pour la page Admin News ;
- aucun appel reseau dans le carnet d'ordres simule.

Le compromis est accepte : certaines informations peuvent etre legerement
anciennes, mais l'application evite une rafale dangereuse de requetes.

### Les reruns Streamlit et la performance

Un widget Streamlit peut relancer `app.py` entierement. Les graphiques et appels
API couteux doivent donc etre places dans des fragments ou caches. Le cache de
valorisation dans `storage.py` est invalide explicitement apres un ordre ou un
reset, au lieu de recalculer tout a chaque interaction de formulaire.

### Les snapshots Admin News

Les progressions 24 h et 7 jours ne peuvent pas etre calculees proprement avec
un seul prix courant. La page Admin News repose donc sur deux historiques :

1. prix des actifs collectes periodiquement ;
2. valeurs des portefeuilles officiels collectees periodiquement.

Le workflow existant les alimente toutes les 15 minutes. La page lit ensuite
ces tables sans API externe.

### Les migrations de schema

`Base.metadata.create_all()` cree les tables manquantes, mais ne modifie pas
les tables deja existantes. Chaque nouvelle colonne importante doit donc aussi
etre ajoutee dans `db_core.ensure_schema()` avec une migration idempotente.

C'est un point essentiel lors d'un deploiement sur une base Supabase deja
existante.

---

## 8. Organisation du code

```text
app.py                    point d'entree et orchestration Streamlit
src/
  auth.py                 comptes, roles, hash bcrypt
  db.py                   connexion DB avec support Streamlit/secrets
  db_core.py              connexion DB independante de Streamlit, migrations
  db_models.py            modeles SQLAlchemy des tables
  storage.py              acces aux portefeuilles de l'utilisateur courant
  portfolio_repo.py       chargement/sauvegarde generique d'un portefeuille
  portfolio.py            moteur metier cash, positions et trades
  valuation.py            P&L, valeur, marge et liquidation
  order_engine.py         execution des ordres limites
  market_data.py          appels et caches Yahoo Finance
  kraken_data.py          historiques crypto Kraken
  admin_snapshot.py       collecte des snapshots Admin News
  admin_news.py           requetes sans reseau pour le dashboard Admin
  ui_*.py                 pages et composants Streamlit
  theme.py                CSS, palette et composants de rendu
scripts/
  check_tp_sl.py          execution automatique des TP/SL
  check_liquidation.py    liquidations automatiques
  record_admin_snapshots.py snapshots prix/portefeuilles
  backup_db.py            export CSV de la base
  restore_db.py           restauration complete, destructive
  restore_user.py         restauration ciblee d'un seul compte
  reset_password.py       changement de mot de passe par saisie masquee
tests/                    tests de logique et gardes reseau
.github/workflows/        taches planifiees GitHub Actions
```

Regle pratique : l'interface `ui_*.py` doit orchestrer et afficher; les calculs
financiers doivent rester dans les modules metier; les acces DB doivent passer
par les modules de persistance; les scripts GitHub Actions ne doivent pas
dependre de Streamlit.

---

## 9. Sauvegardes, restauration et securite

La sauvegarde quotidienne exporte les tables en CSV dans `backups/YYYY-MM-DD/`.
Elle permet une restauration complete, mais `restore_db.py` remplace toute la
base et est donc destructif.

Pour un compte supprime accidentellement, `restore_user.py` est plus adapte :
il restaure un seul utilisateur, ses portefeuilles, positions, trades, ordres,
TP/SL, snapshots de valeur et historique de recherche.

Les sauvegardes contiennent des hashes bcrypt. Elles ne contiennent pas les
mots de passe en clair. Un utilisateur qui oublie son mot de passe doit donc
passer par `scripts/reset_password.py`.

Les fichiers suivants ne doivent jamais etre committés :

- `.env` ;
- secrets Supabase ;
- mots de passe en clair ;
- captures ou archives locales contenant des donnees personnelles, sauf choix
  explicite.

---

## 10. Limites et pistes d'evolution

Quelques limites sont connues et importantes a comprendre :

- les snapshots historiques ne peuvent pas reconstituer le passe avant leur
  activation ;
- les taux de change historiques ne sont pas toujours stockes separement ;
- une concurrence complexe peut encore provoquer une perte logique de la
  derniere modification ;
- le classement historique depend de la qualite et de la frequence des
  snapshots ;
- les APIs gratuites peuvent renvoyer des erreurs ou des donnees retardees ;
- le carnet d'ordres est decoratif, pas une donnee de marche reelle ;
- les tests de navigateur restent utiles pour valider le rendu responsive
  Streamlit, car les tests Python ne voient pas tous les comportements CSS.

Les evolutions naturelles seraient :

1. ajouter des contraintes et verrous plus fins pour les mises a jour partielles ;
2. introduire une vraie migration de schema versionnee ;
3. ajouter des tests d'integration avec une base de test ;
4. ajouter des tests UI automatises desktop et mobile ;
5. separer eventuellement la collecte de marche dans un service dedie si le
   nombre d'utilisateurs augmente fortement.
