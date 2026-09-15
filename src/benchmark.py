"""Comparaison de la performance du portefeuille à une référence externe —
un indice de marché, ou le portefeuille officiel d'un autre participant du
concours (voir build_participant_comparison) — toutes deux normalisées en
base 100 au premier point disponible pour être comparables sur un même
graphique.
"""

import pandas as pd

from . import market_data as md

BENCHMARKS = {
    "CAC 40": "^FCHI",
    "S&P 500": "^GSPC",
    "Euro Stoxx 50": "^STOXX50E",
    "Nasdaq 100": "^NDX",
}


def _portfolio_series(value_history: list[dict]) -> pd.Series:
    """Série de valeur (dates -> € bruts, triée) à partir d'un value_history
    brut (voir Portfolio.value_history) — factorisé pour être réutilisé à la
    fois pour le portefeuille principal et pour un portefeuille de
    comparaison (participant)."""
    df = pd.DataFrame(value_history)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.sort_values("date").set_index("date")
    return df["value_eur"]


def _align_rebased(portfolio_series_100: pd.Series, other_raw: pd.Series) -> tuple[pd.Series, pd.Series] | None:
    """Aligne `other_raw` (dates -> valeur brute, indice ou portefeuille
    d'un participant) sur les dates de `portfolio_series_100` (déjà en base
    100), en base 100 elle aussi à partir de son premier point aligné commun.
    None si aucune date ne se recoupe. Factorisé entre build_comparison
    (indice) et build_participant_comparison (participant)."""
    other_index = pd.to_datetime(other_raw.index)
    if other_index.tz is not None:
        other_index = other_index.tz_localize(None)
    other_raw = pd.Series(other_raw.values, index=other_index).sort_index()

    # Aligne chaque date du portefeuille sur la dernière valeur connue de la
    # référence à cette date (les jours de bourse — ou de connexion d'un
    # autre participant — ne coïncident pas forcément avec les jours
    # d'utilisation de l'application).
    aligned = other_raw.reindex(other_raw.index.union(portfolio_series_100.index)).sort_index().ffill()
    aligned = aligned.reindex(portfolio_series_100.index).dropna()
    if aligned.empty:
        return None

    other_rebased = aligned / aligned.iloc[0] * 100
    portfolio_aligned = portfolio_series_100.reindex(aligned.index)
    return portfolio_aligned, other_rebased


def build_comparison(value_history: list[dict], benchmark_label: str) -> pd.DataFrame | None:
    """Retourne un DataFrame indexé par date avec une colonne "Portefeuille" et
    une colonne portant le nom du benchmark, toutes deux en base 100.

    None si l'historique du portefeuille est trop court (< 2 points) pour
    être exploitable. Lève MarketDataError si le benchmark est inaccessible.
    """
    if len(value_history) < 2:
        return None

    portfolio_raw = _portfolio_series(value_history)
    portfolio_series = portfolio_raw / portfolio_raw.iloc[0] * 100

    ticker = BENCHMARKS[benchmark_label]
    start = portfolio_series.index.min() - pd.Timedelta(days=7)  # marge pour le forward-fill du premier point
    hist = md.get_history(ticker, interval="1d", start=start)
    closes = hist["Close"]

    result = _align_rebased(portfolio_series, closes)
    if result is None:
        return pd.DataFrame({"Portefeuille": portfolio_series})

    portfolio_aligned, benchmark_series = result
    return pd.DataFrame({"Portefeuille": portfolio_aligned, benchmark_label: benchmark_series})


def build_participant_comparison(
    value_history: list[dict], other_value_history: list[dict], other_label: str,
) -> pd.DataFrame | None:
    """Comme build_comparison, mais la référence est le value_history du
    portefeuille OFFICIEL d'un autre participant (voir
    leaderboard.list_official_portfolios/get_value_history) plutôt qu'un
    indice externe — aucun appel réseau ici, contrairement à build_comparison
    (juste de l'alignement de deux courbes déjà en mémoire).

    None si l'un des deux historiques est trop court (< 2 points), ou si
    aucune date ne se recoupe entre les deux."""
    if len(value_history) < 2 or len(other_value_history) < 2:
        return None

    portfolio_raw = _portfolio_series(value_history)
    portfolio_series = portfolio_raw / portfolio_raw.iloc[0] * 100
    other_raw = _portfolio_series(other_value_history)

    result = _align_rebased(portfolio_series, other_raw)
    if result is None:
        return None

    portfolio_aligned, other_rebased = result
    return pd.DataFrame({"Portefeuille": portfolio_aligned, other_label: other_rebased})
