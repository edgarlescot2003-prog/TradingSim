"""Classement multi-utilisateurs : qui a le meilleur P&L.

Revalue TOUS les portefeuilles de TOUS les utilisateurs en direct (prix de
marché courants) à chaque consultation — pas seulement celui de la personne
connectée. Assumé correct pour un petit nombre de comptes ; un cache de prix
partagé entre portefeuilles évite de refaire le même appel API si plusieurs
personnes détiennent le même actif. À revoir (ex : repli sur la dernière
valeur connue comme avant) si le nombre de comptes/positions grossit au
point de rendre le chargement du classement trop lent.

Un utilisateur avec plusieurs portefeuilles est classé sur la somme de tous
(capital de départ total vs valeur totale actuelle) — plus juste qu'un seul
de ses portefeuilles, qui pourrait masquer des pertes ailleurs.
"""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from . import db, valuation
from . import market_data as md
from .db_models import PortfolioRow, PositionRow, User
from .portfolio import Portfolio, Position


def _load_portfolio(session, prow: PortfolioRow) -> Portfolio:
    position_rows = session.execute(
        select(PositionRow).where(PositionRow.portfolio_id == prow.id)
    ).scalars().all()
    positions = {
        r.ticker: Position(
            ticker=r.ticker, name=r.name, quantity=r.quantity, avg_price_eur=r.avg_price_eur,
            currency=r.currency, entry_date=r.entry_date, side=r.side, margin_eur=r.margin_eur,
        ) for r in position_rows
    }
    return Portfolio(
        id=prow.id, name=prow.name, initial_capital=prow.initial_capital,
        cash=prow.cash, positions=positions,
    )


def _fetch_price_eur(ticker: str) -> tuple[str, float | None]:
    try:
        quote = md.get_quote(ticker)
        return ticker, md.convert_to_eur(quote["price"], quote["currency"])
    except md.MarketDataError:
        return ticker, None


def compute_rankings() -> list[dict]:
    """Un P&L par utilisateur (agrégé sur tous ses portefeuilles, valorisés
    en direct), trié du meilleur au moins bon. Chaque entrée : user_id,
    username, n_portfolios, initial_capital, current_value, pnl_eur, pnl_pct.
    """
    with db.get_session() as session:
        usernames = {u.id: u.username for u in session.execute(select(User)).scalars().all()}
        portfolio_rows = session.execute(select(PortfolioRow)).scalars().all()
        # Les positions sont chargées ici (session ouverte) ; la valorisation
        # en direct (appels réseau vers yfinance/Kraken) se fait après avoir
        # refermé la session, pour ne pas garder une connexion DB ouverte
        # pendant qu'on attend les API de marché.
        loaded = [(prow, _load_portfolio(session, prow)) for prow in portfolio_rows]

    # Un même ticker peut apparaître chez plusieurs utilisateurs : on
    # récupère chaque prix une seule fois, en parallèle (appels réseau
    # indépendants) plutôt que portefeuille par portefeuille en série —
    # c'est ce qui faisait l'essentiel du temps de chargement du classement.
    unique_tickers = {pos.ticker for _, portfolio in loaded for pos in portfolio.positions.values()}
    price_cache: dict[str, float] = {}
    if unique_tickers:
        with ThreadPoolExecutor(max_workers=min(8, len(unique_tickers))) as executor:
            for ticker, price_eur in executor.map(_fetch_price_eur, unique_tickers):
                if price_eur is not None:
                    price_cache[ticker] = price_eur

    totals: dict[str, dict] = {}
    for prow, portfolio in loaded:
        current_value, _ = valuation.total_value(portfolio, price_cache)
        entry = totals.setdefault(prow.user_id, {
            "username": usernames.get(prow.user_id, "(compte supprimé)"),
            "initial_capital": 0.0,
            "current_value": 0.0,
            "n_portfolios": 0,
        })
        entry["initial_capital"] += prow.initial_capital
        entry["current_value"] += current_value
        entry["n_portfolios"] += 1

    rankings = []
    for user_id, data in totals.items():
        pnl_eur = data["current_value"] - data["initial_capital"]
        pnl_pct = (pnl_eur / data["initial_capital"] * 100) if data["initial_capital"] else 0.0
        rankings.append({"user_id": user_id, **data, "pnl_eur": pnl_eur, "pnl_pct": pnl_pct})

    rankings.sort(key=lambda r: r["pnl_eur"], reverse=True)
    return rankings
