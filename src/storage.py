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

import uuid

import streamlit as st
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import db
from .db_models import PendingOrderRow, PortfolioRow, PositionRow, TradeRow, User, ValueHistoryRow
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

        session.query(PositionRow).filter_by(portfolio_id=portfolio.id).delete(synchronize_session=False)
        session.query(TradeRow).filter_by(portfolio_id=portfolio.id).delete(synchronize_session=False)
        session.query(PendingOrderRow).filter_by(portfolio_id=portfolio.id).delete(synchronize_session=False)
        session.query(ValueHistoryRow).filter_by(portfolio_id=portfolio.id).delete(synchronize_session=False)

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
        # dédoublonne par date avant insertion : la contrainte unique porte sur
        # (portfolio_id, date) exact, et le value_history en mémoire peut
        # contenir deux fois la même date (voir plus bas).
        deduped_history = {v["date"]: v["value_eur"] for v in portfolio.value_history}
        if deduped_history:
            # INSERT ... ON CONFLICT DO UPDATE plutôt qu'un simple insert :
            # deux requêtes quasi simultanées sur le même portefeuille (deux
            # onglets ouverts, ou un double rerun réseau) peuvent chacune
            # recalculer un point du jour avec un timestamp identique si
            # l'horloge du conteneur n'a pas encore avancé entre les deux
            # appels — la 2ᵉ tentait alors un INSERT en double juste après
            # avoir supprimé les lignes existantes, ce qui violait la
            # contrainte unique et faisait échouer TOUTE la sauvegarde
            # (positions/trades compris), pas seulement la courbe de valeur.
            # Avec upsert, la 2ᵉ requête écrase simplement la valeur au lieu
            # d'échouer.
            stmt = pg_insert(ValueHistoryRow).values([
                {
                    "id": str(uuid.uuid4()), "portfolio_id": portfolio.id, "user_id": user_id,
                    "date": date, "value_eur": value_eur,
                }
                for date, value_eur in deduped_history.items()
            ])
            stmt = stmt.on_conflict_do_update(
                constraint="uq_value_history_portfolio_date",
                set_={"value_eur": stmt.excluded.value_eur},
            )
            session.execute(stmt)

        session.commit()


def delete_portfolio(portfolio_id: str) -> None:
    """Supprime définitivement un portefeuille et toutes ses données
    (positions, historique des trades, ordres en attente, courbe de valeur).

    Scopé à l'utilisateur courant (`_current_user_id()`), comme le reste de
    ce module : un portefeuille qui n'appartient pas à l'utilisateur connecté
    est silencieusement ignoré plutôt que supprimé, pour ne jamais permettre
    à un compte de supprimer les données d'un autre.
    """
    user_id = _current_user_id()
    with db.get_session() as session:
        prow = session.get(PortfolioRow, portfolio_id)
        if prow is None or prow.user_id != user_id:
            return

        # users.active_portfolio_id a une contrainte de clé étrangère vers
        # portfolios.id : si ce portefeuille est l'actif enregistré, il faut
        # la lever avant de supprimer, sinon la suppression échoue (violation
        # de contrainte) — même précaution que dans auth.delete_user.
        user = session.get(User, user_id)
        if user is not None and user.active_portfolio_id == portfolio_id:
            user.active_portfolio_id = None
            session.flush()

        for model in (PositionRow, TradeRow, PendingOrderRow, ValueHistoryRow):
            session.query(model).filter_by(portfolio_id=portfolio_id).delete(synchronize_session=False)
        session.delete(prow)
        session.commit()
