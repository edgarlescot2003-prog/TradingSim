"""Univers d'actifs proposé par l'onglet Trading (listes par catégorie),
SANS dépendance à Streamlit ni au réseau.

Source unique des noms affichés, des catégories, et pour les actions de la
zone et du pays : l'accueil Trading (cases de catégories, suggestions de
recherche), les pages de liste et la table des prix indicatifs quotidiens
(daily_snapshot.py, qui s'amorce avec ces actifs) lisent tous ces listes. La
recherche, elle, reste indépendante : n'importe quel ticker Yahoo/Kraken est
tradable, ces listes ne sont qu'une vitrine.

Élargissement du 26/09/2026 (proposition validée par Edgar, voir
docs/proposition_elargissement_univers.md) : 160 actifs, tous vérifiés
auprès de Yahoo (et Kraken pour la crypto) le 25/09/2026.
- Actions : les 30 plus grosses capitalisations de chaque ZONE (converties
  en euros), répartition par pays non imposée ; Amérique = 25 États-Unis +
  5 Canada (le classement pur n'en retenait aucune). Chine et Hong Kong
  exclus pour cette V1. Unilever gardée une seule fois (Londres).
- Actions de Londres cotées en pence et contrats agricoles en cents :
  convertis par market_data.normalize_currency.

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

# Zones des actions (ordre d'affichage) et noms des pays présents.
ZONES = ["europe", "amerique", "asie"]
COUNTRY_NAMES = {
    "france": "France", "allemagne": "Allemagne", "royaume-uni": "Royaume-Uni", "suisse": "Suisse",
    "pays-bas": "Pays-Bas", "espagne": "Espagne", "italie": "Italie",
    "etats-unis": "États-Unis", "canada": "Canada",
    "japon": "Japon", "coree-du-sud": "Corée du Sud", "inde": "Inde", "taiwan": "Taïwan",
}

# (ticker Yahoo, nom affiché, pays), classés par capitalisation décroissante.
STOCKS_BY_ZONE: dict[str, list[tuple[str, str, str]]] = {
    "europe": [
        ("ASML.AS", "ASML", "pays-bas"), ("RO.SW", "Roche", "suisse"), ("HSBA.L", "HSBC", "royaume-uni"),
        ("NOVN.SW", "Novartis", "suisse"), ("SHEL.L", "Shell", "royaume-uni"),
        ("AZN.L", "AstraZeneca", "royaume-uni"), ("SIE.DE", "Siemens", "allemagne"), ("SAP.DE", "SAP", "allemagne"),
        ("NESN.SW", "Nestlé", "suisse"), ("OR.PA", "L'Oréal", "france"), ("MC.PA", "LVMH", "france"),
        ("SAN.MC", "Banco Santander", "espagne"), ("TTE.PA", "TotalEnergies", "france"),
        ("ITX.MC", "Inditex", "espagne"), ("SU.PA", "Schneider Electric", "france"),
        ("ALV.DE", "Allianz", "allemagne"), ("ABBN.SW", "ABB", "suisse"), ("AIR.PA", "Airbus", "france"),
        ("RR.L", "Rolls-Royce", "royaume-uni"), ("RMS.PA", "Hermès", "france"), ("SAF.PA", "Safran", "france"),
        ("BBVA.MC", "BBVA", "espagne"), ("IBE.MC", "Iberdrola", "espagne"), ("RIO.L", "Rio Tinto", "royaume-uni"),
        ("UBSG.SW", "UBS", "suisse"), ("DTE.DE", "Deutsche Telekom", "allemagne"),
        ("UCG.MI", "UniCredit", "italie"), ("ISP.MI", "Intesa Sanpaolo", "italie"),
        ("ULVR.L", "Unilever", "royaume-uni"), ("BNP.PA", "BNP Paribas", "france"),
    ],
    "amerique": [
        ("NVDA", "Nvidia", "etats-unis"), ("AAPL", "Apple", "etats-unis"), ("GOOGL", "Alphabet", "etats-unis"),
        ("MSFT", "Microsoft", "etats-unis"), ("AMZN", "Amazon", "etats-unis"), ("META", "Meta", "etats-unis"),
        ("AVGO", "Broadcom", "etats-unis"), ("TSLA", "Tesla", "etats-unis"),
        ("BRK-B", "Berkshire Hathaway", "etats-unis"), ("LLY", "Eli Lilly", "etats-unis"),
        ("AMD", "AMD", "etats-unis"), ("JPM", "JPMorgan Chase", "etats-unis"), ("WMT", "Walmart", "etats-unis"),
        ("V", "Visa", "etats-unis"), ("XOM", "ExxonMobil", "etats-unis"), ("JNJ", "Johnson & Johnson", "etats-unis"),
        ("INTC", "Intel", "etats-unis"), ("MA", "Mastercard", "etats-unis"), ("ABBV", "AbbVie", "etats-unis"),
        ("CSCO", "Cisco", "etats-unis"), ("ORCL", "Oracle", "etats-unis"), ("COST", "Costco", "etats-unis"),
        ("CVX", "Chevron", "etats-unis"), ("BAC", "Bank of America", "etats-unis"),
        ("KO", "Coca-Cola", "etats-unis"),
        ("RY.TO", "Royal Bank of Canada", "canada"), ("TD.TO", "Toronto-Dominion Bank", "canada"),
        ("SHOP.TO", "Shopify", "canada"), ("BMO.TO", "Bank of Montreal", "canada"),
        ("BNS.TO", "Scotiabank", "canada"),
    ],
    "asie": [
        ("2330.TW", "TSMC", "taiwan"), ("005930.KS", "Samsung Electronics", "coree-du-sud"),
        ("000660.KS", "SK hynix", "coree-du-sud"), ("2454.TW", "MediaTek", "taiwan"),
        ("8306.T", "Mitsubishi UFJ", "japon"), ("7203.T", "Toyota", "japon"), ("9984.T", "SoftBank Group", "japon"),
        ("RELIANCE.NS", "Reliance Industries", "inde"), ("8316.T", "Sumitomo Mitsui", "japon"),
        ("8035.T", "Tokyo Electron", "japon"), ("6501.T", "Hitachi", "japon"), ("2308.TW", "Delta Electronics", "taiwan"),
        ("6098.T", "Recruit", "japon"), ("6758.T", "Sony", "japon"), ("9983.T", "Fast Retailing", "japon"),
        ("8411.T", "Mizuho", "japon"), ("6861.T", "Keyence", "japon"), ("HDFCBANK.NS", "HDFC Bank", "inde"),
        ("BHARTIARTL.NS", "Bharti Airtel", "inde"), ("3711.TW", "ASE Technology", "taiwan"),
        ("8058.T", "Mitsubishi Corp.", "japon"), ("2317.TW", "Hon Hai (Foxconn)", "taiwan"),
        ("ICICIBANK.NS", "ICICI Bank", "inde"), ("8001.T", "Itochu", "japon"), ("8766.T", "Tokio Marine", "japon"),
        ("SBIN.NS", "State Bank of India", "inde"), ("6981.T", "Murata", "japon"), ("9432.T", "NTT", "japon"),
        ("7011.T", "Mitsubishi Heavy Industries", "japon"), ("TCS.NS", "Tata Consultancy Services", "inde"),
    ],
}

ASSETS_BY_CATEGORY: dict[str, list[tuple[str, str]]] = {
    ACTIONS: [(t, n) for zone in ZONES for t, n, _ in STOCKS_BY_ZONE[zone]],
    CRYPTO: [
        ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"), ("XRP-USD", "XRP"),
        ("ADA-USD", "Cardano"), ("DOGE-USD", "Dogecoin"), ("TRX-USD", "TRON"), ("AVAX-USD", "Avalanche"),
        ("LINK-USD", "Chainlink"), ("DOT-USD", "Polkadot"), ("LTC-USD", "Litecoin"), ("BCH-USD", "Bitcoin Cash"),
        ("XLM-USD", "Stellar"), ("UNI7083-USD", "Uniswap"), ("ATOM-USD", "Cosmos"), ("NEAR-USD", "NEAR Protocol"),
        ("AAVE-USD", "Aave"), ("ETC-USD", "Ethereum Classic"), ("FIL-USD", "Filecoin"), ("ALGO-USD", "Algorand"),
    ],
    # Paires regroupées par devise dans l'onglet (trading_nav_config.FOREX_CURRENCIES).
    FOREX: [
        ("EURUSD=X", "EUR/USD"), ("GBPUSD=X", "GBP/USD"), ("USDJPY=X", "USD/JPY"), ("USDCHF=X", "USD/CHF"),
        ("AUDUSD=X", "AUD/USD"), ("USDCAD=X", "USD/CAD"), ("NZDUSD=X", "NZD/USD"), ("EURGBP=X", "EUR/GBP"),
        ("EURJPY=X", "EUR/JPY"), ("EURCHF=X", "EUR/CHF"), ("GBPJPY=X", "GBP/JPY"), ("AUDJPY=X", "AUD/JPY"),
        ("EURAUD=X", "EUR/AUD"), ("GBPCHF=X", "GBP/CHF"), ("CHFJPY=X", "CHF/JPY"), ("EURCAD=X", "EUR/CAD"),
        ("CADJPY=X", "CAD/JPY"), ("AUDNZD=X", "AUD/NZD"),
    ],
    # Contrats à terme ; regroupés en familles (COMMODITY_FAMILIES).
    COMMODITIES: [
        ("GC=F", "Or"), ("SI=F", "Argent"), ("PL=F", "Platine"), ("PA=F", "Palladium"), ("HG=F", "Cuivre"),
        ("CL=F", "Pétrole WTI"), ("BZ=F", "Pétrole Brent"), ("NG=F", "Gaz naturel"), ("RB=F", "Essence (RBOB)"),
        ("HO=F", "Fioul domestique"), ("ZC=F", "Maïs"), ("ZW=F", "Blé"), ("ZS=F", "Soja"), ("KC=F", "Café"),
        ("SB=F", "Sucre"), ("CC=F", "Cacao"),
    ],
    # ETF obligataires américains (valuation.BOND_ETF_TICKERS) ; jamais les
    # rendements d'État bruts (^TNX...), qui ne sont pas des prix négociables.
    # Regroupés dans l'onglet par trading_nav_config.BOND_GROUPS.
    BONDS: [
        ("SGOV", "Trésor US 0-3 mois"), ("SHY", "Trésor US 1-3 ans"), ("IEI", "Trésor US 3-7 ans"),
        ("IEF", "Trésor US 7-10 ans"), ("TLH", "Trésor US 10-20 ans"), ("TLT", "Trésor US 20+ ans"),
        ("GOVT", "Trésor US toutes maturités"), ("BND", "Obligations US (total market)"),
        ("AGG", "Obligations US (agrégé)"), ("MUB", "Obligations municipales US"),
        ("LQD", "Entreprises US investment grade"), ("HYG", "Entreprises US haut rendement"),
        ("JNK", "Entreprises US haut rendement (SPDR)"), ("TIP", "Trésor US indexé sur l'inflation"),
        ("BNDX", "Obligations internationales (couvertes)"), ("EMB", "Obligations émergentes en dollars"),
    ],
}

# Familles de matières premières (validées par Edgar : 3 familles).
COMMODITY_FAMILIES = {
    "metaux": {"nom": "Métaux", "description": "Métaux précieux (or, argent, platine, palladium) et cuivre.",
               "tickers": ["GC=F", "SI=F", "PL=F", "PA=F", "HG=F"]},
    "energie": {"nom": "Énergie", "description": "Pétrole (WTI, Brent), gaz naturel, essence et fioul.",
                "tickers": ["CL=F", "BZ=F", "NG=F", "RB=F", "HO=F"]},
    "agriculture": {"nom": "Agriculture", "description": "Céréales (maïs, blé, soja) et produits tropicaux "
                                                         "(café, sucre, cacao).",
                    "tickers": ["ZC=F", "ZW=F", "ZS=F", "KC=F", "SB=F", "CC=F"]},
}

# Zone et pays renseignés en base (daily_snapshot, sans jamais écraser une
# valeur existante) : actions par zone ; ETF obligataires = fonds américains.
ASSET_PLACES: dict[str, tuple[str, str]] = {
    **{t: (zone, country) for zone in ZONES for t, _, country in STOCKS_BY_ZONE[zone]},
    **{t: ("amerique", "etats-unis") for t, _ in ASSETS_BY_CATEGORY[BONDS]},
}

_NAMES = {t: n for assets in ASSETS_BY_CATEGORY.values() for t, n in assets}
_CATEGORY_BY_TICKER = {t: c for c, assets in ASSETS_BY_CATEGORY.items() for t, _ in assets}


def all_assets() -> list[tuple[str, str, str]]:
    """(ticker, nom, catégorie) pour tout l'univers, dans l'ordre d'affichage."""
    return [(t, n, c) for c in CATEGORIES for t, n in ASSETS_BY_CATEGORY[c]]


def category_of(ticker: str) -> str | None:
    """Catégorie d'un ticker de l'univers, None s'il n'en fait pas partie."""
    return _CATEGORY_BY_TICKER.get(ticker)


def name_of(ticker: str) -> str | None:
    """Nom affiché d'un ticker de l'univers (prime sur le nom stocké en base)."""
    return _NAMES.get(ticker)


def in_universe(ticker: str) -> bool:
    return ticker in _CATEGORY_BY_TICKER


def countries_of_zone(zone: str) -> list[str]:
    """Pays présents dans la liste d'une zone, dans l'ordre de première apparition."""
    return list(dict.fromkeys(country for _, _, country in STOCKS_BY_ZONE.get(zone, [])))
