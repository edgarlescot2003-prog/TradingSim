-- TradingSim: tables de cache pour le tableau Admin News.
-- Migration idempotente et non destructive.
-- Aucun DROP, TRUNCATE, DELETE ou UPDATE n'est exécuté ici.

CREATE TABLE IF NOT EXISTS market_price_snapshots (
    id UUID PRIMARY KEY,
    ticker VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    category VARCHAR NOT NULL DEFAULT '',
    recorded_at VARCHAR NOT NULL,
    price_eur DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_market_price_snapshots_ticker
    ON market_price_snapshots (ticker);

CREATE INDEX IF NOT EXISTS ix_market_price_snapshots_recorded_at
    ON market_price_snapshots (recorded_at);

CREATE TABLE IF NOT EXISTS portfolio_value_snapshots (
    id UUID PRIMARY KEY,
    portfolio_id UUID NOT NULL REFERENCES portfolios (id),
    user_id UUID NOT NULL REFERENCES users (id),
    recorded_at VARCHAR NOT NULL,
    value_eur DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_portfolio_value_snapshots_portfolio_id
    ON portfolio_value_snapshots (portfolio_id);

CREATE INDEX IF NOT EXISTS ix_portfolio_value_snapshots_user_id
    ON portfolio_value_snapshots (user_id);

CREATE INDEX IF NOT EXISTS ix_portfolio_value_snapshots_recorded_at
    ON portfolio_value_snapshots (recorded_at);
