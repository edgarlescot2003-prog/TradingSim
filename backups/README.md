# Sauvegardes de la base TradingSim

Ce dossier contient des sauvegardes automatiques quotidiennes de toutes les
tables de la base Supabase, au format CSV (un fichier par table), générées
par le workflow GitHub Actions `.github/workflows/backup.yml` et le script
`scripts/backup_db.py`. Aucun service payant : tout repose sur GitHub Actions
(gratuit) et sur le dépôt GitHub lui-même comme stockage.

Chaque sauvegarde vit dans un dossier `AAAA-MM-JJ/` (une par jour). Seules
les **14 dernières** sont conservées (rotation automatique) pour ne pas faire
grossir le dépôt indéfiniment.

## ⚙️ Mise en place (une seule fois)

Pour que la sauvegarde automatique fonctionne, GitHub a besoin de la chaîne
de connexion à la base (`DATABASE_URL`), sans qu'elle soit jamais écrite en
clair dans le code. Ça se fait via un **secret GitHub** :

1. Va sur la page du dépôt sur GitHub : `https://github.com/edgarlescot2003-prog/TradingSim`
2. Clique sur **Settings** (en haut du dépôt, pas les paramètres de ton compte).
3. Dans le menu de gauche : **Secrets and variables** → **Actions**.
4. Clique sur **New repository secret**.
5. Nom du secret : `DATABASE_URL`
6. Valeur : colle exactement la même chaîne de connexion que celle présente
   dans ton fichier `.env` local (celle en format **Session Pooler**,
   `aws-0-eu-west-2.pooler.supabase.com` — jamais le format "Direct
   connection").
7. Clique sur **Add secret**.

C'est tout — le workflow tournera automatiquement chaque nuit à partir de là
(pas besoin de le relancer toi-même). Tu peux vérifier que ça a bien tourné
dans l'onglet **Actions** du dépôt GitHub (workflow "Sauvegarde quotidienne
de la base").

### Lancer une sauvegarde manuellement (sans attendre la nuit)

Dans l'onglet **Actions** du dépôt GitHub → clique sur "Sauvegarde
quotidienne de la base" dans la liste de gauche → bouton **Run workflow**
(en haut à droite) → **Run workflow**.

## 🆘 Restaurer une sauvegarde (en cas de problème)

⚠️ Cette opération **remplace entièrement** les données actuelles de la base
par celles de la sauvegarde choisie. À ne faire qu'en cas de réel problème
(suppression accidentelle, corruption, bug).

1. Choisis le dossier de sauvegarde à restaurer (ex : `backups/2026-09-10/`)
   — le plus récent avant l'incident, en général.
2. Ouvre un terminal dans VS Code, à la racine du projet (là où se trouve
   `app.py`).
3. Assure-toi que ton fichier `.env` local pointe bien vers la bonne base
   Supabase (`DATABASE_URL`, format Session Pooler).
4. Lance :
   ```
   python -m scripts.restore_db backups/2026-09-10
   ```
   (remplace la date par le dossier choisi)
5. Le script te demande de confirmer en tapant `OUI` en majuscules — c'est
   voulu, pour ne jamais restaurer par erreur en appuyant trop vite sur
   Entrée.
6. Une fois terminé, reboote l'app sur Streamlit Cloud (menu ⋮ → **Reboot
   app**) pour repartir sur des données fraîches.

Si tu n'es pas sûr de toi ou que le résultat ne te semble pas correct,
arrête-toi et redemande-moi de l'aide avant d'aller plus loin — la
sauvegarde CSV elle-même n'est jamais modifiée par cette opération, tu peux
donc toujours réessayer.

## Contenu de chaque sauvegarde

Un fichier CSV par table : `users`, `portfolios`, `positions`, `trades`,
`pending_orders`, `value_history`, `search_history`, `courses`, `news`.

⚠️ Le fichier `users.csv` contient les mots de passe **hachés** (bcrypt, pas
en clair — impossible à retrouver depuis le hash) de chaque compte. Le dépôt
GitHub étant privé, c'est un compromis jugé acceptable pour que la
restauration recrée des comptes utilisables sans que personne n'ait à
recréer son mot de passe. Ne rends jamais ce dépôt public sans y penser.
