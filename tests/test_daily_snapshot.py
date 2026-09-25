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


# -- Rafraîchissement paresseux (étape 3) --------------------------------------

from datetime import date, timedelta

from src import kraken_data, market_data as md


def _series(end: date, days: int, start_price: float = 100.0, step: float = 1.0):
    """Bougies quotidiennes (week-ends compris) finissant à `end` inclus."""
    return [(end - timedelta(days=days - 1 - i), start_price + i * step) for i in range(days)]


def test_summarize_yesterday_rule_and_30d_change():
    today = date(2026, 9, 25)
    candles = _series(today, 50)  # dernière bougie = aujourd'hui (en cours)
    result = ds.summarize(candles, today)
    assert result["as_of_date"] == "2026-09-24", result  # la bougie du jour est ignorée
    close = dict(candles)[date(2026, 9, 24)]
    ref = dict(candles)[date(2026, 8, 25)]  # 30 jours avant la veille, pile
    assert abs(result["close_price"] - close) < 1e-9
    assert abs(result["change_30d_pct"] - (close / ref - 1) * 100) < 1e-9, result
    # Trou dans les données (week-end/férié) : dernière bougie AU PLUS TARD 30 j avant.
    holes = [(d, c) for d, c in candles if d != date(2026, 8, 25)]
    ref2 = dict(candles)[date(2026, 8, 24)]
    assert abs(ds.summarize(holes, today)["change_30d_pct"] - (close / ref2 - 1) * 100) < 1e-9
    # Historique trop court ou vide : donnée incomplète -> None.
    assert ds.summarize(_series(today, 20), today) is None
    assert ds.summarize([], today) is None
    assert ds.summarize([(today, 10.0)], today) is None
    print("OK: clôture de la veille (bougie du jour ignorée) et variation 30 j")


def _set_row(engine, ticker, **values):
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE asset_daily_snapshot SET {sets} WHERE ticker = :ticker"),
                     {**values, "ticker": ticker})


def _row(ticker, category):
    return next(r for r in ds.list_assets(category) if r["ticker"] == ticker)


class _Counter:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error

    def __call__(self, ticker):
        self.calls.append(ticker)
        if self.error:
            raise self.error
        return self.result(ticker) if callable(self.result) else self.result


def _good(ticker):
    today = date.today()
    return {"candles": _series(today, 45), "currency": "USD", "today": today}


def _reset_circuits():
    for d in (ms._state, ms._state_synced_at):
        d.clear()


def test_circuit_open_means_zero_calls_and_values_kept():
    engine = _fresh_engine()
    _reset_circuits()
    ds._engine()
    _set_row(engine, "AAPL", close_price=150.0, currency="USD", change_30d_pct=2.0, as_of_date="2026-01-01")
    ms.record_rate_limit(md.YAHOO, RuntimeError("Too Many Requests"))
    yahoo = _Counter(_good)
    with patch.object(md, "get_daily_closes", yahoo):
        updated, skipped = ds.refresh_category(asset_universe.ACTIONS, sleep=lambda s: None)
    assert yahoo.calls == [] and updated == 0 and skipped == 5, (yahoo.calls, updated, skipped)
    row = _row("AAPL", asset_universe.ACTIONS)
    assert row["close_price"] == 150.0 and row["last_attempt_at"] is None, row
    print("OK: coupe-circuit ouvert -> zéro appel, valeurs conservées, pas de tentative comptée")


def test_invalid_data_never_overwrites_and_no_retry_loop():
    engine = _fresh_engine()
    _reset_circuits()
    ds._engine()
    _set_row(engine, "AAPL", close_price=150.0, currency="USD", change_30d_pct=2.0, as_of_date="2026-01-01")
    today = date.today()
    short = _Counter(lambda t: {"candles": _series(today, 5), "currency": "USD", "today": today})
    with patch.object(md, "get_daily_closes", short):
        updated, _ = ds.refresh_category(asset_universe.ACTIONS, sleep=lambda s: None)
    row = _row("AAPL", asset_universe.ACTIONS)
    assert updated == 0 and row["close_price"] == 150.0 and row["change_30d_pct"] == 2.0, row
    assert row["last_attempt_at"] is not None
    failing = _Counter(error=md.MarketDataError("vide"))
    with patch.object(md, "get_daily_closes", failing):
        ds.refresh_category(asset_universe.ACTIONS, sleep=lambda s: None)
    assert failing.calls == [], "échec récent : pas de nouvel essai avant RETRY_AFTER_SECONDS"
    assert _row("AAPL", asset_universe.ACTIONS)["close_price"] == 150.0
    print("OK: donnée incomplète ou erreur -> bonne valeur conservée, pas de boucle de tentatives")


def test_successful_refresh_spacing_and_daily_guard():
    _fresh_engine()
    _reset_circuits()
    yahoo = _Counter(_good)
    sleeps = []
    with patch.object(md, "get_daily_closes", yahoo):
        updated, skipped = ds.refresh_category(asset_universe.BONDS, sleep=sleeps.append)
        again = ds.refresh_category(asset_universe.BONDS, sleep=sleeps.append)
    assert (updated, skipped) == (5, 0) and len(yahoo.calls) == 5, (updated, skipped, yahoo.calls)
    assert len(sleeps) == 4 and all(1.0 <= s <= 1.5 for s in sleeps), sleeps
    assert again == (0, 0) and len(yahoo.calls) == 5, "déjà à jour : aucune requête dans les 24 h"
    row = _row("TLT", asset_universe.BONDS)
    assert row["currency"] == "USD" and row["as_of_date"] == (date.today() - timedelta(days=1)).isoformat()
    print("OK: 5 requêtes espacées de 1 à 1,5 s, puis plus rien de la journée")


def test_crypto_uses_kraken_then_yahoo_fallback():
    _fresh_engine()
    _reset_circuits()
    kraken = _Counter(_good)
    yahoo = _Counter(_good)
    with patch.object(kraken_data, "get_daily_closes", kraken), patch.object(md, "get_daily_closes", yahoo):
        assert ds.refresh_category(asset_universe.CRYPTO, sleep=lambda s: None) == (4, 0)
    assert len(kraken.calls) == 4 and yahoo.calls == [], (kraken.calls, yahoo.calls)

    _fresh_engine()
    _reset_circuits()
    kraken = _Counter(error=md.MarketDataError("Unknown asset pair"))
    yahoo = _Counter(_good)
    with patch.object(kraken_data, "get_daily_closes", kraken), patch.object(md, "get_daily_closes", yahoo):
        assert ds.refresh_category(asset_universe.CRYPTO, sleep=lambda s: None) == (4, 0)
    assert len(yahoo.calls) == 4, "Kraken en échec -> secours Yahoo"

    _fresh_engine()
    _reset_circuits()
    ms.record_rate_limit(kraken_data.KRAKEN, RuntimeError("EAPI:Rate limit exceeded"))
    ms.record_rate_limit(md.YAHOO, RuntimeError("Too Many Requests"))
    kraken, yahoo = _Counter(_good), _Counter(_good)
    with patch.object(kraken_data, "get_daily_closes", kraken), patch.object(md, "get_daily_closes", yahoo):
        ds.refresh_category(asset_universe.CRYPTO, sleep=lambda s: None)
    assert kraken.calls == [] and yahoo.calls == [], "deux coupe-circuits ouverts -> zéro appel"
    print("OK: crypto via Kraken, secours Yahoo si Kraken échoue, zéro appel si les deux sont en pause")


def test_fetchers_parse_source_payloads():
    import pandas as pd

    _fresh_engine()
    _reset_circuits()
    index = pd.date_range("2026-07-20", periods=60, freq="D", tz="America/New_York")
    hist = pd.DataFrame({"Close": [100.0 + i for i in range(60)]}, index=index)

    class _History:
        _history_metadata = {"currency": "USD", "exchangeTimezoneName": "America/New_York"}

    class _Ticker:
        calls = 0

        def __init__(self, ticker):
            self._price_history = _History()

        def history(self, **kwargs):
            type(self).calls += 1
            assert kwargs == {"period": "2mo", "interval": "1d"}, kwargs
            return hist

    with patch.object(md.yf, "Ticker", _Ticker):
        result = md.get_daily_closes("AAPL")
    assert _Ticker.calls == 1 and result["currency"] == "USD" and len(result["candles"]) == 60
    assert result["candles"][0] == (date(2026, 7, 20), 100.0), result["candles"][0]

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            base = 1_780_000_000 - 1_780_000_000 % 86400
            return {"error": [], "result": {
                "XXBTZUSD": [[base + i * 86400, "1", "1", "1", str(50_000 + i), "1", "1", 1] for i in range(40)],
                "last": base}}

    requests_seen = []
    with patch.object(kraken_data.requests, "get", lambda url, params, timeout: requests_seen.append(params) or _Resp()):
        result = kraken_data.get_daily_closes("BTC-USD")
    assert len(requests_seen) == 1 and requests_seen[0]["pair"] == "XBTUSD" and requests_seen[0]["interval"] == 1440
    assert result["currency"] == "USD" and result["candles"][-1][1] == 50_039.0
    print("OK: lecture des réponses Yahoo (devise dans les métadonnées) et Kraken, une requête chacune")


def test_calendar_day_rule():
    from datetime import datetime, timezone

    def ts(text):
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()

    now = ts("2026-09-26T00:05:00")
    assert ds.is_due({"updated_at": ds.iso(ts("2026-09-25T23:59:00"))}, now), "mis à jour hier -> à recharger"
    assert not ds.is_due({"updated_at": ds.iso(ts("2026-09-26T00:01:00"))}, now), "déjà mis à jour aujourd'hui"
    assert ds.is_due({"updated_at": None, "last_attempt_at": None}, now)
    assert not ds.is_due({"updated_at": None, "last_attempt_at": ds.iso(now - 3600)}, now), "échec récent : attendre"
    print("OK: règle « une fois par jour calendaire UTC » (passage de minuit compris)")


def test_refresh_all_due_for_cron():
    _fresh_engine()
    _reset_circuits()
    kraken, yahoo = _Counter(_good), _Counter(_good)
    with patch.object(kraken_data, "get_daily_closes", kraken), patch.object(md, "get_daily_closes", yahoo), \
            patch.object(ds, "REQUEST_SPACING_SECONDS", 0.0), patch.object(ds, "REQUEST_JITTER_SECONDS", 0.0):
        assert ds.acquire_lease(ds.lease_name(asset_universe.FOREX), "app-visiteur")
        first = ds.refresh_all_due(holder="test")
        second = ds.refresh_all_due(holder="test")
    assert first[asset_universe.FOREX] == "déjà en cours ailleurs", first
    assert first["Actions:amerique"] == "5 mis à jour, 0 ignoré(s)" and first[asset_universe.CRYPTO].startswith("4"), first
    assert len(kraken.calls) == 4 and len(yahoo.calls) == 15, (len(kraken.calls), len(yahoo.calls))
    assert second["Actions:amerique"] == "déjà à jour", "second passage de la journée : aucune requête"
    assert len(yahoo.calls) == 15
    assert ds.acquire_lease(ds.lease_name("Actions:amerique"), "autre"), "bail relâché par le cron"
    print("OK: pré-chargement cron (toutes les listes dues, bail respecté, rien au 2e passage du jour)")


def test_cron_script_never_imports_streamlit():
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import sys; sys.modules['streamlit'] = None; "
            "import scripts.refresh_daily_lists, src.daily_snapshot, src.market_data, src.kraken_data; print('ok')")
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and "ok" in result.stdout, result.stderr[-800:]
    print("OK: le script du cron s'importe sans Streamlit (comme l'environnement GitHub Actions)")


def test_background_trigger_single_run():
    import threading as th
    import time as tm

    _fresh_engine()
    _reset_circuits()
    release = th.Event()

    def slow(ticker):
        release.wait(10)
        return _good(ticker)

    yahoo = _Counter(slow)
    with patch.object(md, "get_daily_closes", yahoo), patch.object(ds, "REQUEST_SPACING_SECONDS", 0.0), \
            patch.object(ds, "REQUEST_JITTER_SECONDS", 0.0):
        assert ds.start_refresh_if_due(asset_universe.FOREX) == "started"
        assert ds.start_refresh_if_due(asset_universe.FOREX) == "busy"
        assert ds.is_refreshing(asset_universe.FOREX)
        release.set()
        for _ in range(100):
            if not ds.is_refreshing(asset_universe.FOREX):
                break
            tm.sleep(0.05)
    assert len(yahoo.calls) == 5, yahoo.calls
    assert ds.start_refresh_if_due(asset_universe.FOREX) == "fresh"
    assert ds.acquire_lease(ds.lease_name(asset_universe.FOREX), "other"), "bail relâché à la fin"
    print("OK: déclenchement en arrière-plan, un seul à la fois, bail relâché à la fin")


def test_fallback_scoped_single_and_paused():
    import threading as th
    import time as tm

    engine = _fresh_engine()
    _reset_circuits()
    ds._engine()
    _set_row(engine, "MSFT", zone="europe")
    _set_row(engine, "NVDA", zone="europe")
    release = th.Event()

    def slow(ticker):
        release.wait(10)
        return _good(ticker)

    yahoo = _Counter(slow)
    with patch.object(md, "get_daily_closes", yahoo), patch.object(ds, "REQUEST_SPACING_SECONDS", 0.0),             patch.object(ds, "REQUEST_JITTER_SECONDS", 0.0):
        assert ds.start_refresh_if_due(asset_universe.ACTIONS, zone="europe") == "started"
        assert ds.start_refresh_if_due(asset_universe.ACTIONS, zone="europe") == "busy"
        assert ds.start_refresh_if_due(asset_universe.ACTIONS, zone="amerique") == "queued", "un seul à la fois"
        assert ds.start_refresh_if_due(asset_universe.CRYPTO) == "queued"
        release.set()
        for _ in range(100):
            if ds.active_scope() is None:
                break
            tm.sleep(0.05)
    assert sorted(yahoo.calls) == ["MSFT", "NVDA"], "seule la liste affichée (zone Europe) est chargée"
    ms.record_rate_limit(md.YAHOO, RuntimeError("Too Many Requests"))
    assert ds.start_refresh_if_due(asset_universe.ACTIONS, zone="amerique") == "paused", "source en pause"
    print("OK: secours limité à la liste affichée, un seul chargement à la fois (« en attente »), rien si source en pause")


if __name__ == "__main__":
    test_seed_inserts_universe_without_indices_and_never_overwrites()
    test_lease_single_winner_and_expiry()
    test_concurrent_acquisitions_one_winner()
    test_database_unavailable_is_graceful()
    test_summarize_yesterday_rule_and_30d_change()
    test_circuit_open_means_zero_calls_and_values_kept()
    test_invalid_data_never_overwrites_and_no_retry_loop()
    test_successful_refresh_spacing_and_daily_guard()
    test_crypto_uses_kraken_then_yahoo_fallback()
    test_fetchers_parse_source_payloads()
    test_calendar_day_rule()
    test_refresh_all_due_for_cron()
    test_cron_script_never_imports_streamlit()
    test_background_trigger_single_run()
    test_fallback_scoped_single_and_paused()
    print("Tous les tests des prix indicatifs quotidiens sont passés.")
