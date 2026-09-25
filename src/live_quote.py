"""Prix EN DIRECT de la fiche actif (seul endroit de l'onglet Trading qui
interroge une source à chaque consultation), SANS dépendance à Streamlit.

Toutes les règles de fraîcheur de la fiche vivent ici, à un seul endroit :
- durée de cache par classe d'actif (PRICE_CACHE_SECONDS) : sert aussi de
  fréquence d'actualisation automatique de la fiche (inutile de relancer
  plus vite que le cache) ;
- garde-fou d'âge du prix affiché au moment d'un ordre ;
- pause de l'actualisation automatique après inactivité.
"""

from . import kraken_data
from . import market_data as md
from . import valuation

YAHOO = "yahoo"   # actions, ETF (dont obligataires), matières premières, forex
KRAKEN = "kraken"  # crypto

PRICE_CACHE_SECONDS = {YAHOO: 90, KRAKEN: 30}


def live_source(ticker: str, quote_type: str = "") -> str:
    """Source du prix en direct de la fiche : Kraken pour la crypto, Yahoo
    pour tout le reste (classe déduite comme partout ailleurs par
    valuation.category_for)."""
    return KRAKEN if valuation.category_for(quote_type, ticker) == "Crypto" else YAHOO


def price_cache_seconds(ticker: str, quote_type: str = "") -> int:
    return PRICE_CACHE_SECONDS[live_source(ticker, quote_type)]


def get_display_quote(ticker: str, quote_type: str = "") -> dict:
    """Prix affiché sur la fiche (même format que market_data.get_quote),
    réutilisé tant qu'il a moins que la durée de cache de sa classe.

    Crypto : Kraken Ticker (1 requête) ; si Kraken ne connaît pas la paire
    ou est indisponible, secours Yahoo (soumis à son propre coupe-circuit).
    Dans tous les cas, repli sur le dernier prix connu (mode « prix daté »)
    si aucune source ne répond ; lève MarketDataError si rien n'existe."""
    if live_source(ticker, quote_type) == KRAKEN:
        try:
            return kraken_data.get_ticker_quote(ticker, max_age=PRICE_CACHE_SECONDS[KRAKEN])
        except md.MarketDataError:
            pass
    return md.get_quote(ticker, allow_stale=True, max_age=PRICE_CACHE_SECONDS[YAHOO])
