-- TradingSim : coupe-circuit des APIs de marché + dernier prix connu.
-- Migration idempotente et non destructive (aucun DROP/DELETE/UPDATE/TRUNCATE).
-- NB : l'app et les scripts du cron créent aussi ces tables automatiquement
-- (db_core.ensure_schema + market_store._CREATE_TABLES_SQL) ; ce fichier sert
-- de référence et peut être exécuté à la main dans l'éditeur SQL de Supabase.

CREATE TABLE IF NOT EXISTS api_circuit_state (
    source VARCHAR PRIMARY KEY,           -- 'yahoo' ou 'kraken'
    blocked_until VARCHAR,                -- ISO 8601 UTC, NULL = pas de pause
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error VARCHAR,
    updated_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS last_known_prices (
    ticker VARCHAR PRIMARY KEY,           -- ticker Yahoo, ou 'FX:USD' pour un taux -> EUR
    price DOUBLE PRECISION NOT NULL,      -- devise native
    currency VARCHAR NOT NULL,
    previous_close DOUBLE PRECISION,
    quote_type VARCHAR,
    market_time VARCHAR,                  -- heure de cotation réelle (ISO), si connue
    fetched_at VARCHAR NOT NULL,          -- heure d'obtention auprès de la source (ISO)
    change_30d_pct DOUBLE PRECISION,
    change_30d_at VARCHAR
);

-- Traçabilité des ordres exécutés sur prix daté (colonnes nullables, additives).
ALTER TABLE trades ADD COLUMN IF NOT EXISTS price_age_seconds DOUBLE PRECISION;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS price_source VARCHAR;
