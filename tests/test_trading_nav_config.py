"""Tests de la configuration statique de la navigation Trading : valeurs
d'indices recopiées à l'identique depuis l'annexe B, sources présentes,
contours existants, zone/pays renseignés sans écraser, disponibilité
calculée depuis la base.

Base SQLite temporaire (jamais Supabase), sockets piégés. Exécutable
directement : python tests/test_trading_nav_config.py
"""
import os
import socket
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "postgresql://blocked:blocked@127.0.0.1:1/blocked"


def _no_network(*args, **kwargs):
    raise AssertionError("APPEL RÉSEAU INTERDIT dans ce test")


patch.object(socket.socket, "connect", _no_network).start()

from sqlalchemy import create_engine, text

from src import daily_snapshot as ds, market_store as ms, trading_nav_config as cfg
from src.geo_outlines import GEO_OUTLINES

# Annexe B, recopiée ici indépendamment : toute modification de la config
# sans modification volontaire de ce test fait échouer le test.
ANNEXE_B = {
    "europe": [("STOXX Europe 600", 17.0, 0, True)],
    "amerique": [("S&P 500", 16.4, 1, False)],
    "asie": [("Nikkei 225", 26.2, 1, False), ("Hang Seng", 27.77, 1, False), ("Shanghai Composite", 18.41, 1, False)],
    "france": [("CAC 40", 10.42, 1, False)],
    "allemagne": [("DAX 40", 23.01, 1, False)],
    "royaume-uni": [("FTSE 100", 21.51, 1, False)],
    "suisse": [("SMI", 14.5, 1, False)],
    "pays-bas": [("AEX", 8.3, 1, False)],
    "etats-unis": [("S&P 500", 16.4, 1, False)],
    "canada": [("S&P/TSX Composite", 28.2, 1, False)],
    "japon": [("Nikkei 225", 26.2, 1, False)],
    "chine": [("Shanghai Composite", 18.41, 1, False)],
    "hong-kong": [("Hang Seng", 27.77, 1, False)],
}


def test_index_values_copied_from_annex_b():
    assert cfg.ANNEE_PERF == 2025
    for key, expected in ANNEXE_B.items():
        indices = cfg.zone_indices(key) if key in cfg.ZONES else cfg.country_indices(key)
        got = [(i["nom"], i["perf"], i["decimales"], bool(i.get("approx"))) for i in indices]
        assert got == expected, (key, got)
        for index in indices:
            assert index.get("source"), f"indice sans source : {index['nom']}"
    assert cfg.PAYS["allemagne"]["indice"]["note"] == "dividendes inclus"
    assert "Performance 2025 de l'indice" in cfg.PERF_FOOTNOTE
    print("OK: 13 cartes, indices et performances identiques à l'annexe B, chacun avec sa source")


def test_outline_keys_exist():
    used = [z["contour"] for z in cfg.ZONES.values()] + [p["contour"] for p in cfg.PAYS.values()]
    for key in used:
        assert key is None or key in GEO_OUTLINES, f"contour inconnu : {key}"
    assert cfg.PAYS["hong-kong"]["contour"] is None
    for zone_key, zone in cfg.ZONES.items():
        for country in zone["pays"]:
            assert cfg.PAYS[country]["zone"] == zone_key
    print("OK: toutes les clés de contour existent (Hong Kong sans contour), zones/pays cohérents")


def _fresh():
    engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'nav.db')}")
    ms.configure(lambda: engine)
    ms._db_unavailable_until = 0.0
    ds._ready_engine = None
    ds._places_cache.clear()
    return engine


def test_zone_country_filled_without_overwrite_and_availability():
    engine = _fresh()
    ds._engine()
    with engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT ticker, zone || '/' || country FROM asset_daily_snapshot "
                                      "WHERE zone IS NOT NULL")).fetchall())
        nulls = conn.execute(text("SELECT count(*) FROM asset_daily_snapshot WHERE zone IS NULL")).scalar()
        # Valeur posée à la main (ou par une mission future) : ne doit jamais être écrasée.
        conn.execute(text("UPDATE asset_daily_snapshot SET country = 'canada' WHERE ticker = 'MSFT'"))
    assert rows["AAPL"] == "amerique/etats-unis" and rows["TLT"] == "amerique/etats-unis", rows
    assert len(rows) == 10 and nulls == 14, (len(rows), nulls)  # crypto, forex, matières premières : sans zone
    ds._ready_engine = None
    ds._engine()  # nouveau démarrage : amorçage relancé
    msft = next(r for r in ds.list_assets("Actions") if r["ticker"] == "MSFT")
    assert msft["country"] == "canada", "valeur existante jamais écrasée"

    places = ds.available_places("Actions")
    assert places == {("amerique", "etats-unis"), ("amerique", "canada")}, places
    assert ds.available_places("Crypto") == set()
    # Liste filtrée par zone / pays (lecture seule).
    assert {r["ticker"] for r in ds.list_assets("Actions", zone="amerique", country="etats-unis")} == \
        {"AAPL", "NVDA", "GOOGL", "AMZN"}
    ms.configure(None)
    ds._places_cache.clear()
    assert ds.available_places("Actions") is None, "base absente : None, jamais d'exception"
    print("OK: zone/pays renseignés sans écraser ; disponibilité calculée depuis la base (cache 5 min)")


def test_forex_config():
    for code, currency in cfg.FOREX_CURRENCIES.items():
        assert currency["contour"] in GEO_OUTLINES, code
        assert currency["banque_centrale"] and "%" not in currency["banque_centrale"]
    assert cfg.pair_currencies("EURUSD=X") == ("EUR", "USD") and cfg.pair_currencies("AAPL") is None
    from src import asset_universe
    for ticker, _ in asset_universe.ASSETS_BY_CATEGORY[asset_universe.FOREX]:
        base, quote = cfg.pair_currencies(ticker)
        assert base in cfg.FOREX_CURRENCIES and quote in cfg.FOREX_CURRENCIES, ticker
    print("OK: devises Forex (contours existants, banque centrale sans taux), toutes les paires couvertes")


if __name__ == "__main__":
    test_index_values_copied_from_annex_b()
    test_outline_keys_exist()
    test_zone_country_filled_without_overwrite_and_availability()
    test_forex_config()
    print("Tous les tests de configuration de la navigation sont passés.")
