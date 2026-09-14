"""Résumé hebdomadaire automatique publié dans l'onglet News.

Calculé uniquement à partir des données déjà stockées (courbe de valeur des
portefeuilles officiels, historique des trades) — AUCUN nouvel appel aux API
de prix externes (contrainte non négociable de la doc de conception
d'origine). Rien n'est revalorisé en direct ici, contrairement au Classement.

Il n'y a pas de vrai scheduler dans ce projet (app Streamlit sans tâche de
fond) : la génération est donc vérifiée à chaque démarrage du serveur
(check_and_generate, mis en cache 1h — voir app.py) plutôt qu'à une heure
fixe. `maybe_generate` calcule la semaine calendaire (lundi->dimanche) qui
vient de se terminer et publie un résumé si :
  1. il n'existe pas déjà un résumé pour cette semaine (dédoublonné par le
     titre exact, généré de façon déterministe à partir des dates) ;
  2. il y a quelque chose à résumer (au moins un portefeuille officiel qui
     existait déjà au début de cette semaine).
Comme la vérification se refait à chaque lancement, un lundi sans connexion
n'est jamais un problème : le résumé de la semaine manquée sera publié au
prochain démarrage, quel que soit le jour.
"""

from datetime import date, datetime, timedelta

import streamlit as st
from sqlalchemy import select

from . import db, news_storage
from .db_models import NewsRow, PortfolioRow, TradeRow, User, ValueHistoryRow
from .news import NewsItem

SYSTEM_TITLE_PREFIX = "Résumé hebdomadaire"


def _last_completed_week(today: date) -> tuple[date, date]:
    """(lundi, dimanche) de la semaine calendaire qui précède celle de `today`."""
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)
    return last_monday, last_sunday


def _title_for_week(monday: date, sunday: date) -> str:
    return f"{SYSTEM_TITLE_PREFIX} — semaine du {monday.strftime('%d/%m')} au {sunday.strftime('%d/%m/%Y')}"


def _most_traded_ticker(session, week_start_iso: str, week_end_iso: str) -> tuple[str, int] | None:
    rows = session.execute(
        select(TradeRow.ticker).where(TradeRow.date >= week_start_iso, TradeRow.date <= week_end_iso)
    ).all()
    if not rows:
        return None
    counts: dict[str, int] = {}
    for (ticker,) in rows:
        counts[ticker] = counts.get(ticker, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])


def _weekly_returns(session, monday: date, sunday: date) -> list[dict]:
    """Variation en % de chaque portefeuille officiel sur la semaine, pour
    les portefeuilles qui existaient déjà au lundi. La valeur de départ est
    le dernier point connu à date <= lundi (capital de départ si aucun point
    n'existe encore ce jour-là) ; la valeur de fin, le dernier point connu à
    date <= dimanche. Un portefeuille sans aucun point de valorisation dans
    toute la période est exclu (rien à comparer)."""
    usernames = {u.id: u.username for u in session.execute(select(User)).scalars().all()}
    official_portfolios = session.execute(
        select(PortfolioRow).where(PortfolioRow.is_official.is_(True))
    ).scalars().all()

    monday_iso, sunday_iso = monday.isoformat(), sunday.isoformat()
    # Borne exclusive (lundi de la semaine SUIVANTE, en simple "YYYY-MM-DD") :
    # comparer une chaîne ISO complète (avec heure/microsecondes, format des
    # dates réellement écrites par Portfolio.record_value_snapshot) à
    # `sunday_iso + "T23:59:59"` échouerait dès qu'un point porte des
    # microsecondes ("...T23:59:59.451232" est lexicographiquement PLUS GRAND
    # que "...T23:59:59", donc exclu à tort) — une simple date "YYYY-MM-DD"
    # n'a pas ce problème : toute date-heure du dimanche reste lexicalement
    # avant le lundi suivant, quelle que soit l'heure/précision.
    next_week_start_iso = (sunday + timedelta(days=1)).isoformat()
    results = []
    for prow in official_portfolios:
        if prow.created_at[:10] > monday_iso:
            continue  # n'existait pas encore au début de la semaine

        points = session.execute(
            select(ValueHistoryRow.date, ValueHistoryRow.value_eur)
            .where(ValueHistoryRow.portfolio_id == prow.id, ValueHistoryRow.date < next_week_start_iso)
            .order_by(ValueHistoryRow.date)
        ).all()

        start_value = prow.initial_capital
        end_value = None
        for point_date, value_eur in points:
            if point_date[:10] <= monday_iso:
                start_value = value_eur
            if point_date[:10] <= sunday_iso:
                end_value = value_eur

        if end_value is None or start_value <= 0:
            continue

        results.append({
            "username": usernames.get(prow.user_id, "(compte supprimé)"),
            "return_pct": (end_value / start_value - 1) * 100,
        })

    results.sort(key=lambda r: r["return_pct"], reverse=True)
    return results


def _build_summary_content(session, monday: date, sunday: date) -> str | None:
    """None si rien à résumer (aucun portefeuille officiel actif sur cette
    semaine) — pas de publication d'un article vide dans ce cas."""
    weekly_returns = _weekly_returns(session, monday, sunday)
    if not weekly_returns:
        return None

    lines = [
        f"Classement de la semaine du {monday.strftime('%d/%m')} au {sunday.strftime('%d/%m/%Y')} "
        "(variation sur la semaine, portefeuilles officiels uniquement) :",
        "",
    ]
    for i, r in enumerate(weekly_returns, start=1):
        sign = "+" if r["return_pct"] >= 0 else ""
        lines.append(f"{i}. **{r['username']}** — {sign}{r['return_pct']:.2f} %")

    best = weekly_returns[0]
    best_sign = "+" if best["return_pct"] >= 0 else ""
    lines += ["", f"Plus forte progression : **{best['username']}** ({best_sign}{best['return_pct']:.2f} %)"]

    if len(weekly_returns) > 1:
        worst = weekly_returns[-1]
        worst_sign = "+" if worst["return_pct"] >= 0 else ""
        lines.append(f"Plus forte baisse : **{worst['username']}** ({worst_sign}{worst['return_pct']:.2f} %)")

    top_ticker = _most_traded_ticker(
        session, datetime.combine(monday, datetime.min.time()).isoformat(),
        datetime.combine(sunday, datetime.max.time()).isoformat(),
    )
    if top_ticker:
        ticker, count = top_ticker
        ordre = "ordre" if count == 1 else "ordres"
        lines += ["", f"Actif le plus tradé de la semaine (tous portefeuilles confondus) : **{ticker}** ({count} {ordre})"]

    return "\n".join(lines)


def maybe_generate() -> None:
    """Publie le résumé de la dernière semaine calendaire complète s'il
    n'existe pas déjà et qu'il y a quelque chose à résumer. Sans effet la
    toute première semaine du concours (aucune semaine complète précédente)."""
    today = date.today()
    monday, sunday = _last_completed_week(today)
    if today <= monday:
        return

    title = _title_for_week(monday, sunday)

    with db.get_session() as session:
        already_published = session.execute(
            select(NewsRow.id).where(NewsRow.title == title)
        ).scalar_one_or_none()
        if already_published is not None:
            return

        content = _build_summary_content(session, monday, sunday)

    if content is None:
        return

    news_storage.add_news(NewsItem(title=title, content=content, is_system=True), author_user_id=None)


@st.cache_resource(ttl=3600, show_spinner=False)
def check_and_generate() -> None:
    """Enveloppe cache_resource de maybe_generate() : la vérification (une
    poignée de requêtes DB, aucun appel API de prix) ne s'exécute réellement
    qu'une fois par heure et par processus serveur, partagée entre toutes les
    sessions — pas à chaque rerun de chaque utilisateur connecté."""
    maybe_generate()
