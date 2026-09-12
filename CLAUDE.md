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

### Onglet Cours
Ajout manuel de fiches de révision (pas d'automatisation via API pour
l'instant — décision volontaire), organisées par thème, recherche possible.

### Onglet Classement
Classement multi-utilisateurs trié par P&L en €, avec le P&L en % affiché
à côté. Ne prend en compte que le **portefeuille officiel** de chaque
utilisateur (voir Portefeuille officiel ci-dessus) — recalculé en temps
réel à chaque consultation, pour tout le monde. Ma propre ligne est repérée
par un "(toi)". Visible par tous les comptes connectés.

### Onglet News
Fil d'articles (titre, contenu, lien, image de couverture). Admin et
Contributeur peuvent publier librement (sans validation) ; suppression
réservée à l'Admin (y compris les news d'un Contributeur) ; lecture seule
pour un compte standard.

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

## Tâches en cours / pas encore faites
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