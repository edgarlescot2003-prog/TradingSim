"""Tests autonomes des prix indicatifs quotidiens (daily_snapshot) : table,
amorçage, bail de rafraîchissement.

Base SQLite temporaire (jamais Supabase), aucun appel réseau (toute
connexion socket est piégée). Exécutable directement :
python tests/test_daily_snapshot.py
"""
import os
import socket
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"

from sqlalchemy import create_engine, text

from src import asset_universe, daily_snapshot as ds, market_store as ms


def _no_network(*args, **kwargs):
    raise AssertionError("APPEL RÉSEAU INTERDIT dans ce test")


patch.object(socket.socket, "connect", _no_network).start()
patch.object(socket, "create_connection", _no_network).start()


def _fresh_engine():
    engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'daily.db')}")
    ms.configure(lambda: engine)
    ms._db_unavailable_until = 0.0
    ds._ready_engine = None
    return engine


def test_seed_inserts_universe_without_indices_and_never_overwrites():
    engine = _fresh_engine()
    rows = ds.list_assets(asset_universe.CRYPTO)
    assert [r["ticker"] for r in rows] == ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"], rows
    assert all(r["close_price"] is None and r["zone"] is None for r in rows)
    with engine.begin() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM asset_daily_snapshot")).scalar()
        indices = conn.execute(text("SELECT COUNT(*) FROM asset_daily_snapshot WHERE ticker LIKE '^%'")).scalar()
        conn.execute(text("UPDATE asset_daily_snapshot SET close_price = 42.0 WHERE ticker = 'AAPL'"))
    assert total == len(asset_universe.all_assets()) == 24 and indices == 0, (total, indices)
    ds._ready_engine = None  # simule un redémarrage : ré-amorçage
    aapl = next(r for r in ds.list_assets(asset_universe.ACTIONS) if r["ticker"] == "AAPL")
    assert aapl["close_price"] == 42.0, "l'amorçage ne doit jamais écraser une ligne existante"
    print("OK: amorçage (24 actifs, aucun indice), jamais d'écrasement")


def test_lease_single_winner_and_expiry():
    _fresh_engine()
    now = 1_000_000.0
    assert ds.acquire_lease("asset_daily:Crypto", "A", now=now)
    assert not ds.acquire_lease("asset_daily:Crypto", "B", now=now + 1)
    assert ds.acquire_lease("asset_daily:Actions", "B", now=now + 1), "un bail par catégorie"
    # Bail expiré (processus A tué sans relâcher) : récupérable.
    assert ds.acquire_lease("asset_daily:Crypto", "B", now=now + ds.LEASE_SECONDS + 1)
    ds.release_lease("asset_daily:Crypto", "A")  # A ne peut pas relâcher le bail de B
    assert not ds.acquire_lease("asset_daily:Crypto", "C", now=now + ds.LEASE_SECONDS + 2)
    ds.release_lease("asset_daily:Crypto", "B")
    assert ds.acquire_lease("asset_daily:Crypto", "C", now=now + ds.LEASE_SECONDS + 3)
    print("OK: bail exclusif, expiré récupérable, relâché seulement par son détenteur")


def test_concurrent_acquisitions_one_winner():
    _fresh_engine()
    ds._engine()  # tables prêtes avant la course
    results = []
    barrier = threading.Barrier(8)

    def contender(i):
        barrier.wait()
        results.append(ds.acquire_lease("asset_daily:Forex", f"P{i}"))

    threads = [threading.Thread(target=contender, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1, results
    print("OK: 8 acquisitions simultanées (threads) -> un seul gagnant")


def test_database_unavailable_is_graceful():
    ms.configure(None)
    ds._ready_engine = None
    assert ds.list_assets(asset_universe.ACTIONS) is None
    assert ds.acquire_lease("asset_daily:Actions", "A") is False
    ds.release_lease("asset_daily:Actions", "A")  # ne lève pas

    def broken():
        raise RuntimeError("base injoignable")

    ms.configure(broken)
    ms._db_unavailable_until = 0.0
    assert ds.list_assets(asset_universe.ACTIONS) is None
    print("OK: base absente/injoignable -> None/False, jamais d'exception")


if __name__ == "__main__":
    test_seed_inserts_universe_without_indices_and_never_overwrites()
    test_lease_single_winner_and_expiry()
    test_concurrent_acquisitions_one_winner()
    test_database_unavailable_is_graceful()
    print("Tous les tests des prix indicatifs quotidiens sont passés.")
