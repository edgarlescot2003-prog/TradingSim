"""Vérifie et exécute la liquidation automatique des positions à levier dont
la perte latente atteint le seuil de marge de maintenance (voir
src/valuation.py, MAINTENANCE_LOSS_RATIO = 80% de la marge engagée), MÊME
quand aucun utilisateur n'a l'app ouverte — lancé par le workflow GitHub
Actions .github/workflows/check-tp-sl.yml, TOUJOURS APRÈS l'étape de
vérification des paliers Take Profit / Stop Loss (voir scripts/check_tp_sl.py) :
si un palier TP/SL et une liquidation se déclenchent tous les deux sur la
même position au même run, le TP/SL (action volontaire de l'utilisateur) est
traité en premier et peut réduire/fermer la position avant que ce script ne
s'exécute. C'est l'ORDRE DES STEPS dans le workflow qui garantit cette
priorité, pas une logique interne à ce script.

Réutilise Portfolio.sell()/cover_short() (les mêmes fonctions que les ventes/
rachats manuels et les paliers TP/SL) pour la clôture — seul le déclencheur
change, aucune nouvelle logique financière dupliquée. Le trade créé est
marqué `is_liquidation=True` (voir Trade, TradeRow) pour être affiché avec le
badge "Liquidation auto" dans l'historique, distinct de "Auto (TP/SL)".

Une liquidation clôture TOUJOURS la position en entier (pas de notion de
palier/pourcentage ici, contrairement au TP/SL) : la marge de maintenance
porte sur la position dans son ensemble.

SANS dépendance à Streamlit, mêmes conventions que check_tp_sl.py (db_core
pour la connexion, portfolio_repo pour charger/sauvegarder, market_data.get_quote
pour les prix courants — actions comme crypto, voir check_tp_sl.py pour le
détail de ce choix).

Robustesse (même logique que check_tp_sl.py) :
- Prix indisponible pour un ticker → les positions concernées sont ignorées
  ce run, retentées au prochain passage (jamais liquidé sur une donnée
  invalide).
- Position déjà fermée/réduite sous le seuil entre-temps (ex : par le run
  TP/SL précédent dans le même workflow) → ignorée, revérifiée sur l'état
  frais du portefeuille juste avant d'agir, pas sur le scan initial.
- Idempotent par construction : une position liquidée est entièrement
  fermée et disparaît de portfolio.positions, donc un run suivant (ou un
  redémarrage accidentel du workflow) ne la retrouve simplement plus parmi
  les positions à levier à vérifier.

Usage (depuis la racine du projet) :
    python -m scripts.check_liquidation
"""

from concurrent.futures import ThreadPoolExecutor
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import db_core, diag_log, market_data as md, market_store, portfolio_repo, valuation
from src.db_models import PositionRow


def _fetch_price_eur(ticker: str) -> tuple[str, tuple[float, float] | None]:
    try:
        # Jamais allow_stale ici : un prix daté (dernier prix connu) ne peut
        # pas déclencher d'exécution automatique, même récent.
        quote = md.get_quote(ticker)
        fx_rate, _ = md.get_fx_rate_info(quote["currency"])
        if not md.is_fresh_for_automation(quote):
            market_store.log_event("automation_skipped_stale_price", ticker=ticker,
                                   market_time=quote.get("market_time"), market_open=quote.get("market_open"))
            print(f"  ⚠️  Prix pas assez frais pour {ticker} (cotation figée ?), liquidation reportée.")
            return ticker, None
        return ticker, (quote["price"] * fx_rate, quote["fetched_at"])
    except md.MarketDataError as e:
        print(f"  ⚠️  Prix indisponible pour {ticker} : {e}")
        return ticker, None


def _fetch_prices(tickers: set[str]) -> dict[str, float | None]:
    if not tickers:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as executor:
        return dict(executor.map(_fetch_price_eur, tickers))


def _is_leveraged(pos_row: PositionRow) -> bool:
    """Repère les positions candidates à la vérification (leverage > 1) sans
    charger le portefeuille complet — filtre initial bon marché, revérifié
    plus précisément sur les dataclasses Position fraîchement chargées dans
    _process_portfolio (voir valuation.is_liquidatable)."""
    if pos_row.margin_eur <= 1e-9:
        return False
    cost_basis = pos_row.quantity * pos_row.avg_price_eur
    return (cost_basis / pos_row.margin_eur) > 1 + 1e-9


def _process_portfolio(
    session: Session, portfolio_id: str, user_id: str, tickers: set[str],
    price_cache: dict[str, tuple[float, float] | None],
) -> None:
    portfolio = portfolio_repo.load_portfolio(session, portfolio_id)
    if portfolio is None:
        print(f"  Portefeuille {portfolio_id} introuvable, ignoré ce run.")
        return

    to_liquidate = []
    for ticker in tickers:
        position = portfolio.positions.get(ticker)
        if position is None:
            continue  # fermée/inversée entre-temps (autre trade, ou run TP/SL précédent du même workflow)
        price_info = price_cache.get(ticker)
        if price_info is None or time.time() - price_info[1] > md.AUTOMATION_MAX_FETCH_AGE_SECONDS:
            continue  # déjà loggé par _fetch_price_eur ; retenté au prochain run
        price_eur = price_info[0]
        if valuation.is_liquidatable(position, price_eur):
            to_liquidate.append((position, price_eur))

    if not to_liquidate:
        return

    executed = 0
    for position, price_eur in to_liquidate:
        qty = position.quantity
        try:
            if position.side == "long":
                portfolio.sell(position.ticker, qty, price_eur, is_liquidation=True)
            else:
                portfolio.cover_short(position.ticker, qty, price_eur, is_liquidation=True)
        except ValueError as e:
            print(f"  Liquidation {position.ticker} échouée ({e}) — reportée au prochain run.")
            continue
        executed += 1
        print(
            f"  LIQUIDATION {position.ticker} ({position.side}) qty={qty:g} @ {price_eur:.2f} € "
            f"(marge engagée {position.margin_eur:,.2f} €)"
        )

    if executed:
        portfolio_repo.save_portfolio(session, portfolio, user_id)
        print(f"  Portefeuille {portfolio_id} sauvegardé ({executed} liquidation(s) exécutée(s)).")


def run() -> None:
    diag_log.log_process_start()
    now_iso = datetime.now(timezone.utc).isoformat()
    engine = db_core.create_engine_from_env()
    db_core.ensure_schema(engine)  # au cas où l'app n'a pas encore redémarré depuis l'ajout de ce schéma
    market_store.configure(lambda: engine, scope="github")  # coupe-circuit propre à l'IP GitHub

    with Session(engine) as session:
        all_positions = session.execute(select(PositionRow)).scalars().all()
        leveraged = [p for p in all_positions if _is_leveraged(p)]

        print(f"[{now_iso}] {len(leveraged)} position(s) à levier sur {len(all_positions)} au total à vérifier.")
        if not leveraged:
            return

        unique_tickers = {p.ticker for p in leveraged}
        price_cache = _fetch_prices(unique_tickers)

        by_portfolio: dict[str, list[PositionRow]] = {}
        for p in leveraged:
            by_portfolio.setdefault(p.portfolio_id, []).append(p)

        for portfolio_id, pos_rows in by_portfolio.items():
            user_id = pos_rows[0].user_id  # toutes les positions d'un même portfolio_id partagent le même user_id
            tickers = {p.ticker for p in pos_rows}
            _process_portfolio(session, portfolio_id, user_id, tickers, price_cache)

    print("Run terminé.")


if __name__ == "__main__":
    run()
