"""Vérification et exécution des ordres à cours limité en attente.

Comme l'application n'a pas de tâche de fond, un franchissement de seuil
pourrait survenir puis se résorber entre deux rafraîchissements sans que le
simple prix courant ne le révèle. Pour ne pas le manquer, chaque vérification
récupère l'historique des prix depuis le dernier instant vérifié
(`order.last_checked_at`) — pas seulement le prix actuel — et cherche le
premier moment où le prix (Haut/Bas de la bougie) a franchi le seuil. L'ordre
est alors exécuté au prix limite, avec l'horodatage réel de ce
franchissement, pas au prix ni à l'heure du rafraîchissement.

Simplifications assumées :
- La granularité de l'historique récupéré dépend de l'ancienneté du dernier
  contrôle (limites d'historique intrajournalier de Yahoo Finance) : 5 min
  sur les 7 derniers jours, 1 h jusqu'à 60 jours, quotidien au-delà. Un
  mouvement plus bref que cette granularité pourrait donc être manqué.
- Le taux de change utilisé pour convertir les prix historiques en euros est
  le taux courant (pas de série de taux de change historique), négligeable
  sur les échelles de temps concernées par un usage normal de l'application.
"""

from datetime import datetime, timedelta, timezone

from . import market_data as md


class _FetchFailed(Exception):
    """L'historique n'a pas pu être récupéré : on retentera plus tard sans
    avancer le point de contrôle, pour ne pas perdre la fenêtre non vérifiée.
    """


def _pick_interval(gap: timedelta) -> str:
    if gap <= timedelta(days=7):
        return "5m"
    if gap <= timedelta(days=60):
        return "1h"
    return "1d"


def _find_trigger(order, fx_rate: float, now: datetime):
    """Cherche, dans l'historique depuis order.last_checked_at, le premier
    instant où le prix (converti en €) franchit le seuil de l'ordre.
    Retourne (event_time_naif_local, prix_eur) si trouvé, sinon None.
    Lève _FetchFailed si l'historique n'a pas pu être récupéré.
    """
    since = datetime.fromisoformat(order.last_checked_at)
    if since >= now:
        return None

    interval = _pick_interval(now - since)
    try:
        hist = md.get_history(order.ticker, interval=interval, start=since)
    except md.MarketDataError as e:
        raise _FetchFailed from e

    if hist.empty:
        raise _FetchFailed
    latest_timestamp = hist.index.max()
    if getattr(latest_timestamp, "tzinfo", None) is None:
        latest_timestamp = latest_timestamp.replace(tzinfo=timezone.utc)
    latest_age = now - latest_timestamp.to_pydatetime()
    if latest_age.total_seconds() > md.MAX_EXECUTION_PRICE_AGE_SECONDS:
        raise _FetchFailed

    is_buy_side = order.action in ("achat", "rachat short")
    for timestamp, row in hist.iterrows():
        if is_buy_side:
            touched = row["Low"] * fx_rate <= order.limit_price_eur
        else:
            touched = row["High"] * fx_rate >= order.limit_price_eur
        if touched:
            event_time = timestamp.to_pydatetime().astimezone().replace(tzinfo=None)
            return event_time, order.limit_price_eur

    return None


def _execute(portfolio, order, price_eur: float, event_time: datetime) -> None:
    if order.action == "achat":
        portfolio.buy(order.ticker, order.name, order.quantity, price_eur, order.currency,
                      leverage=order.leverage, trade_date=event_time)
    elif order.action == "vente":
        portfolio.sell(order.ticker, order.quantity, price_eur, trade_date=event_time)
    elif order.action == "ouverture short":
        portfolio.open_short(order.ticker, order.name, order.quantity, price_eur, order.currency,
                             leverage=order.leverage, trade_date=event_time)
    elif order.action == "rachat short":
        portfolio.cover_short(order.ticker, order.quantity, price_eur, trade_date=event_time)


def process_pending_orders(portfolio) -> list[str]:
    """Exécute les ordres dont le prix cible a été atteint depuis leur
    dernière vérification. Retourne les messages décrivant chaque exécution.
    """
    messages = []
    still_pending = []
    now = datetime.now(timezone.utc)

    for order in portfolio.pending_orders:
        try:
            fx_rate = md.get_fx_rate_to_eur(order.currency)
            trigger = _find_trigger(order, fx_rate, now)
        except (_FetchFailed, md.MarketDataError):
            # Échec temporaire : on retentera avec la même fenêtre au prochain
            # rafraîchissement plutôt que de risquer de manquer un franchissement.
            still_pending.append(order)
            continue

        if trigger is None:
            order.last_checked_at = now.isoformat()
            still_pending.append(order)
            continue

        event_time, price_eur = trigger
        try:
            _execute(portfolio, order, price_eur, event_time)
        except ValueError:
            # Fonds insuffisants au moment de l'exécution : l'ordre reste en
            # attente, mais on ne revérifiera pas la fenêtre déjà franchie.
            order.last_checked_at = now.isoformat()
            still_pending.append(order)
        else:
            messages.append(
                f"Ordre exécuté : {order.action} de {order.quantity:g} x {order.ticker} "
                f"à {price_eur:,.2f} € (seuil franchi le {event_time.strftime('%Y-%m-%d %H:%M')})."
            )

    portfolio.pending_orders = still_pending
    return messages
