"""Garde contre l'incident du 25/09 : après un push, Streamlit Cloud réimporte
tous les modules src.* sans relancer db.bootstrap (mis en cache) ; le
market_store réimporté repartait débranché de la base (coupe-circuit,
derniers prix connus et listes en mémoire seule, sans aucun message).

Simulation : importlib.reload(market_store) remet le module dans l'état d'un
module fraîchement réimporté (variables globales à zéro), en cours de
session. On vérifie que db.ensure_market_store (appelé à chaque exécution de
app.py) le rebranche, et que les TROIS mécanismes réécrivent en base :
listes (asset_daily_snapshot), dernier prix connu, coupe-circuit.

Base SQLite temporaire (db.get_engine remplacé), sockets piégés : jamais de
réseau, jamais Supabase. Exécutable directement :
python tests/test_hot_reload_reconnect.py
"""
import importlib
import os
import socket
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"


def _no_network(*args, **kwargs):
    raise AssertionError("APPEL RÉSEAU INTERDIT dans ce test")


patch.object(socket.socket, "connect", _no_network).start()

from sqlalchemy import create_engine, text

from src import daily_snapshot as ds, db, market_store as ms

ENGINE = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'reload.db')}")
patch.object(db, "get_engine", lambda: ENGINE).start()


def _count(sql):
    with ENGINE.connect() as conn:
        return conn.execute(text(sql)).scalar()


def test_reimported_store_is_reconnected_for_all_three_mechanisms():
    # Démarrage normal (ce que fait db.bootstrap) : tout est branché.
    ms.configure(lambda: ENGINE)
    ds._ready_engine = None
    assert ms.is_configured() and ds.list_assets("Crypto") is not None

    # Push -> modules réimportés : le market_store repart à zéro.
    importlib.reload(ms)
    ds._ready_engine = None
    assert not ms.is_configured()
    assert ds.list_assets("Crypto") is None, "c'était le symptôme en prod : liste 'indisponible'"

    # Exécution suivante de app.py.
    db.ensure_market_store()
    assert ms.is_configured()

    # 1. Listes : lecture en base de nouveau possible.
    rows = ds.list_assets("Crypto")
    assert rows is not None and len(rows) == 4, rows
    # 2. Dernier prix connu : réécrit en base (pas seulement en mémoire).
    ms.remember_prices([{"ticker": "ZZTEST", "price": 1.0, "currency": "USD", "fetched_at": time.time()}])
    assert _count("SELECT count(*) FROM last_known_prices WHERE ticker = 'ZZTEST'") == 1
    # 3. Coupe-circuit : persisté en base, donc partagé entre processus.
    ms.record_rate_limit("yahoo", RuntimeError("Too Many Requests"))
    assert _count("SELECT count(*) FROM api_circuit_state WHERE source = 'yahoo' AND blocked_until IS NOT NULL") == 1

    # Appels suivants : rien à faire (simple vérification en mémoire).
    getter = ms._engine_getter
    db.ensure_market_store()
    assert ms._engine_getter is getter
    print("OK: module réimporté -> rebranché ; listes, dernier prix connu et coupe-circuit réécrivent en base")


def test_reconnect_never_crashes_when_engine_unavailable():
    importlib.reload(ms)

    def broken():
        raise RuntimeError("DATABASE_URL introuvable")

    with patch.object(db, "get_engine", broken):
        db.ensure_market_store()  # ne lève pas
    assert not ms.is_configured()
    db.ensure_market_store()  # la base revient : rebranché au run suivant
    assert ms.is_configured()
    print("OK: base injoignable au moment du rebranchement -> pas de plantage, nouvel essai au run suivant")


def test_app_calls_reconnect_on_every_run():
    """app.py doit appeler ensure_market_store à CHAQUE exécution, pas
    seulement dans le bloc « db_ready » (une seule fois par session)."""
    source = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"),
                  encoding="utf-8").read()
    lines = source.splitlines()
    call = next(i for i, line in enumerate(lines) if "db.ensure_market_store()" in line)
    assert not lines[call].startswith((" ", "\t")), "l'appel doit être au niveau du module, hors de tout if"
    assert call < next(i for i, line in enumerate(lines) if "ui_auth.render()" in line), \
        "avant la porte de connexion"
    print("OK: app.py rebranche à chaque exécution, avant la porte de connexion")


if __name__ == "__main__":
    test_reimported_store_is_reconnected_for_all_three_mechanisms()
    test_reconnect_never_crashes_when_engine_unavailable()
    test_app_calls_reconnect_on_every_run()
    print("Tous les tests de rebranchement après rechargement à chaud sont passés.")
