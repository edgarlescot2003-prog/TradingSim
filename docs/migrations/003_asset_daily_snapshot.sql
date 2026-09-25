-- TradingSim : prix indicatifs quotidiens des pages de liste Trading + bail
-- de rafraîchissement.
-- Migration idempotente et non destructive (aucun DROP/DELETE/UPDATE/TRUNCATE).
-- NB : l'app crée aussi ces tables automatiquement au démarrage
-- (db_core.ensure_schema + daily_snapshot._CREATE_TABLES_SQL) ; ce fichier sert
-- de référence et peut être exécuté à la main dans l'éditeur SQL de Supabase.

CREATE TABLE IF NOT EXISTS asset_daily_snapshot (
    ticker VARCHAR PRIMARY KEY,           -- ticker Yahoo (ex : AAPL, BTC-USD, EURUSD=X)
    name VARCHAR NOT NULL,                -- nom affiché
    category VARCHAR NOT NULL,            -- Actions, Crypto, Obligations, Forex, Matières premières
    zone VARCHAR,                         -- réservé à une phase ultérieure
    country VARCHAR,                      -- réservé à une phase ultérieure
    close_price DOUBLE PRECISION,         -- clôture de la veille, devise native
    currency VARCHAR,                     -- devise réelle de l'actif
    change_30d_pct DOUBLE PRECISION,      -- variation sur 30 jours (%)
    as_of_date VARCHAR,                   -- date de la clôture (AAAA-MM-JJ)
    updated_at VARCHAR,                   -- dernière mise à jour réussie (ISO 8601 UTC)
    last_attempt_at VARCHAR               -- dernière tentative, réussie ou non (ISO 8601 UTC)
);

CREATE INDEX IF NOT EXISTS ix_asset_daily_snapshot_category ON asset_daily_snapshot (category);

CREATE TABLE IF NOT EXISTS refresh_leases (
    name VARCHAR PRIMARY KEY,             -- ex : 'asset_daily:Crypto'
    leased_until VARCHAR NOT NULL,        -- ISO 8601 UTC ; bail libre si dans le passé
    holder VARCHAR                        -- identifiant du processus détenteur
);
