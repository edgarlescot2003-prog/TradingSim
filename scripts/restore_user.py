"""Restaure un seul compte depuis une sauvegarde CSV.

Contrairement à restore_db.py, ce script ne touche pas aux autres comptes.
Les contenus partages (cours/news) ne sont pas rattaches automatiquement :
la suppression d'un compte les detache volontairement.
"""

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src import db_core
from src.db_models import (
    PendingOrderRow, PortfolioRow, PositionRow, SearchHistoryRow, TpSlOrderRow,
    TradeRow, User, ValueHistoryRow,
)

PORTFOLIO_TABLES = (
    (PositionRow, "positions"),
    (TradeRow, "trades"),
    (PendingOrderRow, "pending_orders"),
    (ValueHistoryRow, "value_history"),
    (TpSlOrderRow, "tp_sl_orders"),
)


def _rows(backup_dir: Path, filename: str, user_id: str) -> list[dict]:
    path = backup_dir / filename
    if path.suffix.lower() != ".csv":
        path = path.with_suffix(".csv")
    dataframe = pd.read_csv(path, keep_default_na=True)
    if "user_id" in dataframe.columns:
        dataframe = dataframe[dataframe["user_id"] == user_id]
    return dataframe.where(pd.notnull(dataframe), None).to_dict("records")


def _insert(session: Session, model, values: list[dict]) -> None:
    if values:
        session.bulk_insert_mappings(model, values)


def restore_user(backup_dir: Path, username: str) -> None:
    users = pd.read_csv(backup_dir / "users.csv", keep_default_na=True)
    selected = users[users["username"] == username]
    if len(selected) != 1:
        raise ValueError(f"Compte introuvable ou ambigu dans la sauvegarde : {username}")

    user_data = selected.iloc[0].where(pd.notna(selected.iloc[0]), None).to_dict()
    user_id = user_data["id"]
    active_id = user_data.get("active_portfolio_id")
    engine = db_core.create_engine_from_env()
    db_core.ensure_schema(engine)

    with Session(engine) as session:
        if session.get(User, user_id) is not None:
            raise ValueError(f"Le compte {username} existe deja dans la base actuelle.")
        if session.execute(select(User).where(User.username == username)).scalar_one_or_none() is not None:
            raise ValueError(f"Le nom de compte {username} est deja utilise dans la base actuelle.")

        user_data["active_portfolio_id"] = None
        _insert(session, User, [user_data])
        session.flush()

        portfolios = _rows(backup_dir, "portfolios.csv", user_id)
        _insert(session, PortfolioRow, portfolios)
        session.flush()

        for model, filename in PORTFOLIO_TABLES:
            _insert(session, model, _rows(backup_dir, filename, user_id))
        _insert(session, SearchHistoryRow, _rows(backup_dir, "search_history.csv", user_id))

        if active_id:
            session.get(User, user_id).active_portfolio_id = active_id
        session.commit()

    print(f"Compte restaure : {username} ({user_id})")
    print(f"Portefeuilles : {len(portfolios)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python -m scripts.restore_user backups/AAAA-MM-JJ nom_du_compte")
        raise SystemExit(1)
    restore_user(Path(sys.argv[1]), sys.argv[2])