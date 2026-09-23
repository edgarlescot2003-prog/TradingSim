"""Chargement/sauvegarde d'UN portefeuille (dataclasses de portfolio.py)
depuis/vers Supabase, SANS dépendance à Streamlit.

Isolé de `storage.py` (qui ajoute le scoping sur l'utilisateur de la session
Streamlit courante, via `st.session_state.user_id`) pour que les scripts/
crons indépendants de l'app — qui n'ont pas de session Streamlit et opèrent
sur un `portfolio_id` explicite, potentiellement pour PLUSIEURS utilisateurs
différents dans une même exécution (ex : scripts/check_tp_sl.py, qui
vérifie les paliers de tous les portefeuilles à chaque passage) — puissent
réutiliser exactement la même logique de persistance que l'app, sans jamais
importer Streamlit.

Chaque appelant fournit sa propre `Session` SQLAlchemy déjà ouverte (via
`db.get_session()` côté app, ou `db_core.create_engine_from_env()` côté
script indépendant) : ce module ne gère lui-même aucune connexion.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .db_models import (
    PendingOrderRow, PortfolioRow, PositionRow, TradeRow, TpSlOrderRow, ValueHistoryRow,
)
from .portfolio import PendingOrder, Portfolio, Position, Trade


def portfolio_from_rows(prow, positions, trades, orders, value_history) -> Portfolio:
    return Portfolio(
        id=prow.id,
        name=prow.name,
        initial_capital=prow.initial_capital,
        cash=prow.cash,
        created_at=prow.created_at,
        is_official=prow.is_official,
        positions={p.ticker: Position(
            ticker=p.ticker, name=p.name, quantity=p.quantity, avg_price_eur=p.avg_price_eur,
            currency=p.currency, entry_date=p.entry_date, side=p.side, margin_eur=p.margin_eur,
        ) for p in positions},
        history=[Trade(
            date=t.date, ticker=t.ticker, name=t.name, side=t.side, action=t.action,
            quantity=t.quantity, price_eur=t.price_eur, currency=t.currency,
            leverage=t.leverage, realized_pnl_eur=t.realized_pnl_eur, tp_sl_order_id=t.tp_sl_order_id,
            is_liquidation=t.is_liquidation,
        ) for t in trades],
        pending_orders=[PendingOrder(
            id=o.id, ticker=o.ticker, name=o.name, action=o.action, quantity=o.quantity,
            limit_price_eur=o.limit_price_eur, currency=o.currency, leverage=o.leverage,
            created_at=o.created_at, last_checked_at=o.last_checked_at,
        ) for o in orders],
        value_history=[{"date": v.date, "value_eur": v.value_eur} for v in value_history],
    )


def load_portfolio(session: Session, portfolio_id: str) -> Portfolio | None:
    """Charge le portefeuille `portfolio_id` (positions/trades/ordres/courbe
    de valeur compris), quel que soit son propriétaire. None s'il n'existe
    pas (ou plus)."""
    prow = session.get(PortfolioRow, portfolio_id)
    if prow is None:
        return None

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
        select(ValueHistoryRow).where(ValueHistoryRow.portfolio_id == prow.id).order_by(ValueHistoryRow.date)
    ).scalars().all()
    return portfolio_from_rows(prow, positions, trades, orders, value_history)


def save_portfolio(session: Session, portfolio: Portfolio, user_id: str) -> None:
    """Sauvegarde (création ou mise à jour complète) `portfolio`, propriété
    de `user_id`, et commite. Chaque appel est donc sa propre transaction
    (un portefeuille à la fois) — un script qui sauvegarde plusieurs
    portefeuilles dans la même exécution (ex : scripts/check_tp_sl.py) fait
    donc autant de commits indépendants, pas une seule transaction globale.

    `with_for_update=True` verrouille la ligne `portfolios` (si elle existe
    déjà) jusqu'au commit de CETTE transaction : un second appel concurrent
    à `save_portfolio` sur le MÊME portefeuille (ex : une session utilisateur
    et le cron `check-tp-sl.yml`/`check_liquidation.py`, qui tournent toutes
    les 15 min sur tous les portefeuilles à paliers/positions leviées actifs
    — voir scripts/check_tp_sl.py, scripts/check_liquidation.py) attend que
    CETTE transaction se termine avant de commencer la sienne, au lieu de
    s'exécuter en parallèle. Nécessaire car ce qui suit fait un DELETE puis
    un ré-INSERT complet de positions/trades/pending_orders : sans ce verrou,
    deux sauvegardes entrelacées peuvent soit violer la contrainte unique de
    `positions` (portfolio_id, ticker) — le crash `IntegrityError` détecté au
    stress test de conditions réelles (prompt 11) —, soit pire, faire
    disparaître silencieusement des lignes fraîchement insérées par l'autre
    (le DELETE d'une transaction supprimant l'INSERT déjà commité de
    l'autre), sans qu'aucune erreur ne soit levée. Un simple upsert
    `ON CONFLICT` (voir value_history plus bas, qui a le même souci mais une
    contrainte unique dessus) ne suffit pas seul ici : `trades` et
    `pending_orders` n'ont pas de contrainte unique naturelle pour cibler un
    conflit, donc seul un verrou qui sérialise la transaction ENTIÈRE ferme
    la fenêtre de course pour les 4 tables à la fois.
    """
    prow = session.get(PortfolioRow, portfolio.id, with_for_update=True)
    if prow is None:
        session.add(PortfolioRow(
            id=portfolio.id, user_id=user_id, name=portfolio.name,
            initial_capital=portfolio.initial_capital, cash=portfolio.cash,
            created_at=portfolio.created_at, is_official=portfolio.is_official,
        ))
    else:
        prow.name = portfolio.name
        prow.cash = portfolio.cash
        prow.initial_capital = portfolio.initial_capital
        # is_official n'est JAMAIS réécrit ici, volontairement : ce statut
        # est définitif et ne doit pouvoir changer que via l'action dédiée
        # (auth.set_official_portfolio), jamais en passant par une simple
        # sauvegarde de portefeuille (achat, vente, palier TP/SL...).

    session.query(PositionRow).filter_by(portfolio_id=portfolio.id).delete(synchronize_session=False)
    session.query(TradeRow).filter_by(portfolio_id=portfolio.id).delete(synchronize_session=False)
    session.query(PendingOrderRow).filter_by(portfolio_id=portfolio.id).delete(synchronize_session=False)
    session.query(ValueHistoryRow).filter_by(portfolio_id=portfolio.id).delete(synchronize_session=False)

    # INSERT ... ON CONFLICT DO UPDATE (même idiome que value_history plus
    # bas) : `positions` porte une vraie contrainte unique (portfolio_id,
    # ticker), donc en plus du verrou ci-dessus (qui protège déjà cette
    # table), un upsert explicite évite aussi tout conflit résiduel si cette
    # fonction est un jour appelée hors du chemin verrouillé.
    if portfolio.positions:
        stmt = pg_insert(PositionRow).values([
            {
                "id": str(uuid.uuid4()), "portfolio_id": portfolio.id, "user_id": user_id,
                "ticker": pos.ticker, "name": pos.name, "quantity": pos.quantity,
                "avg_price_eur": pos.avg_price_eur, "currency": pos.currency,
                "entry_date": pos.entry_date, "side": pos.side, "margin_eur": pos.margin_eur,
            }
            for pos in portfolio.positions.values()
        ])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_position_portfolio_ticker",
            set_={
                "name": stmt.excluded.name, "quantity": stmt.excluded.quantity,
                "avg_price_eur": stmt.excluded.avg_price_eur, "currency": stmt.excluded.currency,
                "entry_date": stmt.excluded.entry_date, "side": stmt.excluded.side,
                "margin_eur": stmt.excluded.margin_eur,
            },
        )
        session.execute(stmt)
    for t in portfolio.history:
        session.add(TradeRow(
            portfolio_id=portfolio.id, user_id=user_id, date=t.date, ticker=t.ticker, name=t.name,
            side=t.side, action=t.action, quantity=t.quantity, price_eur=t.price_eur,
            currency=t.currency, leverage=t.leverage, realized_pnl_eur=t.realized_pnl_eur,
            tp_sl_order_id=t.tp_sl_order_id, is_liquidation=t.is_liquidation,
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
        # INSERT ... ON CONFLICT DO UPDATE plutôt qu'un simple insert : deux
        # sauvegardes quasi simultanées sur le même portefeuille (deux
        # onglets ouverts, le cron TP/SL et une session utilisateur en même
        # temps...) peuvent chacune recalculer un point du jour avec un
        # timestamp identique si l'horloge n'a pas encore avancé entre les
        # deux — la 2ᵉ tentait alors un INSERT en double juste après avoir
        # supprimé les lignes existantes, ce qui violait la contrainte
        # unique et faisait échouer TOUTE la sauvegarde (positions/trades
        # compris), pas seulement la courbe de valeur. Avec upsert, la 2ᵉ
        # requête écrase simplement la valeur au lieu d'échouer.
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


def reset_all_portfolios(session: Session, initial_capital: float = 10_000.0) -> int:
    """Remet tous les portefeuilles au capital fourni, sans position.

    Les comptes et le statut de portefeuille officiel sont conservés. Les
    données de trading associées sont supprimées dans une seule transaction.
    Retourne le nombre de portefeuilles réinitialisés.
    """
    portfolios = session.execute(
        select(PortfolioRow).with_for_update()
    ).scalars().all()
    portfolio_ids = [portfolio.id for portfolio in portfolios]

    if portfolio_ids:
        for model in (PositionRow, TradeRow, PendingOrderRow, ValueHistoryRow, TpSlOrderRow):
            session.query(model).filter(model.portfolio_id.in_(portfolio_ids)).delete(
                synchronize_session=False
            )
        session.query(PortfolioRow).filter(PortfolioRow.id.in_(portfolio_ids)).update(
            {PortfolioRow.initial_capital: initial_capital, PortfolioRow.cash: initial_capital},
            synchronize_session=False,
        )

    session.commit()
    return len(portfolios)
