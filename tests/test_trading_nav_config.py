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

# Valeurs sourcées (annexe B du 24/09/2026 + KOSPI, Nifty 50, TAIEX du
# 25/09/2026), recopiées ici indépendamment : toute modification de la
# config sans modification volontaire de ce test fait échouer le test.
ANNEXE_B = {
    "europe": [("STOXX Europe 600", 17.0, 0, True)],
    "amerique": [("S&P 500", 16.4, 1, False), ("S&P/TSX Composite", 28.2, 1, False)],
    "asie": [("Nikkei 225", 26.2, 1, False), ("TAIEX", 25.73, 1, False), ("Nifty 50", 10.51, 1, False),
             ("KOSPI", 75.6, 1, False)],
}


def test_index_values_copied_from_annex_b():
    assert cfg.ANNEE_PERF == 2025
    for key, expected in ANNEXE_B.items():
        indices = cfg.zone_indices(key)
        got = [(i["nom"], i["perf"], i["decimales"], bool(i.get("approx"))) for i in indices]
        assert got == expected, (key, got)
        for index in indices:
            assert index.get("source"), f"indice sans source : {index['nom']}"
    assert set(cfg.ZONES) == {"europe", "amerique", "asie"}
    assert "Performance 2025 de l'indice" in cfg.PERF_FOOTNOTE
    print("OK: 3 zones, indices et performances identiques aux valeurs sourcées, chacun avec sa source")


def test_outline_keys_exist_and_universe_consistent():
    from src import asset_universe as au
    used = [z["contour"] for z in cfg.ZONES.values()] + [c["contour"] for c in cfg.FOREX_CURRENCIES.values()]
    for key in used:
        assert key in GEO_OUTLINES, f"contour inconnu : {key}"
    assert au.ZONES == list(cfg.ZONES)
    for zone in au.ZONES:
        assert len(au.STOCKS_BY_ZONE[zone]) == 30, zone
        for _, _, country in au.STOCKS_BY_ZONE[zone]:
            assert country in au.COUNTRY_NAMES, country
    print("OK: contours existants (zones et devises), 3 zones de 30 actions, pays connus")


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
    assert rows["ASML.AS"] == "europe/pays-bas" and rows["2330.TW"] == "asie/taiwan", rows
    assert len(rows) == 106 and nulls == 54, (len(rows), nulls)  # 90 actions + 16 obligations ; crypto, forex, MP : sans zone
    ds._ready_engine = None
    ds._engine()  # nouveau démarrage : amorçage relancé
    msft = next(r for r in ds.list_assets("Actions") if r["ticker"] == "MSFT")
    assert msft["country"] == "canada", "valeur existante jamais écrasée"

    places = ds.available_places("Actions")
    assert {z for z, _ in places} == {"europe", "amerique", "asie"}, places
    assert ("amerique", "canada") in places and ("asie", "inde") in places
    assert ds.available_places("Crypto") == set()
    # Liste filtrée par zone (lecture seule) : 30 actions, sans les ETF obligataires.
    amerique = {r["ticker"] for r in ds.list_assets("Actions", zone="amerique")}
    assert len(amerique) == 30 and "RY.TO" in amerique and "TLT" not in amerique
    ms.configure(None)
    ds._places_cache.clear()
    assert ds.available_places("Actions") is None, "base absente : None, jamais d'exception"
    print("OK: zone/pays renseignés sans écraser ; disponibilité calculée depuis la base (cache 5 min)")


def test_commodity_families():
    from src import asset_universe as au
    grouped = sorted(t for f in au.COMMODITY_FAMILIES.values() for t in f["tickers"])
    assert grouped == sorted(t for t, _ in au.ASSETS_BY_CATEGORY[au.COMMODITIES])
    assert list(au.COMMODITY_FAMILIES) == ["metaux", "energie", "agriculture"]
    print("OK: 3 familles de matières premières couvrant les 16 contrats")


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


def test_bond_groups_config():
    from src import asset_universe
    grouped = [t for g in cfg.BOND_GROUPS.values() for t in g["tickers"]]
    universe = [t for t, _ in asset_universe.ASSETS_BY_CATEGORY[asset_universe.BONDS]]
    assert sorted(grouped) == sorted(universe), "chaque ETF obligataire est dans exactement une maturité"
    assert "de 1 à 3 ans (SHY)" in cfg.BOND_GROUPS["court-terme"]["description"]
    assert len(cfg.BOND_GROUPS) == 6
    assert "investment grade" in cfg.BOND_GROUPS["diversifies"]["description"], "BND/AGG ne sont pas que de l'État"
    for group in cfg.BOND_GROUPS.values():
        assert group["zone"] in cfg.ZONES, "niveau zone prévu pour plus tard"
    print("OK: maturités obligataires (descriptions vérifiées, chaque ETF classé une fois, zone prévue)")


if __name__ == "__main__":
    test_index_values_copied_from_annex_b()
    test_outline_keys_exist_and_universe_consistent()
    test_zone_country_filled_without_overwrite_and_availability()
    test_forex_config()
    test_bond_groups_config()
    test_commodity_families()
    print("Tous les tests de configuration de la navigation sont passés.")
