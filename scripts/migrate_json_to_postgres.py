"""Migration ponctuelle : importe les données JSON existantes
(data/portfolios.json, data/courses.json) vers PostgreSQL.

À exécuter une fois, manuellement, depuis la racine du projet :
    python -m scripts.migrate_json_to_postgres

Réutilise Portfolio.from_dict / Course pour parser le JSON, puis les mêmes
fonctions storage.save_portfolio / course_storage.save_courses que l'app
utilise normalement — aucune logique de conversion dupliquée.
"""

import json
from pathlib import Path

import streamlit as st

from src import course_storage, db, storage
from src.course import Course
from src.portfolio import Portfolio

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def migrate() -> None:
    db.init_db()
    user_id = db.ensure_default_user()
    st.session_state.user_id = user_id  # storage.py / course_storage.py le lisent de là
    print(f"Utilisateur cible : {user_id}")

    portfolios_file = DATA_DIR / "portfolios.json"
    if portfolios_file.exists():
        data = json.loads(portfolios_file.read_text(encoding="utf-8"))
        count = 0
        for pdata in data.get("portfolios", {}).values():
            portfolio = Portfolio.from_dict(pdata)
            storage.save_portfolio(portfolio)
            print(f"  Portefeuille migré : {portfolio.name!r} — "
                  f"{len(portfolio.positions)} position(s), {len(portfolio.history)} trade(s), "
                  f"{len(portfolio.pending_orders)} ordre(s) en attente, "
                  f"{len(portfolio.value_history)} point(s) de valeur")
            count += 1
        print(f"{count} portefeuille(s) migré(s).")
    else:
        print("Aucun data/portfolios.json trouvé, rien à migrer côté portefeuilles.")

    courses_file = DATA_DIR / "courses.json"
    if courses_file.exists():
        raw = json.loads(courses_file.read_text(encoding="utf-8"))
        courses = [Course(**c) for c in raw]
        course_storage.save_courses(courses)
        print(f"{len(courses)} cours migré(s).")
    else:
        print("Aucun data/courses.json trouvé, rien à migrer côté cours.")


if __name__ == "__main__":
    migrate()
