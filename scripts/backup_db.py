"""Sauvegarde périodique de la base Supabase : exporte chaque table en CSV
dans backups/AAAA-MM-JJ/, commité dans le dépôt GitHub (pas de service tiers
payant). Lancé automatiquement chaque jour par le workflow GitHub Actions
(.github/workflows/backup.yml) — voir backups/README.md pour restaurer.

Exécutable aussi manuellement en local, depuis la racine du projet :
    python -m scripts.backup_db

Rotation : ne garde que les KEEP_LAST_N sauvegardes les plus récentes, pour
ne pas faire gonfler le dépôt indéfiniment (chaque sauvegarde ne pèse que
quelques dizaines de Ko pour ce projet).
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src import db
from src.db_models import (
    CourseRow, NewsRow, PendingOrderRow, PortfolioRow, PositionRow, SearchHistoryRow, TradeRow, User,
    ValueHistoryRow,
)

BACKUPS_DIR = Path(__file__).resolve().parent.parent / "backups"

KEEP_LAST_N = 14

# Toutes les tables métier de db_models.py — pas seulement les plus
# "critiques" citées en exemple dans la doc de conception (users, portfolios,
# ordres, historique de valorisation) : le coût d'inclure aussi
# positions/cours/news/recherche est négligeable et rend la sauvegarde
# complète plutôt que partielle.
TABLES = {
    "users": User,
    "portfolios": PortfolioRow,
    "positions": PositionRow,
    "trades": TradeRow,
    "pending_orders": PendingOrderRow,
    "value_history": ValueHistoryRow,
    "search_history": SearchHistoryRow,
    "courses": CourseRow,
    "news": NewsRow,
}


def _export_table(engine, model, out_path: Path) -> int:
    df = pd.read_sql_table(model.__tablename__, engine)
    df.to_csv(out_path, index=False)
    return len(df)


def _rotate() -> None:
    """Ne garde que les KEEP_LAST_N dossiers de sauvegarde les plus récents
    (noms au format AAAA-MM-JJ : le tri alphabétique est aussi un tri
    chronologique)."""
    if not BACKUPS_DIR.exists():
        return
    day_dirs = sorted(p for p in BACKUPS_DIR.iterdir() if p.is_dir())
    for old_dir in day_dirs[:-KEEP_LAST_N]:
        shutil.rmtree(old_dir)
        print(f"  Rotation : suppression de {old_dir.name}")


def run_backup() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = BACKUPS_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = db.get_engine()
    for table_name, model in TABLES.items():
        count = _export_table(engine, model, out_dir / f"{table_name}.csv")
        print(f"  {table_name}: {count} lignes")

    _rotate()
    return out_dir


if __name__ == "__main__":
    print(f"Sauvegarde en cours vers {BACKUPS_DIR}...")
    result_dir = run_backup()
    print(f"Terminé : {result_dir}")
