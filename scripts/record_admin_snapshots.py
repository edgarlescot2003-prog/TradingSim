"""Enregistre les snapshots du tableau Admin News.

Ce script est exécuté par le workflow TP/SL existant (après TP/SL et
liquidation), mais n'enregistre au plus qu'un snapshot par heure (voir
admin_snapshot.SNAPSHOT_MIN_INTERVAL). Il contacte les API uniquement ici,
jamais au rendu de la page Admin.
"""

from sqlalchemy.orm import Session

from src import admin_snapshot, db_core, diag_log, market_store


def run() -> None:
    diag_log.log_process_start()
    engine = db_core.create_engine_from_env()
    db_core.ensure_schema(engine)
    market_store.configure(lambda: engine, scope="github")  # coupe-circuit propre à l'IP GitHub
    with Session(engine) as session:
        prices, portfolios = admin_snapshot.record_snapshots(session)
    print(f"Snapshots Admin News: {prices} prix, {portfolios} portefeuilles officiels.")


if __name__ == "__main__":
    run()