"""Restaure TOUTE la base Supabase depuis une sauvegarde CSV produite par
scripts/backup_db.py (voir backups/README.md pour le guide pas à pas).

⚠️ DESTRUCTIF : vide entièrement chaque table avant d'y réinsérer les lignes
de la sauvegarde choisie. À exécuter uniquement en cas d'incident réel sur la
base (suppression accidentelle, corruption), jamais automatiquement — ce
script n'est appelé nulle part ailleurs dans l'app ou les workflows.

Usage (depuis la racine du projet, avec le même .env que l'app) :
    python -m scripts.restore_db backups/2026-09-12
"""

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src import db
from src.db_models import (
    CourseRow, NewsRow, PendingOrderRow, PortfolioRow, PositionRow, SearchHistoryRow, TradeRow, User,
    ValueHistoryRow,
)

# Ordre de SUPPRESSION : les tables filles (qui référencent users/portfolios
# via une clé étrangère) doivent être vidées AVANT leurs tables parentes.
# La RÉINSERTION se fait dans l'ordre inverse (parents d'abord).
TABLES_CHILDREN_FIRST = [
    PositionRow, TradeRow, PendingOrderRow, ValueHistoryRow, SearchHistoryRow,
    CourseRow, NewsRow, PortfolioRow, User,
]


def _load_dataframe(backup_dir: Path, table_name: str) -> pd.DataFrame:
    path = backup_dir / f"{table_name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Fichier manquant dans la sauvegarde : {path} — sauvegarde incomplète ou dossier invalide."
        )
    df = pd.read_csv(path, keep_default_na=True)
    # Cellules vides -> None (pas la chaîne "" ni NaN) : nécessaire pour les
    # colonnes nullable (ex : CourseRow.user_id, NewsRow.link) réinsérées
    # correctement en NULL plutôt qu'en chaîne vide.
    return df.where(pd.notnull(df), None)


def restore(backup_dir: Path) -> None:
    engine = db.get_engine()
    with engine.begin() as conn:
        print("Suppression des données actuelles...")
        for model in TABLES_CHILDREN_FIRST:
            conn.execute(text(f'DELETE FROM "{model.__tablename__}"'))

        print("Réinsertion depuis la sauvegarde...")
        for model in reversed(TABLES_CHILDREN_FIRST):
            df = _load_dataframe(backup_dir, model.__tablename__)
            if df.empty:
                print(f"  {model.__tablename__}: 0 ligne (table vide dans la sauvegarde)")
                continue
            df.to_sql(model.__tablename__, conn, if_exists="append", index=False)
            print(f"  {model.__tablename__}: {len(df)} lignes restaurées")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python -m scripts.restore_db backups/AAAA-MM-JJ")
        sys.exit(1)

    target_dir = Path(sys.argv[1])
    if not target_dir.is_dir():
        print(f"Dossier introuvable : {target_dir}")
        sys.exit(1)

    print(
        f"⚠️  ATTENTION : ceci va REMPLACER TOUTES les données actuelles de la base "
        f"par la sauvegarde « {target_dir.name} ». Cette action est IRRÉVERSIBLE."
    )
    confirmation = input("Tape OUI (en majuscules) pour confirmer, autre chose pour annuler : ")
    if confirmation != "OUI":
        print("Annulé, aucune modification effectuée.")
        sys.exit(0)

    restore(target_dir)
    print("Restauration terminée.")
