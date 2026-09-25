"""Diagnostic en LECTURE SEULE : l'endpoint Yahoo v7/finance/quote répond-il
aujourd'hui pour plusieurs symboles en UNE requête ?

Rien n'est intégré à l'app (décision reportée à la phase 2, actifs détenus).
Exactement 3 requêtes, jamais de boucle ni de nouvel essai :
  1. https://fc.yahoo.com            -> cookie de session
  2. v1/test/getcrumb                -> jeton "crumb" associé au cookie
  3. v7/finance/quote?symbols=...    -> 6 symboles en une requête
Aucune dépendance à Streamlit ni à la base. Utilisé depuis un PC
(`python scripts/diagnostic_quote_groupe.py`) et par le workflow manuel
.github/workflows/diagnostic-quote-groupe.yml.

Sur GitHub Actions, le résultat est aussi publié en annotations (::notice) :
lisibles sans authentification via l'API publique des check-runs d'un dépôt
public, contrairement aux logs complets.
"""

import json
import os
import time

import requests

SYMBOLS = ["AAPL", "MC.PA", "GC=F", "CL=F", "EURUSD=X", "TLT"]
FIELDS = ["regularMarketPrice", "regularMarketPreviousClose", "regularMarketChangePercent",
          "regularMarketTime", "currency", "marketState"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def run() -> dict:
    report = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": {}, "symbols": {}}
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        r1 = session.get("https://fc.yahoo.com", timeout=15, allow_redirects=True)
        report["steps"]["cookie"] = {"http": r1.status_code, "cookies": sorted(session.cookies.keys())}
    except Exception as e:
        report["steps"]["cookie"] = {"error": repr(e)}

    crumb = None
    try:
        r2 = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15)
        crumb = r2.text.strip() if r2.status_code == 200 else None
        report["steps"]["crumb"] = {"http": r2.status_code, "obtained": bool(crumb),
                                    "body_start": None if crumb else r2.text[:120]}
    except Exception as e:
        report["steps"]["crumb"] = {"error": repr(e)}

    try:
        params = {"symbols": ",".join(SYMBOLS)}
        if crumb:
            params["crumb"] = crumb
        r3 = session.get("https://query1.finance.yahoo.com/v7/finance/quote", params=params, timeout=15)
        now = time.time()
        step = {"http": r3.status_code}
        if r3.status_code == 200:
            results = (r3.json().get("quoteResponse") or {}).get("result") or []
            step["symbols_returned"] = len(results)
            for item in results:
                market_time = item.get("regularMarketTime")
                report["symbols"][item.get("symbol")] = {
                    "missing_fields": [f for f in FIELDS if item.get(f) is None],
                    "price": item.get("regularMarketPrice"),
                    "currency": item.get("currency"),
                    "marketState": item.get("marketState"),
                    "age_seconds": round(now - market_time) if isinstance(market_time, (int, float)) else None,
                }
        else:
            step["body_start"] = r3.text[:200]
        report["steps"]["quote"] = step
    except Exception as e:
        report["steps"]["quote"] = {"error": repr(e)}
    return report


def _annotate(report: dict) -> None:
    quote = report["steps"].get("quote", {})
    print(f"::notice title=quote-groupe-resume::cookie={report['steps'].get('cookie', {}).get('http')} "
          f"crumb={report['steps'].get('crumb', {}).get('http')} quote={quote.get('http')} "
          f"symboles={quote.get('symbols_returned')} erreur={quote.get('error') or quote.get('body_start') or '-'}")
    for symbol, info in report["symbols"].items():
        print(f"::notice title=quote-{symbol}::age_s={info['age_seconds']} etat={info['marketState']} "
              f"devise={info['currency']} manquants={','.join(info['missing_fields']) or 'aucun'}")


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        _annotate(result)
