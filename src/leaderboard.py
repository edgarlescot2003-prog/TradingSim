"""Classement multi-utilisateurs : qui a le meilleur P&L.

Revalue en direct (prix de marché courants) le portefeuille OFFICIEL de
chaque utilisateur à chaque consultation — pas les autres. Depuis
l'introduction du statut "portefeuille officiel" (un seul par utilisateur,
désigné une fois pour toutes, voir auth.set_official_portfolio), un
utilisateur peut avoir plusieurs portefeuilles "fun/test" en parallèle :
seul celui marqué officiel compte pour le classement, les autres en sont
totalement exclus (même actifs, même avec des gains). Un utilisateur sans
portefeuille officiel désigné (compte pas encore migré) n'apparaît pas du
tout dans le classement plutôt que d'y figurer sur un choix arbitraire.

Un cache de prix partagé entre utilisateurs évite de refaire le même appel
API si plusieurs personnes détiennent le même actif. Assumé correct pour un
petit nombre de comptes ; à revoir (ex : repli sur la dernière valeur connue)
si le nombre de comptes/positions grossit au point de rendre le chargement
du classement trop lent.
"""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from . import db, valuation
from . import market_data as md
from .db_models import PortfolioRow, PositionRow, User, ValueHistoryRow
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
        # Affichage uniquement : dernier prix connu si la source est en pause.
        quote = md.get_quote(ticker, allow_stale=True)
        return ticker, md.convert_to_eur(quote["price"], quote["currency"], allow_stale=True)
    except md.MarketDataError:
        return ticker, None


def compute_rankings() -> list[dict]:
    """Un P&L par utilisateur, calculé sur son seul portefeuille officiel
    (valorisé en direct), trié du meilleur au moins bon. Chaque entrée :
    user_id, username, initial_capital, current_value, pnl_eur, pnl_pct.
    Un utilisateur sans portefeuille officiel désigné n'apparaît pas.
    """
    with db.get_session() as session:
        usernames = {u.id: u.username for u in session.execute(select(User)).scalars().all()}
        portfolio_rows = session.execute(
            select(PortfolioRow).where(PortfolioRow.is_official.is_(True))
        ).scalars().all()
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

    rankings = []
    for prow, portfolio in loaded:
        current_value, _ = valuation.total_value(portfolio, price_cache)
        pnl_eur = current_value - prow.initial_capital
        pnl_pct = (pnl_eur / prow.initial_capital * 100) if prow.initial_capital else 0.0
        rankings.append({
            "user_id": prow.user_id,
            "username": usernames.get(prow.user_id, "(compte supprimé)"),
            "initial_capital": prow.initial_capital,
            "current_value": current_value,
            "pnl_eur": pnl_eur,
            "pnl_pct": pnl_pct,
        })

    rankings.sort(key=lambda r: r["pnl_eur"], reverse=True)
    return rankings


def list_official_portfolios(exclude_user_id: str | None = None) -> list[dict]:
    """Identité des portefeuilles officiels de tous les utilisateurs (pas de
    valorisation, pas d'appel réseau) : pour peupler un sélecteur, voir la
    comparaison à un participant sur la page Portefeuille
    (ui_portfolio._render_performance). `exclude_user_id` : exclut ce compte
    (typiquement l'utilisateur courant — comparer son propre portefeuille
    officiel à lui-même n'aurait pas de sens)."""
    with db.get_session() as session:
        usernames = {u.id: u.username for u in session.execute(select(User)).scalars().all()}
        rows = session.execute(
            select(PortfolioRow).where(PortfolioRow.is_official.is_(True))
        ).scalars().all()

    result = [
        {
            "user_id": r.user_id,
            "username": usernames.get(r.user_id, "(compte supprimé)"),
            "portfolio_id": r.id,
            "portfolio_name": r.name,
        }
        for r in rows if r.user_id != exclude_user_id
    ]
    result.sort(key=lambda r: r["username"].lower())
    return result


def get_value_history(portfolio_id: str) -> list[dict]:
    """value_history brut d'UN portefeuille, quel qu'en soit le
    propriétaire, sans charger positions/trades/ordres (voir
    portfolio_repo.load_portfolio pour un chargement complet) — utilisé pour
    la comparaison à un participant (voir benchmark.build_participant_
    comparison), plus léger qu'un chargement complet quand seule la courbe
    de valeur est nécessaire."""
    with db.get_session() as session:
        rows = session.execute(
            select(ValueHistoryRow)
            .where(ValueHistoryRow.portfolio_id == portfolio_id)
            .order_by(ValueHistoryRow.date)
        ).scalars().all()
    return [{"date": r.date, "value_eur": r.value_eur} for r in rows]
