"""Persistance des portefeuilles dans PostgreSQL (Supabase), pour l'app
Streamlit — scope l'utilisateur courant depuis `st.session_state.user_id`.

Toute la logique de chargement/sauvegarde (positions/trades/ordres/courbe de
valeur, SANS dépendance à Streamlit) vit dans `src/portfolio_repo.py`,
réutilisée aussi par les scripts/crons indépendants de l'app (ex :
scripts/check_tp_sl.py) qui opèrent sur un `portfolio_id` explicite plutôt
que sur "l'utilisateur de la session courante".
"""

import streamlit as st
from sqlalchemy import select

from . import db, portfolio_repo
from .db_models import PortfolioRow, PositionRow, TradeRow, PendingOrderRow, TpSlOrderRow, User, ValueHistoryRow
from .portfolio import Portfolio


def _current_user_id() -> str:
    """Utilisateur propriétaire des données pour la session en cours. Lu
    depuis st.session_state (posé par app.py au démarrage) plutôt que passé
    en paramètre partout : ça deviendra l'utilisateur connecté une fois
    l'authentification branchée (phase suivante), sans changer cette API.
    """
    return st.session_state.user_id


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
        portfolios = {prow.id: portfolio_repo.load_portfolio(session, prow.id) for prow in prows}

    active_id = next(iter(portfolios), None)
    return portfolios, active_id


def save_portfolio(portfolio: Portfolio) -> None:
    """Sauvegarde (création ou mise à jour complète) un portefeuille, pour
    l'utilisateur courant."""
    user_id = _current_user_id()
    with db.get_session() as session:
        portfolio_repo.save_portfolio(session, portfolio, user_id)


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
        if prow.is_official:
            # Filet de sécurité : l'UI bloque déjà ce bouton, mais le statut
            # officiel doit rester non contournable même par un futur appel
            # direct à cette fonction.
            raise ValueError("Le portefeuille officiel ne peut pas être supprimé.")

        # users.active_portfolio_id a une contrainte de clé étrangère vers
        # portfolios.id : si ce portefeuille est l'actif enregistré, il faut
        # la lever avant de supprimer, sinon la suppression échoue (violation
        # de contrainte) — même précaution que dans auth.delete_user.
        user = session.get(User, user_id)
        if user is not None and user.active_portfolio_id == portfolio_id:
            user.active_portfolio_id = None
            session.flush()

        # TradeRow avant TpSlOrderRow : trades.tp_sl_order_id référence
        # tp_sl_orders.id, il faut donc supprimer les trades d'abord.
        for model in (PositionRow, TradeRow, PendingOrderRow, ValueHistoryRow, TpSlOrderRow):
            session.query(model).filter_by(portfolio_id=portfolio_id).delete(synchronize_session=False)
        session.delete(prow)
        session.commit()
