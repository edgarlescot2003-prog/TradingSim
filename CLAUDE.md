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
possibles, bouton reset optionnel, fiche de position complète (P&L €/%,
prix moyen d'achat, date d'entrée, poids %), graphique de performance dans
le temps, comparaison à un indice de référence (CAC40, S&P500...).

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
à côté. Un utilisateur avec plusieurs portefeuilles est classé sur la
somme de tous. Ma propre ligne est repérée par un "(toi)". Visible par
tous les comptes connectés (Admin ou Standard).
⚠️ À vérifier au démarrage de session : je suis en train de faire passer
le calcul de "dernière valeur connue à la connexion" à un recalcul en
temps réel pour tous les utilisateurs à chaque consultation — vérifie
l'état actuel du code avant de repartir dessus.

### Esthétique
Thème sombre inspiré d'Hyperliquid (terminal de trading pro) : fond
quasi-noir, police monospace pour tous les chiffres, vert/rouge pour
gains/pertes, densité forte, coins carrés.

### Comptes et rôles (2 niveaux)
- Admin (moi) : tous les droits, gestion des comptes, seul à pouvoir
  supprimer un cours ou écrire dans l'onglet News.
- Utilisateur standard : portefeuille et trading isolés, peut ajouter/
  modifier ses propres cours mais pas les supprimer, lecture seule sur
  News.
Authentification par mot de passe haché (bcrypt). Un compte désactivé par
l'Admin est bloqué immédiatement, sans perte de données.

## Base de données
Connexion via Session Pooler IMPÉRATIVEMENT
(`aws-0-eu-west-2.pooler.supabase.com`), JAMAIS le format "Direct
connection" (`db.xxx.supabase.co`) qui échoue sur Streamlit Cloud.
Isolation stricte des données par `user_id` sur chaque requête.

## Tâches en cours / pas encore faites
- Onglet News (Admin uniquement) : pas encore construit
- Test complet en conditions réelles de la version déployée (compte admin
  ET compte standard), pour reconfirmer isolation des données et
  permissions
- Cookie de session persistant : mis de côté pour l'instant, pas urgent
- Vérifier que les derniers ajustements (esthétique, tickers cliquables,
  précision des graphiques, refresh 30s) sont bien passés sur la version
  déployée, pas juste en local

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