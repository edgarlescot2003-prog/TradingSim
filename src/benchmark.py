"""Comparaison de la performance du portefeuille à un indice de référence,
tous deux normalisés en base 100 au premier point disponible pour être
comparables sur un même graphique.
"""

import pandas as pd

from . import market_data as md

BENCHMARKS = {
    "CAC 40": "^FCHI",
    "S&P 500": "^GSPC",
    "Euro Stoxx 50": "^STOXX50E",
    "Nasdaq 100": "^NDX",
}


def build_comparison(value_history: list[dict], benchmark_label: str) -> pd.DataFrame | None:
    """Retourne un DataFrame indexé par date avec une colonne "Portefeuille" et
    une colonne portant le nom du benchmark, toutes deux en base 100.

    None si l'historique du portefeuille est trop court (< 2 points) pour
    être exploitable. Lève MarketDataError si le benchmark est inaccessible.
    """
    if len(value_history) < 2:
        return None

    portfolio_df = pd.DataFrame(value_history)
    portfolio_df["date"] = pd.to_datetime(portfolio_df["date"]).dt.tz_localize(None)
    portfolio_df = portfolio_df.sort_values("date").set_index("date")
    portfolio_series = portfolio_df["value_eur"] / portfolio_df["value_eur"].iloc[0] * 100

    ticker = BENCHMARKS[benchmark_label]
    start = portfolio_series.index.min() - pd.Timedelta(days=7)  # marge pour le forward-fill du premier point
    hist = md.get_history(ticker, interval="1d", start=start)

    hist_index = pd.to_datetime(hist.index)
    if hist_index.tz is not None:
        hist_index = hist_index.tz_localize(None)
    closes = pd.Series(hist["Close"].values, index=hist_index).sort_index()

    # Aligne chaque date du portefeuille sur le dernier cours de clôture connu
    # de l'indice à cette date (les jours de bourse ne coïncident pas
    # forcément avec les jours d'utilisation de l'application).
    aligned = closes.reindex(closes.index.union(portfolio_series.index)).sort_index().ffill()
    aligned = aligned.reindex(portfolio_series.index).dropna()

    if aligned.empty:
        return pd.DataFrame({"Portefeuille": portfolio_series})

    benchmark_series = aligned / aligned.iloc[0] * 100
    portfolio_aligned = portfolio_series.reindex(aligned.index)

    return pd.DataFrame({"Portefeuille": portfolio_aligned, benchmark_label: benchmark_series})
