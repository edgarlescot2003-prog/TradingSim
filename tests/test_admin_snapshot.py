"""Test à blanc du snapshot Admin News (admin_snapshot.record_snapshots) sur
une base SQLite temporaire avec un faux portefeuille officiel : prix mockés,
aucun appel réseau, jamais Supabase.

Exécutable directement : python tests/test_admin_snapshot.py
"""
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src import admin_snapshot
from src import market_data as md
from src.db_models import (
    Base, MarketPriceSnapshotRow, PortfolioRow, PortfolioValueSnapshotRow, PositionRow, User,
)


def _session_with_official_portfolio():
    engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'a.db')}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    user = User(username="jetable", password_hash="x")
    session.add(user)
    session.flush()
    pf = PortfolioRow(user_id=user.id, name="Officiel", initial_capital=10_000, cash=9_000, is_official=True)
    session.add(pf)
    session.flush()
    session.add(PositionRow(portfolio_id=pf.id, user_id=user.id, ticker="AAPL", name="Apple", quantity=10,
                            avg_price_eur=100.0, currency="USD", entry_date="2026-09-01", margin_eur=1_000))
    session.commit()
    return session


def _quotes(stale=False):
    return {"AAPL": {"price": 110.0, "currency": "USD", "stale": stale},
            "BTC-USD": {"price": 80_000.0, "currency": "USD", "stale": stale}}


def test_records_then_skips_within_the_hour():
    session = _session_with_official_portfolio()
    with patch.object(md, "get_quotes_batch", return_value=_quotes()) as batch, \
         patch.object(md, "get_fx_rate_to_eur", return_value=0.9):
        assert admin_snapshot.record_snapshots(session) == (2, 1)
        assert "AAPL" in batch.call_args[0][0]  # positions officielles incluses dans le batch
        assert admin_snapshot.record_snapshots(session) == (0, 0)  # < 55 min : rien
    value = session.execute(select(PortfolioValueSnapshotRow.value_eur)).scalar()
    assert abs(value - (9_000 + 1_000 + (110 * 0.9 - 100) * 10)) < 1e-6
    print("OK: snapshot enregistré (import corrigé), puis ignoré dans l'heure")


def test_stale_or_empty_prices_write_nothing():
    session = _session_with_official_portfolio()
    with patch.object(md, "get_quotes_batch", return_value=_quotes(stale=True)), \
         patch.object(md, "get_fx_rate_to_eur", return_value=0.9):
        assert admin_snapshot.record_snapshots(session) == (0, 0)
    assert session.execute(select(func.count()).select_from(MarketPriceSnapshotRow)).scalar() == 0
    print("OK: source en pause -> aucun snapshot écrit (jamais de prix daté ni de valeur trompeuse)")


if __name__ == "__main__":
    test_records_then_skips_within_the_hour()
    test_stale_or_empty_prices_write_nothing()
    print("Tous les tests du snapshot Admin sont passés.")
