"""Configuration statique de la navigation de l'onglet Trading (zones,
indices de référence, devises, maturités), SANS dépendance à Streamlit ni au
réseau.

Performances d'indices = valeurs FIGÉES de l'année ANNEE_PERF, recopiées
telles quelles depuis leurs sources (annexe B du prompt de conception,
recueillies par Claude (chat) le 24/09/2026 ; KOSPI, Nifty 50 et TAIEX
recueillis par Claude Code le 25/09/2026). Aucune requête, aucun
rafraîchissement : ce sont des variations d'indices (devise locale, indice
« prix » sauf mention contraire), pas le rendement d'un placement.

MISE À JOUR ANNUELLE (chaque janvier) : changer ANNEE_PERF et TOUTES les
valeurs `perf` avec leurs sources, en une seule modification de ce fichier.
Ne jamais « corriger » une valeur sans source.

Navigation des actions (26/09/2026) : Accueil → Actions → ZONE → liste (plus
de niveau pays ; le pays reste affiché dans la liste). Disponibilité d'une
zone (carte cliquable ou « Bientôt ») : jamais écrite ici, calculée depuis la
table des prix indicatifs (daily_snapshot.available_places).
"""

from .asset_universe import ASSET_PLACES  # noqa: F401 (réexporté pour daily_snapshot et la fiche)

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
_TSX = {"nom": "S&P/TSX Composite", "perf": 28.2, "decimales": 1,
        "nature": "prix (rendement total ≈ +31,7 % selon S&P DJI)",
        "source": "IBISWorld ; Trading Economics (« 28 % ») ; Reuters (« presque 29 % »)"}
_NIKKEI = {"nom": "Nikkei 225", "perf": 26.2, "decimales": 1, "nature": "prix",
           "source": "Club Patrimoine ; Kyodo / Nikkei Asia (« 26 % », clôture 50 339,48)"}
_KOSPI = {"nom": "KOSPI", "perf": 75.6, "decimales": 1, "nature": "prix",
          "source": "Korea Herald (clôture 4 214,17 contre 2 399 fin 2024) ; Korea JoongAng Daily (« 76 % ») "
                    "— https://www.koreaherald.com/article/10646103"}
_NIFTY = {"nom": "Nifty 50", "perf": 10.51, "decimales": 1, "nature": "prix",
          "source": "Samco (+10,51 %, clôture 26 129,60) ; Business Standard (« environ 10 % »)"}
_TAIEX = {"nom": "TAIEX", "perf": 25.73, "decimales": 1, "nature": "prix",
          "source": "Focus Taiwan 31/12/2025 (+25,73 %, clôture 28 963,60) ; Taipei Times 01/01/2026"}

ZONES = {
    "europe": {
        "nom": "Europe", "contour": "europe",
        "description": "Les 30 plus grandes capitalisations européennes.",
        "indices": [_STOXX_600],
    },
    "amerique": {
        "nom": "Amérique", "contour": "amerique",
        "description": "Les 25 plus grandes capitalisations américaines et 5 canadiennes.",
        "indices": [_SP_500, _TSX],
    },
    "asie": {
        "nom": "Asie", "contour": "asie",
        "description": "Les 30 plus grandes capitalisations du Japon, de Taïwan, d'Inde et de Corée du Sud.",
        "indices": [_NIKKEI, _TAIEX, _NIFTY, _KOSPI],
    },
}

# Indices des anciennes cartes pays (niveau retiré le 26/09/2026), conservés
# avec leurs sources pour une éventuelle V2 par pays :
# CAC 40 +10,42 % (Option Finance / AOF 31/12/2025) ; DAX 40 +23,01 %,
# dividendes inclus (Option Finance / AOF) ; FTSE 100 +21,51 % (AOF, CNBC) ;
# SMI +14,5 % (SRF) ; AEX +8,3 % (FD, beleggen.nl) ; IBEX 35 +49,27 %
# (Trading Economics, clôture 17 307,80) ; FTSE MIB +31,4 % (Il Denaro,
# clôture 45 005,02) ; Hang Seng +27,77 % (Global Times, SCMP) ; Shanghai
# Composite +18,41 % (Global Times, People's Daily).


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
    "CAD": {"nom": "Dollar canadien", "banque_centrale": "Banque du Canada", "contour": "canada"},
    "NZD": {"nom": "Dollar néo-zélandais", "banque_centrale": "Banque de réserve de Nouvelle-Zélande",
            "contour": "nouvelle-zelande"},
}


def pair_currencies(ticker: str) -> tuple[str, str] | None:
    """("EUR", "USD") pour "EURUSD=X", None si ce n'est pas une paire."""
    code = ticker.upper()
    if len(code) == 8 and code.endswith("=X") and code[:6].isalpha():
        return code[:3], code[3:6]
    return None


# -- Obligations : 6 cartes -------------------------------------------------------
# Descriptions vérifiées sur les fiches officielles des fonds :
# - 25/09/2026 : iShares SHY (Trésor 1-3 ans), IEF (7-10 ans), TLT (plus de
#   20 ans), AGG (« U.S. investment-grade bonds ») ; Vanguard BND (Bloomberg
#   U.S. Aggregate Float Adjusted : Trésor, entreprises, titres adossés).
# - 26/09/2026 : iShares SGOV (bons du Trésor 0-3 mois), IEI (3-7 ans), TLH
#   (10-20 ans), GOVT (Trésor, toutes maturités), TIP (Trésor indexé sur
#   l'inflation), MUB (municipales investment grade), LQD (entreprises en
#   dollars investment grade), HYG (entreprises en dollars à haut rendement),
#   EMB (émergents en dollars) ; SPDR JNK (haut rendement américain) ;
#   Vanguard BNDX (obligations investment grade hors États-Unis, couvertes
#   contre le change).
# `zone` : prévu pour un futur niveau « zone » (ETF européens...), mêmes
# cartes à contours, sans refonte.
BOND_GROUPS = {
    "court-terme": {"nom": "Court terme", "tickers": ["SGOV", "SHY"], "zone": "amerique",
                    "description": "Trésor américain de 0 à 3 mois (SGOV) et de 1 à 3 ans (SHY)."},
    "moyen-terme": {"nom": "Moyen terme", "tickers": ["IEI", "IEF"], "zone": "amerique",
                    "description": "Trésor américain de 3 à 7 ans (IEI) et de 7 à 10 ans (IEF)."},
    "long-terme": {"nom": "Long terme", "tickers": ["TLH", "TLT"], "zone": "amerique",
                   "description": "Trésor américain de 10 à 20 ans (TLH) et de plus de 20 ans (TLT)."},
    "diversifies": {"nom": "Diversifiés", "tickers": ["GOVT", "BND", "AGG", "MUB"], "zone": "amerique",
                    "description": "Tout le Trésor américain (GOVT), le marché obligataire américain « investment "
                                   "grade » : État, entreprises et titres adossés (BND, AGG), et les "
                                   "obligations municipales (MUB)."},
    "entreprises": {"nom": "Entreprises", "tickers": ["LQD", "HYG", "JNK"], "zone": "amerique",
                    "description": "Obligations d'entreprises américaines « investment grade » (LQD) et à "
                                   "haut rendement (HYG, JNK)."},
    "inflation-international": {"nom": "Inflation & international", "tickers": ["TIP", "BNDX", "EMB"],
                                "zone": "amerique",
                                "description": "Trésor américain indexé sur l'inflation (TIP), obligations "
                                               "internationales hors États-Unis couvertes contre le change (BNDX) "
                                               "et pays émergents en dollars (EMB)."},
}


def zone_indices(zone_key: str) -> list[dict]:
    return ZONES[zone_key]["indices"]
