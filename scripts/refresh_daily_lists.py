"""Pré-charge les prix indicatifs des listes Trading (asset_daily_snapshot).

Exécuté par le workflow check-tp-sl.yml (après TP/SL, liquidation et
snapshots Admin), sans Streamlit. Ne fait des requêtes qu'au premier passage
de chaque jour calendaire UTC (clôture de la veille, ~24 requêtes espacées
d'~1 s) ; les passages suivants de la journée ne font rien. Même bail que
l'app : jamais de double chargement si une liste est ouverte au même moment.
Les requêtes partent de l'IP de GitHub (coupe-circuit propre à cette IP),
pas de l'IP partagée de Streamlit Cloud.
"""

from src import daily_snapshot, db_core, diag_log, market_store


def run() -> None:
    diag_log.log_process_start()
    engine = db_core.create_engine_from_env()
    try:
        market_store.configure(lambda: engine, scope="github")  # coupe-circuit propre à l'IP GitHub
        for category, result in daily_snapshot.refresh_all_due(holder="github").items():
            print(f"Listes Trading - {category} : {result}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    run()
