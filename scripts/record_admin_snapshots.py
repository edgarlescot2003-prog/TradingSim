"""Enregistre les snapshots du tableau Admin News.

Ce script est exécuté par le workflow TP/SL existant toutes les 15 minutes.
Il contacte les API uniquement ici, jamais au rendu de la page Admin.
"""

from sqlalchemy.orm import Session

from src import admin_snapshot, db_core


def run() -> None:
    engine = db_core.create_engine_from_env()
    db_core.ensure_schema(engine)
    with Session(engine) as session:
        prices, portfolios = admin_snapshot.record_snapshots(session)
    print(f"Snapshots Admin News: {prices} prix, {portfolios} portefeuilles officiels.")


if __name__ == "__main__":
    run()