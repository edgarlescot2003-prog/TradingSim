"""Paliers Take Profit / Stop Loss : création, annulation, consultation.

SANS dépendance à Streamlit — utilisé à la fois par l'UI (ui_trading.py,
qui ouvre sa propre session via db.get_session()) et par le cron
d'exécution (scripts/check_tp_sl.py, qui ouvre la sienne via
db_core.create_engine_from_env()). L'exécution proprement dite (vente/rachat
au déclenchement) vit dans scripts/check_tp_sl.py, pas ici : ce module ne
fait que gérer le CYCLE DE VIE des paliers (créer/lister/annuler), jamais de
trade.

Validation volontairement minimale à la création (quantité en %, prix
positif) : l'utilisateur garde le contrôle total sur le prix cible et peut
très bien poser un palier qui semble "à l'envers" par rapport au prix
courant (ex : un stop loss au-dessus du prix actuel) — ce n'est pas ce
module qui en juge, seule sa cohérence LOGIQUE (side + kind + quantité) est
vérifiée.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import TpSlOrderRow
from .portfolio import Position

KIND_TAKE_PROFIT = "take_profit"
KIND_STOP_LOSS = "stop_loss"
KINDS = (KIND_TAKE_PROFIT, KIND_STOP_LOSS)

STATUS_ACTIVE = "active"
STATUS_EXECUTED = "executed"
STATUS_CANCELLED = "cancelled"

KIND_LABELS = {KIND_TAKE_PROFIT: "Take Profit", KIND_STOP_LOSS: "Stop Loss"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_tp_sl(
    session: Session, portfolio_id: str, user_id: str, position: Position,
    kind: str, target_price_eur: float, quantity_pct: float,
) -> TpSlOrderRow:
    """Crée un nouveau palier sur `position` (position TELLE QU'ELLE EST
    MAINTENANT — sa `quantity` actuelle devient la base "initiale" figée de
    CE palier, voir TpSlOrderRow). `quantity_pct` en % (0 exclu, 100 max).
    """
    if kind not in KINDS:
        raise ValueError(f"Type de palier inconnu : {kind}")
    if not (0 < quantity_pct <= 100):
        raise ValueError("Le pourcentage doit être compris entre 0 (exclu) et 100.")
    if target_price_eur <= 0:
        raise ValueError("Le prix cible doit être supérieur à 0.")
    if position.quantity <= 0:
        raise ValueError("Aucune position sur laquelle poser un palier.")

    row = TpSlOrderRow(
        portfolio_id=portfolio_id, user_id=user_id, ticker=position.ticker, name=position.name,
        currency=position.currency, side=position.side, kind=kind,
        target_price_eur=target_price_eur, quantity_pct=quantity_pct,
        initial_quantity=position.quantity,
        trigger_quantity=position.quantity * quantity_pct / 100,
        status=STATUS_ACTIVE, created_at=_now_iso(),
    )
    session.add(row)
    session.commit()
    return row


def cancel_tp_sl(session: Session, tp_sl_id: str, user_id: str) -> bool:
    """Annule un palier encore actif appartenant à `user_id`. Retourne False
    (sans erreur) s'il est introuvable, déjà exécuté/annulé, ou n'appartient
    pas à cet utilisateur — jamais d'exception pour un simple clic en double."""
    row = session.get(TpSlOrderRow, tp_sl_id)
    if row is None or row.user_id != user_id or row.status != STATUS_ACTIVE:
        return False
    row.status = STATUS_CANCELLED
    row.executed_at = _now_iso()
    session.commit()
    return True


def list_for_portfolio(session: Session, portfolio_id: str, statuses: tuple[str, ...] | None = None) -> list[TpSlOrderRow]:
    """Paliers d'un portefeuille, du plus récent au plus ancien. `statuses`
    restreint aux statuts donnés (par défaut : tous)."""
    query = select(TpSlOrderRow).where(TpSlOrderRow.portfolio_id == portfolio_id)
    if statuses:
        query = query.where(TpSlOrderRow.status.in_(statuses))
    query = query.order_by(TpSlOrderRow.created_at.desc())
    return session.execute(query).scalars().all()
