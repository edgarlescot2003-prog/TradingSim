"""Persistance des portefeuilles dans PostgreSQL (Supabase).

Stratégie volontairement simple, adaptée au volume de données de cette
application (quelques portefeuilles, positions et trades par utilisateur) :
à chaque sauvegarde, les lignes filles d'un portefeuille (positions, trades,
ordres en attente, courbe de valeur) sont entièrement remplacées
(delete + insert) plutôt que diffées finement.

Le modèle en mémoire (dataclasses Portfolio/Position/Trade/PendingOrder dans
portfolio.py) ne change pas : seule cette couche de persistance a été
réécrite (JSON -> PostgreSQL), toute la logique métier qui manipule un
Portfolio (achat/vente/levier/ordres...) reste inchangée.
"""

import streamlit as st
from sqlalchemy import select

from . import db
from .db_models import PendingOrderRow, PortfolioRow, PositionRow, TradeRow, ValueHistoryRow
from .portfolio import PendingOrder, Portfolio, Position, Trade


def _current_user_id() -> str:
    """Utilisateur propriétaire des données pour la session en cours. Lu
    depuis st.session_state (posé par app.py au démarrage) plutôt que passé
    en paramètre partout : ça deviendra l'utilisateur connecté une fois
    l'authentification branchée (phase suivante), sans changer cette API.
    """
    return st.session_state.user_id


def _portfolio_from_rows(prow, positions, trades, orders, value_history) -> Portfolio:
    return Portfolio(
        id=prow.id,
        name=prow.name,
        initial_capital=prow.initial_capital,
        cash=prow.cash,
        created_at=prow.created_at,
        positions={p.ticker: Position(
            ticker=p.ticker, name=p.name, quantity=p.quantity, avg_price_eur=p.avg_price_eur,
            currency=p.currency, entry_date=p.entry_date, side=p.side, margin_eur=p.margin_eur,
        ) for p in positions},
        history=[Trade(
            date=t.date, ticker=t.ticker, name=t.name, side=t.side, action=t.action,
            quantity=t.quantity, price_eur=t.price_eur, currency=t.currency,
            leverage=t.leverage, realized_pnl_eur=t.realized_pnl_eur,
        ) for t in trades],
        pending_orders=[PendingOrder(
            id=o.id, ticker=o.ticker, name=o.name, action=o.action, quantity=o.quantity,
            limit_price_eur=o.limit_price_eur, currency=o.currency, leverage=o.leverage,
            created_at=o.created_at, last_checked_at=o.last_checked_at,
        ) for o in orders],
        value_history=[{"date": v.date, "value_eur": v.value_eur} for v in value_history],
    )


def load_all() -> tuple[dict[str, Portfolio], str | None]:
    """Charge tous les portefeuilles de l'utilisateur courant. Retourne
    ({}, None) s'il n'en a aucun, sinon (portefeuilles, id du premier
    trouvé) — le portefeuille "actif" n'est qu'un choix d'affichage gardé
    en session, pas une donnée persistée.
    """
    user_id = _current_user_id()
    with db.get_session() as session:
        prows = session.execute(
            select(PortfolioRow).where(PortfolioRow.user_id == user_id).order_by(PortfolioRow.created_at)
        ).scalars().all()

        portfolios = {}
        for prow in prows:
            positions = session.execute(
                select(PositionRow).where(PositionRow.portfolio_id == prow.id)
            ).scalars().all()
            trades = session.execute(
                select(TradeRow).where(TradeRow.portfolio_id == prow.id).order_by(TradeRow.date)
            ).scalars().all()
            orders = session.execute(
                select(PendingOrderRow).where(PendingOrderRow.portfolio_id == prow.id)
            ).scalars().all()
            value_history = session.execute(
                select(ValueHistoryRow).where(ValueHistoryRow.portfolio_id == prow.id)
                .order_by(ValueHistoryRow.date)
            ).scalars().all()
            portfolios[prow.id] = _portfolio_from_rows(prow, positions, trades, orders, value_history)

    active_id = next(iter(portfolios), None)
    return portfolios, active_id


def save_portfolio(portfolio: Portfolio) -> None:
    """Sauvegarde (création ou mise à jour complète) un portefeuille, pour
    l'utilisateur courant."""
    user_id = _current_user_id()
    with db.get_session() as session:
        prow = session.get(PortfolioRow, portfolio.id)
        if prow is None:
            session.add(PortfolioRow(
                id=portfolio.id, user_id=user_id, name=portfolio.name,
                initial_capital=portfolio.initial_capital, cash=portfolio.cash,
                created_at=portfolio.created_at,
            ))
        else:
            prow.name = portfolio.name
            prow.cash = portfolio.cash
            prow.initial_capital = portfolio.initial_capital

        session.query(PositionRow).filter_by(portfolio_id=portfolio.id).delete()
        session.query(TradeRow).filter_by(portfolio_id=portfolio.id).delete()
        session.query(PendingOrderRow).filter_by(portfolio_id=portfolio.id).delete()
        session.query(ValueHistoryRow).filter_by(portfolio_id=portfolio.id).delete()

        for pos in portfolio.positions.values():
            session.add(PositionRow(
                portfolio_id=portfolio.id, user_id=user_id, ticker=pos.ticker, name=pos.name,
                quantity=pos.quantity, avg_price_eur=pos.avg_price_eur, currency=pos.currency,
                entry_date=pos.entry_date, side=pos.side, margin_eur=pos.margin_eur,
            ))
        for t in portfolio.history:
            session.add(TradeRow(
                portfolio_id=portfolio.id, user_id=user_id, date=t.date, ticker=t.ticker, name=t.name,
                side=t.side, action=t.action, quantity=t.quantity, price_eur=t.price_eur,
                currency=t.currency, leverage=t.leverage, realized_pnl_eur=t.realized_pnl_eur,
            ))
        for o in portfolio.pending_orders:
            session.add(PendingOrderRow(
                id=o.id, portfolio_id=portfolio.id, user_id=user_id, ticker=o.ticker, name=o.name,
                action=o.action, quantity=o.quantity, limit_price_eur=o.limit_price_eur,
                currency=o.currency, leverage=o.leverage, created_at=o.created_at,
                last_checked_at=o.last_checked_at,
            ))
        for v in portfolio.value_history:
            session.add(ValueHistoryRow(
                portfolio_id=portfolio.id, user_id=user_id, date=v["date"], value_eur=v["value_eur"],
            ))

        session.commit()
