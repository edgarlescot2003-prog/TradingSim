"""Configuration statique de la navigation de l'onglet Trading (zones, pays,
indices de référence), SANS dépendance à Streamlit ni au réseau.

Performances d'indices = valeurs FIGÉES de l'année ANNEE_PERF, recopiées
telles quelles depuis l'annexe B du prompt de conception (recueillies par
Claude (chat) sur des sources publiques le 24/09/2026). Aucune requête, aucun
rafraîchissement : ce sont des variations d'indices (devise locale, indice
« prix » sauf mention contraire), pas le rendement d'un placement.

MISE À JOUR ANNUELLE (chaque janvier) : changer ANNEE_PERF et TOUTES les
valeurs `perf` avec leurs sources, en une seule modification de ce fichier.
Ne jamais « corriger » une valeur sans source.

Disponibilité (carte cliquable ou « Bientôt ») : jamais écrite ici, calculée
depuis la table des prix indicatifs (daily_snapshot.available_places).
"""

ANNEE_PERF = 2025

PERF_FOOTNOTE = (f"Performance {ANNEE_PERF} de l'indice (variation de l'indice, devise locale), "
                 "à titre indicatif.")

# Indices : nom, perf (%), décimales affichées, approx (affiché « ≈ »),
# note (affichée sur la carte), nature, sources.
_STOXX_600 = {"nom": "STOXX Europe 600", "perf": 17.0, "decimales": 0, "approx": True, "nature": "prix",
              "source": "Reuters (sondage août 2026, « presque 17 % ») ; Trading Economics 31/12/2025 "
                        "(« 17 % », clôture ~592). Certaines sources arrondissent à 16 %."}
_SP_500 = {"nom": "S&P 500", "perf": 16.4, "decimales": 1, "nature": "prix (rendement total ≈ +17,9 %)",
           "source": "YCharts (16,39 %) ; Statista (16,4 %) ; First Trust (17,9 % dividendes inclus)"}
_NIKKEI = {"nom": "Nikkei 225", "perf": 26.2, "decimales": 1, "nature": "prix",
           "source": "Club Patrimoine ; Kyodo / Nikkei Asia (« 26 % », clôture 50 339,48)"}
_HANG_SENG = {"nom": "Hang Seng", "perf": 27.77, "decimales": 1, "nature": "prix",
              "source": "Global Times ; SCMP (« 28 % »)"}
_SHANGHAI = {"nom": "Shanghai Composite", "perf": 18.41, "decimales": 1, "nature": "prix",
             "source": "Global Times ; People's Daily (CSI 300 : +17,66 %)"}

ZONES = {
    "europe": {
        "nom": "Europe", "contour": "europe",
        "description": "Grandes places boursières européennes.",
        "pays": ["france", "allemagne", "royaume-uni", "suisse", "pays-bas"],
        "indices": [_STOXX_600],
    },
    "amerique": {
        "nom": "Amérique", "contour": "amerique",
        "description": "Marchés d'Amérique du Nord, dont Wall Street.",
        "pays": ["etats-unis", "canada"],
        "indices": [_SP_500],
    },
    "asie": {
        "nom": "Asie", "contour": "asie",
        "description": "Japon, Chine et Hong Kong. Pas d'indice unique pour la zone.",
        "pays": ["japon", "chine", "hong-kong"],
        "indices": [_NIKKEI, _HANG_SENG, _SHANGHAI],
    },
}

PAYS = {
    "france": {"nom": "France", "zone": "europe", "contour": "france",
               "indice": {"nom": "CAC 40", "perf": 10.42, "decimales": 1, "nature": "prix (CAC 40 GR ≈ +14,3 %)",
                          "source": "Option Finance / AOF 31/12/2025 ; BFM Bourse (clôture 8 149,50)"}},
    "allemagne": {"nom": "Allemagne", "zone": "europe", "contour": "allemagne",
                  "indice": {"nom": "DAX 40", "perf": 23.01, "decimales": 1, "note": "dividendes inclus",
                             "nature": "indice de performance (dividendes réinvestis)",
                             "source": "Option Finance / AOF 31/12/2025 ; Beursgorilla (22,9 %)"}},
    "royaume-uni": {"nom": "Royaume-Uni", "zone": "europe", "contour": "royaume-uni",
                    "indice": {"nom": "FTSE 100", "perf": 21.51, "decimales": 1, "nature": "prix",
                               "source": "Option Finance / AOF ; CNBC 31/12/2025"}},
    "suisse": {"nom": "Suisse", "zone": "europe", "contour": "suisse",
               "indice": {"nom": "SMI", "perf": 14.5, "decimales": 1, "nature": "prix",
                          "source": "SRF 31/12/2025 (clôture 13 267 ; une autre source donne 9,01 %, "
                                    "incohérente avec les niveaux : ignorée)"}},
    "pays-bas": {"nom": "Pays-Bas", "zone": "europe", "contour": "pays-bas",
                 "indice": {"nom": "AEX", "perf": 8.3, "decimales": 1, "nature": "prix, hors dividendes",
                            "source": "FD ; ABM FN-Dow Jones via beleggen.nl (clôture 951,29)"}},
    "etats-unis": {"nom": "États-Unis", "zone": "amerique", "contour": "etats-unis", "indice": _SP_500},
    "canada": {"nom": "Canada", "zone": "amerique", "contour": "canada",
               "indice": {"nom": "S&P/TSX Composite", "perf": 28.2, "decimales": 1,
                          "nature": "prix (rendement total ≈ +31,7 % selon S&P DJI)",
                          "source": "IBISWorld ; Trading Economics (« 28 % ») ; Reuters (« presque 29 % »)"}},
    "japon": {"nom": "Japon", "zone": "asie", "contour": "japon", "indice": _NIKKEI},
    "chine": {"nom": "Chine", "zone": "asie", "contour": "chine", "indice": _SHANGHAI},
    # Pas de contour : trop grossier à la résolution disponible (voir tools/generer_contours.py).
    "hong-kong": {"nom": "Hong Kong", "zone": "asie", "contour": None, "indice": _HANG_SENG},
}

# Carte large « Toute la zone » affichée au-dessus des pays d'une zone.
WIDE_ZONE_LABELS = {"europe": "Toute l'Europe", "amerique": "Toute l'Amérique", "asie": "Toute l'Asie"}

# -- Forex : regroupement par devise ---------------------------------------------
# Une carte par devise présente dans au moins une paire de l'univers. Banque
# centrale : nom seul, JAMAIS de taux directeur (il change). Contours : zone
# monétaire correspondante. Zone euro = 21 pays depuis l'entrée de la
# Bulgarie le 1er janvier 2026 (vérifié le 25/09/2026 : communiqué BCE
# https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.pr260101~c830245e42.en.html),
# identique à ZONE_EURO dans tools/generer_contours.py.
FOREX_CURRENCIES = {
    "EUR": {"nom": "Euro", "banque_centrale": "Banque centrale européenne (BCE)", "contour": "zone-euro"},
    "USD": {"nom": "Dollar américain", "banque_centrale": "Réserve fédérale (Fed)", "contour": "etats-unis"},
    "GBP": {"nom": "Livre sterling", "banque_centrale": "Banque d'Angleterre", "contour": "royaume-uni"},
    "JPY": {"nom": "Yen japonais", "banque_centrale": "Banque du Japon", "contour": "japon"},
    "CHF": {"nom": "Franc suisse", "banque_centrale": "Banque nationale suisse", "contour": "suisse"},
    "AUD": {"nom": "Dollar australien", "banque_centrale": "Banque de réserve d'Australie", "contour": "australie"},
}


def pair_currencies(ticker: str) -> tuple[str, str] | None:
    """("EUR", "USD") pour "EURUSD=X", None si ce n'est pas une paire."""
    code = ticker.upper()
    if len(code) == 8 and code.endswith("=X") and code[:6].isalpha():
        return code[:3], code[3:6]
    return None


# -- Obligations : regroupement par maturité -----------------------------------------
# Descriptions vérifiées le 25/09/2026 sur les fiches officielles des fonds :
# iShares (SHY, IEF, TLT, AGG : « seeks to track an index that includes U.S.
# Treasury bonds with remaining maturities between one and three years »,
# « …seven and ten years », « …greater than twenty years » ; AGG : « U.S.
# investment-grade bonds ») et Vanguard (BND : Bloomberg U.S. Aggregate
# Float Adjusted Index, marché obligataire américain investment grade :
# Trésor, entreprises, titres adossés). BND et AGG ne sont donc PAS des
# fonds d'obligations d'État seulement.
# `zone` : prévu pour un futur niveau « zone » (ETF européens...), mêmes
# cartes à contours, sans refonte.
BOND_GROUPS = {
    "court-terme": {"nom": "Court terme", "tickers": ["SHY"], "zone": "amerique", "maturite": "1 à 3 ans",
                    "description": "Obligations du Trésor américain de 1 à 3 ans (SHY)."},
    "moyen-terme": {"nom": "Moyen terme", "tickers": ["IEF"], "zone": "amerique", "maturite": "7 à 10 ans",
                    "description": "Obligations du Trésor américain de 7 à 10 ans (IEF)."},
    "long-terme": {"nom": "Long terme", "tickers": ["TLT"], "zone": "amerique", "maturite": "plus de 20 ans",
                   "description": "Obligations du Trésor américain de plus de 20 ans (TLT)."},
    "diversifies": {"nom": "Diversifiés", "tickers": ["BND", "AGG"], "zone": "amerique", "maturite": "toutes",
                    "description": "Tout le marché obligataire américain « investment grade » : État, entreprises "
                                   "et titres adossés (BND, AGG)."},
}

# Zone et pays des actifs EXISTANTS (renseignés en base par
# daily_snapshot, sans jamais écraser une valeur déjà présente). Les ETF
# obligataires sont des fonds obligataires américains (voir BOND_GROUPS).
# Crypto, Forex et Matières premières : aucune zone (regroupements propres).
ASSET_PLACES = {
    **{t: ("amerique", "etats-unis") for t in ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN")},
    **{t: ("amerique", "etats-unis") for t in ("TLT", "IEF", "BND", "AGG", "SHY")},
}


def zone_indices(zone_key: str) -> list[dict]:
    return ZONES[zone_key]["indices"]


def country_indices(country_key: str) -> list[dict]:
    return [PAYS[country_key]["indice"]]
