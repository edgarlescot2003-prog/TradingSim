"""Pré-charge les prix indicatifs des listes Trading (asset_daily_snapshot).

Exécuté par le workflow dédié precharge-listes.yml (3 passages de nuit),
sans Streamlit. Ne fait des requêtes qu'au premier passage de chaque jour
calendaire UTC (clôture de la veille, une requête par actif espacée d'~1 s) ;
un passage suivant reprend ce qui manque (coupe-circuit, passage sauté) puis
ne fait plus rien. Même bail que l'app, liste par liste : jamais de double
chargement si une liste est ouverte au même moment.
Les requêtes partent de l'IP de GitHub (coupe-circuit propre à cette IP),
pas de l'IP partagée de Streamlit Cloud.
"""

from src import daily_snapshot, db_core, diag_log, market_store


def run() -> None:
    diag_log.log_process_start()
    engine = db_core.create_engine_from_env()
    try:
        market_store.configure(lambda: engine, scope="github")  # coupe-circuit propre à l'IP GitHub
        for scope, result in daily_snapshot.refresh_all_due(holder="github").items():
            print(f"Listes Trading - {scope} : {result}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    run()
