"""Tests fonctionnels du camembert de diversification secteur/géographie
(prompt 21, point 2) : logique pure (valuation.sector_for/country_for,
ui_portfolio._allocation_by_sector/_allocation_by_geography), sans réseau ni
Streamlit — market_data.get_company_profile est monkeypatché partout, jamais
appelé pour de vrai. Insiste particulièrement sur le repli "Non défini" :
c'est le point explicitement demandé (par Edgar) à vérifier avant de livrer
cette fonctionnalité, aussi bien pour les classes d'actif qui n'ont
structurellement pas de secteur/géographie que pour un ticker qui DEVRAIT en
avoir un mais dont l'appel yfinance échoue ou renvoie un champ vide.

Exécutable directement : python tests/test_diversification.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import market_data as md
from src import valuation
from src import ui_portfolio
from src.portfolio import Position


def test_get_company_profile_never_raises_on_api_error():
    """Ticker introuvable / API en panne : get_company_profile doit renvoyer
    des champs None, jamais lever — c'est ce filet qui permet à sector_for/
    country_for de ne jamais planter le calcul du camembert."""
    md._PROFILE_CACHE.clear()

    class _BoomTicker:
        @property
        def info(self):
            raise RuntimeError("API indisponible")

    original_ticker = md.yf.Ticker
    md.yf.Ticker = lambda ticker: _BoomTicker()
    try:
        profile = md.get_company_profile("BROKEN")
    finally:
        md.yf.Ticker = original_ticker

    assert profile == {"sector": None, "country": None}
    print("OK: get_company_profile ne lève jamais, même si l'API yfinance échoue")


def test_get_company_profile_treats_missing_or_empty_fields_as_none():
    """Un ticker qui répond mais sans champ "sector"/"country" exploitable
    (absent ou chaîne vide) doit aussi ressortir en None, pas planter ni
    renvoyer une chaîne vide telle quelle (qui serait une catégorie "vide"
    invisible dans le camembert plutôt qu'un vrai "Non défini")."""
    md._PROFILE_CACHE.clear()

    class _EmptyFieldsTicker:
        info = {"sector": "", "country": None, "autre_champ": "ignoré"}

    original_ticker = md.yf.Ticker
    md.yf.Ticker = lambda ticker: _EmptyFieldsTicker()
    try:
        profile = md.get_company_profile("EMPTYFIELDS")
    finally:
        md.yf.Ticker = original_ticker

    assert profile == {"sector": None, "country": None}
    print("OK: champs vides/absents traités comme None, pas comme une valeur exploitable")


def _fake_profile(sector=None, country=None):
    return lambda ticker: {"sector": sector, "country": country}


def test_sector_for_crypto_is_fintech_without_api_call():
    calls = []
    original = md.get_company_profile
    md.get_company_profile = lambda ticker: calls.append(ticker) or _fake_profile()(ticker)
    try:
        assert valuation.sector_for("Crypto", "BTC-USD") == "FinTech"
    finally:
        md.get_company_profile = original
    assert calls == [], "Crypto ne doit jamais déclencher d'appel yfinance pour le secteur"
    print("OK: Crypto -> FinTech, sans appel API")


def test_sector_and_country_for_forex_are_undefined_without_api_call():
    calls = []
    original = md.get_company_profile
    md.get_company_profile = lambda ticker: calls.append(ticker) or {"sector": None, "country": None}
    try:
        assert valuation.sector_for("Forex", "EURUSD=X") == valuation.UNDEFINED_LABEL
        assert valuation.country_for("Forex", "EURUSD=X") == valuation.UNDEFINED_LABEL
    finally:
        md.get_company_profile = original
    assert calls == [], "Forex ne doit jamais déclencher d'appel yfinance"
    print("OK: Forex -> Non défini pour secteur ET géographie, sans appel API")


def test_sector_for_commodities_uses_fixed_mapping_without_api_call():
    """Suite au retour d'Edgar : les matières premières avaient toutes un
    secteur "Non défini" (yfinance n'a pas de champ secteur exploitable pour
    un contrat future) — mapping fixe à deux sous-secteurs (Énergie / Métaux
    précieux) demandé explicitement plutôt qu'un unique "Non défini" ou une
    seule catégorie "Matières premières" globale."""
    calls = []
    original = md.get_company_profile
    md.get_company_profile = lambda ticker: calls.append(ticker) or {"sector": None, "country": None}
    try:
        assert valuation.sector_for("Matières premières", "GC=F") == "Métaux précieux"
        assert valuation.sector_for("Matières premières", "SI=F") == "Métaux précieux"
        assert valuation.sector_for("Matières premières", "CL=F") == "Énergie"
        assert valuation.sector_for("Matières premières", "BZ=F") == "Énergie"
        assert valuation.sector_for("Matières premières", "NG=F") == "Énergie"
        # Géographie inchangée : une matière première n'a pas de pays clair.
        assert valuation.country_for("Matières premières", "GC=F") == valuation.UNDEFINED_LABEL
        # Un futur ticker matière première non mappé retombe sur Non défini,
        # pas une exception (voir le commentaire de _COMMODITY_SECTORS).
        assert valuation.sector_for("Matières premières", "XX=F") == valuation.UNDEFINED_LABEL
    finally:
        md.get_company_profile = original
    assert calls == [], "Matières premières ne doivent jamais déclencher d'appel yfinance pour le secteur"
    print("OK: matières premières -> Énergie/Métaux précieux (mapping fixe), sans appel API")


def test_sector_and_country_for_equity_use_real_profile():
    original = md.get_company_profile
    md.get_company_profile = _fake_profile(sector="Technology", country="United States")
    try:
        assert valuation.sector_for("Actions", "AAPL") == "Technology"
        assert valuation.country_for("Actions", "AAPL") == "United States"
    finally:
        md.get_company_profile = original
    print("OK: Actions -> secteur/pays réels via get_company_profile")


def test_sector_and_country_for_equity_fallback_to_undefined_on_missing_field():
    """Le cas explicitement demandé par Edgar : une action qui DEVRAIT avoir
    un secteur/pays, mais dont le champ yfinance revient vide (API en panne
    ponctuelle, ticker mal renseigné...) — bascule automatique en
    "Non défini", jamais un trou dans le camembert ni une exception."""
    original = md.get_company_profile
    md.get_company_profile = _fake_profile(sector=None, country=None)
    try:
        assert valuation.sector_for("Actions", "GLITCHY") == valuation.UNDEFINED_LABEL
        assert valuation.country_for("Actions", "GLITCHY") == valuation.UNDEFINED_LABEL
        assert valuation.sector_for("Indices/ETF", "GLITCHY") == valuation.UNDEFINED_LABEL
        assert valuation.sector_for("Obligations", "TLT") == valuation.UNDEFINED_LABEL
    finally:
        md.get_company_profile = original
    print("OK: champ yfinance vide pour une action/ETF/obligation -> Non défini, sans planter")


def _snapshot(ticker, category, margin_eur, side="long", quantity=1.0, avg_price_eur=100.0):
    return {
        "position": Position(
            ticker=ticker, name=ticker, quantity=quantity, avg_price_eur=avg_price_eur,
            currency="USD", entry_date="2026-01-01", side=side, margin_eur=margin_eur,
        ),
        "category": category,
    }


class _FakePortfolio:
    def __init__(self, cash):
        self.cash = cash


def test_allocation_by_sector_mixes_real_and_undefined_without_crashing():
    """Bout-en-bout façon _render_diversification : un portefeuille avec une
    action dont le profil lève une exception inattendue (repli Non défini),
    une action valide, et une crypto (FinTech fixe) — le calcul complet ne
    doit jamais lever, et "Non défini" doit récupérer la part de la
    position en échec."""
    original = md.get_company_profile

    def fake(ticker):
        if ticker == "BROKEN":
            # Simule une défaillance inattendue qui échappe même au filet de
            # get_company_profile (voir le try/except ajouté dans sector_for/
            # country_for spécifiquement pour ce cas) — pas juste un champ vide.
            raise RuntimeError("panne réseau simulée")
        if ticker == "AAPL":
            return {"sector": "Technology", "country": "United States"}
        return {"sector": None, "country": None}  # simule un champ vide, pas une exception

    md.get_company_profile = fake
    try:
        portfolio = _FakePortfolio(cash=0.0)
        snapshots = [
            _snapshot("AAPL", "Actions", margin_eur=100.0),
            _snapshot("BROKEN", "Actions", margin_eur=100.0),  # exception -> Non défini
            _snapshot("BTC-USD", "Crypto", margin_eur=100.0),
        ]
        by_sector = ui_portfolio._allocation_by_sector(portfolio, snapshots)
        by_geo = ui_portfolio._allocation_by_geography(portfolio, snapshots)
    finally:
        md.get_company_profile = original

    assert abs(by_sector["Technology"] - 33.333) < 0.01
    assert abs(by_sector[valuation.UNDEFINED_LABEL] - 33.333) < 0.01
    assert abs(by_sector["FinTech"] - 33.333) < 0.01
    assert abs(sum(by_sector.values()) - 100.0) < 0.01

    assert abs(by_geo["United States"] - 33.333) < 0.01
    # BROKEN (exception) ET BTC-USD (Crypto, jamais de géographie) tombent
    # tous les deux dans "Non défini" -> leurs parts s'additionnent.
    assert abs(by_geo[valuation.UNDEFINED_LABEL] - 66.667) < 0.01
    print("OK: répartition secteur/géographie mixte (réel + Non défini) calculée sans exception")


if __name__ == "__main__":
    test_get_company_profile_never_raises_on_api_error()
    test_get_company_profile_treats_missing_or_empty_fields_as_none()
    test_sector_for_crypto_is_fintech_without_api_call()
    test_sector_and_country_for_forex_are_undefined_without_api_call()
    test_sector_for_commodities_uses_fixed_mapping_without_api_call()
    test_sector_and_country_for_equity_use_real_profile()
    test_sector_and_country_for_equity_fallback_to_undefined_on_missing_field()
    test_allocation_by_sector_mixes_real_and_undefined_without_crashing()
    print("\nTOUS LES TESTS diversification SONT PASSES.")
