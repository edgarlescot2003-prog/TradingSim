"""Vérifie et exécute les paliers Take Profit / Stop Loss déclenchés, MÊME
quand aucun utilisateur n'a l'app ouverte — lancé toutes les 15 minutes par
le workflow GitHub Actions .github/workflows/check-tp-sl.yml (même modèle
que la sauvegarde nocturne).

SANS dépendance à Streamlit (voir la panne du workflow de sauvegarde,
ModuleNotFoundError: streamlit, causée par un import transitif de src/db.py
avant que cette logique ne soit isolée dans db_core.py) : utilise db_core
pour la connexion et portfolio_repo pour charger/sauvegarder les
portefeuilles, exactement comme le fait l'app Streamlit.

Prix courants récupérés via market_data.get_quote (yfinance) pour TOUS les
tickers — y compris crypto, qui y est déjà bien supportée (ex: "BTC-USD") et
utilisée ainsi partout ailleurs dans l'app (valorisation, classement...) ;
Kraken n'est utilisé nulle part dans ce projet pour un prix COURANT, unique-
ment pour l'historique intrajournalier des graphiques (voir kraken_data.py)
— pas de nouveau code non testé introduit ici pour dupliquer ce que
get_quote fait déjà correctement pour les deux classes d'actifs.

Robustesse :
- Un prix indisponible (API down, ticker invalide) ne bloque jamais tout le
  run : le palier concerné est simplement reporté au prochain passage (15
  minutes plus tard), jamais exécuté sur une donnée invalide.
- Un palier dont la position d'origine n'existe plus dans le même sens
  (fermée ou inversée entre-temps par un autre trade) est auto-annulé
  (status="cancelled") plutôt que retenté indéfiniment sans jamais pouvoir
  aboutir.
- Un palier dont la quantité figée dépasse la quantité réellement restante
  (ex : l'utilisateur a vendu une partie de la position manuellement entre
  temps) est exécuté sur la quantité DISPONIBLE, plafonnée, plutôt que
  bloqué ou planté.
- Idempotent par construction : un palier n'est vérifié/exécutable que s'il
  est encore status="active" au moment où ce run le traite ; si le workflow
  tourne deux fois d'affilée par erreur, la 2ᵉ exécution ne retrouve plus
  aucun palier "active" à traiter pour ceux déjà exécutés au 1er passage
  (chaque palier n'est déclenché qu'une fois, jamais deux).

Usage (depuis la racine du projet) :
    python -m scripts.check_tp_sl
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import db_core, diag_log, market_data as md, portfolio_repo, tp_sl
from src.db_models import TpSlOrderRow


def _fetch_price_eur(ticker: str) -> tuple[str, tuple[float, float] | None]:
    try:
        quote = md.get_quote(ticker)
        fx_rate, fx_fetched_at = md.get_fx_rate_info(quote["currency"])
        fetched_at = min(quote["fetched_at"], fx_fetched_at)
        if not md.is_fresh(fetched_at):
            print(f"  ⚠️  Prix périmé pour {ticker}, palier reporté.")
            return ticker, None
        return ticker, (quote["price"] * fx_rate, fetched_at)
    except md.MarketDataError as e:
        print(f"  ⚠️  Prix indisponible pour {ticker} : {e}")
        return ticker, None


def _fetch_prices(tickers: set[str]) -> dict[str, float | None]:
    if not tickers:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(tickers))) as executor:
        return dict(executor.map(_fetch_price_eur, tickers))


def _is_triggered(order: TpSlOrderRow, current_price_eur: float) -> bool:
    """Sens de la comparaison déterminé par (side, kind) :
    - long  + take_profit : le prix est MONTÉ jusqu'à la cible ou au-delà.
    - long  + stop_loss    : le prix est DESCENDU jusqu'à la cible ou en-deçà.
    - short + take_profit : le prix est DESCENDU jusqu'à la cible ou en-deçà
      (le profit d'un short vient d'une baisse).
    - short + stop_loss    : le prix est MONTÉ jusqu'à la cible ou au-delà
      (limite la perte d'un short, qui perd quand le prix monte).
    """
    rising_triggers = (order.side == "long" and order.kind == tp_sl.KIND_TAKE_PROFIT) or (
        order.side == "short" and order.kind == tp_sl.KIND_STOP_LOSS
    )
    if rising_triggers:
        return current_price_eur >= order.target_price_eur
    return current_price_eur <= order.target_price_eur


def _process_portfolio(
    session: Session, portfolio_id: str, orders: list[TpSlOrderRow],
    price_cache: dict[str, tuple[float, float] | None], now_iso: str,
) -> None:
    portfolio = portfolio_repo.load_portfolio(session, portfolio_id)
    if portfolio is None:
        print(f"  Portefeuille {portfolio_id} introuvable, {len(orders)} palier(s) ignoré(s) ce run.")
        return

    triggered = []
    for o in orders:
        price_info = price_cache.get(o.ticker)
        if price_info is None or not md.is_fresh(price_info[1]):
            continue  # déjà loggé par _fetch_price_eur ; reste "active", retenté au prochain run
        price_eur = price_info[0]
        if _is_triggered(o, price_eur):
            triggered.append(o)

    if not triggered:
        return

    # Ordre d'exécution si plusieurs paliers se déclenchent en même temps sur
    # la même position (mouvement de prix violent entre deux vérifications) :
    # du plus proche du prix d'achat moyen au plus loin — choix simple et
    # défendable (voir la doc de conception d'origine, qui laisse ce choix
    # libre) : on "sort" d'abord aux paliers les plus proches du prix
    # d'entrée avant les plus ambitieux/les plus prudents.
    def _distance_to_avg_price(order: TpSlOrderRow) -> float:
        pos = portfolio.positions.get(order.ticker)
        avg = pos.avg_price_eur if pos else order.target_price_eur
        return abs(order.target_price_eur - avg)

    triggered.sort(key=_distance_to_avg_price)

    executed_count = 0
    user_id = orders[0].user_id  # tous les paliers d'un même portfolio_id partagent le même user_id
    for order in triggered:
        existing = portfolio.positions.get(order.ticker)
        if existing is None or existing.side != order.side:
            order.status = tp_sl.STATUS_CANCELLED
            order.executed_at = now_iso
            print(
                f"  Palier {order.id} ({order.ticker}, {tp_sl.KIND_LABELS[order.kind]}) auto-annulé : "
                "position d'origine introuvable ou de sens différent (fermée/inversée entre-temps)."
            )
            continue

        sell_qty = min(order.trigger_quantity, existing.quantity)
        try:
            if order.side == "long":
                portfolio.sell(order.ticker, sell_qty, order.target_price_eur, tp_sl_order_id=order.id)
            else:
                portfolio.cover_short(order.ticker, sell_qty, order.target_price_eur, tp_sl_order_id=order.id)
        except ValueError as e:
            print(f"  Palier {order.id} ({order.ticker}) exécution échouée ({e}) — reporté au prochain run.")
            continue

        order.status = tp_sl.STATUS_EXECUTED
        order.executed_at = now_iso
        order.executed_price_eur = order.target_price_eur
        executed_count += 1
        print(
            f"  Palier {order.id} EXÉCUTÉ : {tp_sl.KIND_LABELS[order.kind]} {order.ticker} "
            f"qty={sell_qty:g} @ {order.target_price_eur:.2f} €"
            + (f" (plafonné, {order.trigger_quantity:g} visé initialement)" if sell_qty < order.trigger_quantity else "")
        )

    portfolio_repo.save_portfolio(session, portfolio, user_id)
    print(
        f"  Portefeuille {portfolio_id} sauvegardé "
        f"({executed_count} exécuté(s) sur {len(triggered)} déclenché(s))."
    )


def run() -> None:
    diag_log.log_process_start()
    now_iso = datetime.now(timezone.utc).isoformat()
    engine = db_core.create_engine_from_env()
    db_core.ensure_schema(engine)  # au cas où l'app n'a pas encore redémarré depuis l'ajout de ce schéma

    with Session(engine) as session:
        active_orders = session.execute(
            select(TpSlOrderRow).where(TpSlOrderRow.status == tp_sl.STATUS_ACTIVE)
        ).scalars().all()

        print(f"[{now_iso}] {len(active_orders)} palier(s) TP/SL actif(s) à vérifier.")
        if not active_orders:
            return

        unique_tickers = {o.ticker for o in active_orders}
        price_cache = _fetch_prices(unique_tickers)

        by_portfolio: dict[str, list[TpSlOrderRow]] = {}
        for o in active_orders:
            by_portfolio.setdefault(o.portfolio_id, []).append(o)

        for portfolio_id, orders in by_portfolio.items():
            _process_portfolio(session, portfolio_id, orders, price_cache, now_iso)

    print("Run terminé.")


if __name__ == "__main__":
    run()
