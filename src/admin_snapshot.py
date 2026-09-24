"""Collecte périodique des données nécessaires à la page Admin News.

Ce module est appelé par le workflow TP/SL existant. La page Streamlit lit
uniquement les tables produites ici et ne contacte jamais les API de marché.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import market_data as md, portfolio_repo, valuation
from .db_models import MarketPriceSnapshotRow, PortfolioRow, PortfolioValueSnapshotRow

TRACKED_ASSETS = {
    "^FCHI": ("CAC 40", "Indices"), "^GDAXI": ("DAX", "Indices"),
    "^GSPC": ("S&P 500", "Indices"), "^IXIC": ("Nasdaq", "Indices"),
    "^N225": ("Nikkei 225", "Indices"),
    "AAPL": ("Apple", "Actions"), "MSFT": ("Microsoft", "Actions"),
    "NVDA": ("Nvidia", "Actions"), "GOOGL": ("Alphabet", "Actions"),
    "AMZN": ("Amazon", "Actions"),
    "BTC-USD": ("Bitcoin", "Crypto"), "ETH-USD": ("Ethereum", "Crypto"),
    "SOL-USD": ("Solana", "Crypto"), "XRP-USD": ("XRP", "Crypto"),
    "EURUSD=X": ("EUR/USD", "Forex"), "GBPUSD=X": ("GBP/USD", "Forex"),
    "USDJPY=X": ("USD/JPY", "Forex"), "USDCHF=X": ("USD/CHF", "Forex"),
    "AUDUSD=X": ("AUD/USD", "Forex"),
    "GC=F": ("Or", "Matières premières"), "SI=F": ("Argent", "Matières premières"),
    "CL=F": ("Pétrole WTI", "Matières premières"), "BZ=F": ("Pétrole Brent", "Matières premières"),
    "NG=F": ("Gaz naturel", "Matières premières"),
    "TLT": ("Treasury 20+ ans", "Obligations"), "IEF": ("Treasury 7-10 ans", "Obligations"),
    "BND": ("Obligations US", "Obligations"), "AGG": ("Obligations US agrégées", "Obligations"),
    "SHY": ("Treasury 1-3 ans", "Obligations"),
}


# Le tableau Admin News compare des prix sur 8 jours : un point par heure
# suffit largement. Le workflow peut tourner bien plus souvent (TP/SL,
# liquidation) : ce script se contente alors de ne rien faire.
SNAPSHOT_MIN_INTERVAL = timedelta(minutes=55)


def _fetch_prices(tickers: set[str]) -> dict[str, float]:
    """Prix en euros via le batch (market_data.get_quotes_batch) : réutilise
    les prix de moins de 5 min déjà en base (obtenus par l'app), n'appelle
    Yahoo que pour les autres, s'arrête au premier 429 et respecte le
    coupe-circuit partagé — au lieu de 29+ requêtes individuelles en
    parallèle. Un prix daté (stale) n'est JAMAIS enregistré comme snapshot."""
    quotes = md.get_quotes_batch(tuple(sorted(tickers)))
    prices = {}
    for ticker, quote in quotes.items():
        if quote.get("stale"):
            continue
        try:
            prices[ticker] = quote["price"] * md.get_fx_rate_to_eur(quote["currency"])
        except md.MarketDataError as error:
            print(f"Taux de change indisponible pour {ticker}: {error}")
    return prices


def record_snapshots(session: Session) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    last_recorded = session.execute(select(func.max(MarketPriceSnapshotRow.recorded_at))).scalar()
    if last_recorded and last_recorded >= (now - SNAPSHOT_MIN_INTERVAL).isoformat():
        print(f"Dernier snapshot à {last_recorded} : moins de 55 min, rien à faire ce run.")
        return 0, 0
    official_rows = session.execute(
        select(PortfolioRow).where(PortfolioRow.is_official.is_(True))
    ).scalars().all()
    tracked = set(TRACKED_ASSETS)
    for portfolio_row in official_rows:
        portfolio = portfolio_repo.load_portfolio(session, portfolio_row.id)
        if portfolio:
            tracked.update(portfolio.positions)

    fetched_prices = _fetch_prices(tracked)
    if not fetched_prices:
        # Source en pause : aucun snapshot plutôt qu'une série de portefeuilles
        # tous valorisés au prix moyen d'achat (données trompeuses).
        print("Aucun prix frais disponible (source en pause ?) : snapshots reportés au prochain run.")
        return 0, 0
    valuation_prices = dict(fetched_prices)
    # Une cotation indisponible ne doit pas provoquer un second appel caché
    # dans valuation.total_value : le portefeuille est alors valorisé au prix
    # moyen pour ce seul ticker, avec un snapshot explicitement approximatif.
    for portfolio_row in official_rows:
        portfolio = portfolio_repo.load_portfolio(session, portfolio_row.id)
        if portfolio:
            for ticker, position in portfolio.positions.items():
                valuation_prices.setdefault(ticker, position.avg_price_eur)

    for ticker, price_eur in fetched_prices.items():
        name, category = TRACKED_ASSETS.get(ticker, (ticker, "Autres"))
        session.add(MarketPriceSnapshotRow(
            ticker=ticker, name=name, category=category,
            recorded_at=now_iso, price_eur=price_eur,
        ))

    portfolio_count = 0
    for portfolio_row in official_rows:
        portfolio = portfolio_repo.load_portfolio(session, portfolio_row.id)
        if portfolio is None:
            continue
        value_eur, _ = valuation.total_value(portfolio, valuation_prices)
        session.add(PortfolioValueSnapshotRow(
            portfolio_id=portfolio.id, user_id=portfolio_row.user_id,
            recorded_at=now_iso, value_eur=value_eur,
        ))
        portfolio_count += 1

    session.commit()
    return len(fetched_prices), portfolio_count