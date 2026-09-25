"""Univers d'actifs proposé par l'onglet Trading (listes par catégorie),
SANS dépendance à Streamlit ni au réseau.

Source unique des noms affichés et des catégories : l'accueil Trading (cases
de catégories, suggestions de recherche) et la table des prix indicatifs
quotidiens (daily_snapshot.py, qui s'amorce avec ces actifs) lisent tous les
deux ces listes. Les indices (^FCHI, ^GSPC...) n'en font plus partie : ils ne
sont pas achetables. admin_snapshot.py (page Admin News) et benchmark.py
(comparaison du Portefeuille) gardent leurs propres listes d'indices.

Catégories = libellés internes de valuation.category_for (couleurs de badge
theme.CATEGORY_COLORS) ; CATEGORY_LABELS donne le libellé affiché.
"""

ACTIONS = "Actions"
CRYPTO = "Crypto"
BONDS = "Obligations"
FOREX = "Forex"
COMMODITIES = "Matières premières"

# Ordre d'affichage des cases de l'accueil.
CATEGORIES = [ACTIONS, CRYPTO, BONDS, FOREX, COMMODITIES]
CATEGORY_LABELS = {
    ACTIONS: "Actions",
    CRYPTO: "Crypto",
    BONDS: "Obligations",
    FOREX: "Forex/Monnaies",
    COMMODITIES: "Matières premières",
}

ASSETS_BY_CATEGORY: dict[str, list[tuple[str, str]]] = {
    ACTIONS: [
        ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"),
        ("GOOGL", "Alphabet"), ("AMZN", "Amazon"),
    ],
    CRYPTO: [
        ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"), ("XRP-USD", "XRP"),
    ],
    # Paires majeures ; les autres paires restent accessibles par la
    # recherche (valuation.category_for détecte le suffixe "=X").
    FOREX: [
        ("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD"), ("USDJPY=X", "USD/JPY"),
        ("USDCHF=X", "USD/CHF"), ("AUDUSD=X", "AUD/USD"),
    ],
    COMMODITIES: [
        ("GC=F", "Or"), ("SI=F", "Argent"), ("CL=F", "Pétrole WTI"),
        ("BZ=F", "Pétrole Brent"), ("NG=F", "Gaz naturel"),
    ],
    # ETF obligataires (voir valuation.BOND_ETF_TICKERS) : jamais les
    # rendements d'État bruts (^TNX...), qui ne sont pas des prix négociables.
    BONDS: [
        ("TLT", "Treasury 20+ ans"), ("IEF", "Treasury 7-10 ans"), ("BND", "Obligations US (total market)"),
        ("AGG", "Obligations US (agrégé)"), ("SHY", "Treasury 1-3 ans"),
    ],
}


def all_assets() -> list[tuple[str, str, str]]:
    """(ticker, nom, catégorie) pour tout l'univers, dans l'ordre d'affichage."""
    return [(t, n, c) for c in CATEGORIES for t, n in ASSETS_BY_CATEGORY[c]]
