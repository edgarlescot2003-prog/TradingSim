"""Modèle du portefeuille fictif : cash, positions (longues et courtes) avec
effet de levier, ordres à cours limité en attente, historique des trades.

Toutes les valeurs monétaires sont stockées en euros (devise unique du projet).

Modèle de marge (pour supporter le levier) : ouvrir ou augmenter une position
ne débite du cash que la marge nécessaire (notionnel / levier), pas le
notionnel complet. Le P&L reste calculé sur la quantité totale (donc amplifié
par rapport à la marge engagée, ce qui est l'effet recherché du levier).
Fermer/réduire une position rend la fraction de marge correspondante et
crédite le P&L réalisé. Un levier de x1 revient exactement au comportement
sans levier (marge = notionnel).
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class Position:
    ticker: str
    name: str
    quantity: float
    avg_price_eur: float
    currency: str  # devise native de l'actif, pour affichage
    entry_date: str  # date du premier trade sur cette position (YYYY-MM-DD)
    side: str = "long"  # "long" ou "short"
    margin_eur: float = 0.0  # cash effectivement engagé sur cette position


@dataclass
class Trade:
    date: str  # horodatage ISO du trade
    ticker: str
    name: str
    side: str  # "long" ou "short"
    action: str  # "achat", "vente", "ouverture short", "rachat short"
    quantity: float
    price_eur: float
    currency: str
    leverage: float = 1.0
    realized_pnl_eur: float | None = None  # renseigné uniquement pour les clôtures
    # Renseigné uniquement si ce trade a été déclenché automatiquement par un
    # palier Take Profit / Stop Loss (voir tp_sl.py, scripts/check_tp_sl.py) :
    # id du TpSlOrderRow d'origine, None pour un ordre manuel.
    tp_sl_order_id: str | None = None
    # Vrai uniquement si cette clôture est une liquidation automatique par
    # marge de maintenance (voir valuation.is_liquidatable,
    # scripts/check_liquidation.py) — mutuellement exclusif avec
    # tp_sl_order_id en pratique (une position est liquidée ou sortie par un
    # palier, jamais les deux sur le même trade).
    is_liquidation: bool = False
    # Traçabilité des ordres manuels (voir ui_trading._tag_last_trade) : âge
    # du prix utilisé au moment de l'exécution (secondes) et sa source
    # ("yahoo" = prix live, "last_known" = prix daté pendant une pause de la
    # source). None pour les trades antérieurs, TP/SL, liquidations, ordres
    # limites (exécutés au prix limite).
    price_age_seconds: float | None = None
    price_source: str | None = None


@dataclass
class PendingOrder:
    id: str
    ticker: str
    name: str
    action: str  # "achat", "vente", "ouverture short", "rachat short"
    quantity: float
    limit_price_eur: float
    currency: str
    leverage: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # Horodatage UTC (timezone-aware) du dernier instant jusqu'où l'historique
    # de prix a été vérifié pour cet ordre. Sert de point de départ au balayage
    # dans order_engine ; distinct de created_at (naïf, local, pour affichage)
    # car les appels yfinance avec `start=` exigent un datetime timezone-aware
    # pour être correctement interprétés (un datetime naïf est pris pour
    # l'heure locale de la place boursière, pas celle de l'utilisateur).
    last_checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Portfolio:
    initial_capital: float
    cash: float
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Portefeuille"
    positions: dict[str, Position] = field(default_factory=dict)
    history: list[Trade] = field(default_factory=list)
    pending_orders: list[PendingOrder] = field(default_factory=list)
    # Un point {"date": iso, "value_eur": float} par jour d'utilisation environ
    # (voir record_value_snapshot) : sert à tracer la courbe d'évolution.
    value_history: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # Portefeuille compté pour le classement (un seul par utilisateur,
    # définitif — voir auth.set_official_portfolio). Faux par défaut : seul
    # le tout premier portefeuille d'un nouveau compte le passe à True à la
    # création (app.py), les suivants restent "fun/test", hors classement.
    is_official: bool = False

    # -- Position longue -----------------------------------------------------

    def buy(self, ticker: str, name: str, quantity: float, price_eur: float, currency: str,
            leverage: float = 1.0, trade_date: datetime | None = None) -> None:
        """Ouvre ou augmente une position longue sur `ticker`.

        `trade_date` permet d'horodater le trade dans le passé (utilisé par
        order_engine quand un ordre à cours limité s'est déclenché à un
        instant historique) ; par défaut, l'instant présent.
        """
        if quantity <= 0:
            raise ValueError("La quantité doit être supérieure à 0.")
        if leverage <= 0:
            raise ValueError("Le levier doit être supérieur à 0.")

        existing = self.positions.get(ticker)
        if existing and existing.side == "short":
            raise ValueError(
                f"Tu as une position courte ouverte sur {ticker}. "
                "Rachète-la (Cover) avant d'acheter en position longue."
            )

        margin = (quantity * price_eur) / leverage
        if margin > self.cash + 1e-9:
            raise ValueError(
                f"Fonds insuffisants : marge nécessaire de {margin:,.2f} € (levier x{leverage:g}) "
                f"pour {self.cash:,.2f} € de cash disponible."
            )

        trade_dt = trade_date or datetime.now()
        if existing:
            total_qty = existing.quantity + quantity
            existing.avg_price_eur = (
                existing.avg_price_eur * existing.quantity + price_eur * quantity
            ) / total_qty
            existing.quantity = total_qty
            existing.margin_eur += margin
        else:
            self.positions[ticker] = Position(
                ticker=ticker, name=name, quantity=quantity, avg_price_eur=price_eur,
                currency=currency, entry_date=trade_dt.strftime("%Y-%m-%d"), side="long",
                margin_eur=margin,
            )

        self.cash -= margin
        self._log_trade(ticker, name, "long", "achat", quantity, price_eur, currency, leverage,
                         trade_date=trade_dt)

    def sell(self, ticker: str, quantity: float, price_eur: float, trade_date: datetime | None = None,
             tp_sl_order_id: str | None = None, is_liquidation: bool = False) -> float:
        """Réduit ou clôture une position longue. Retourne le P&L réalisé (€).

        `tp_sl_order_id` : renseigné uniquement quand cette vente est
        déclenchée automatiquement par un palier Take Profit / Stop Loss
        (voir scripts/check_tp_sl.py), pour que le trade en garde la trace.
        `is_liquidation` : idem pour une liquidation automatique par marge de
        maintenance (voir scripts/check_liquidation.py).
        """
        existing = self.positions.get(ticker)
        if not existing or existing.side != "long":
            raise ValueError(f"Aucune position longue sur {ticker} à vendre.")
        if quantity <= 0:
            raise ValueError("La quantité doit être supérieure à 0.")
        if quantity > existing.quantity + 1e-9:
            raise ValueError(
                f"Tu ne peux pas vendre {quantity:g} : tu ne détiens que {existing.quantity:g} {ticker}."
            )

        fraction = quantity / existing.quantity
        margin_released = existing.margin_eur * fraction
        realized_pnl = (price_eur - existing.avg_price_eur) * quantity

        self.cash += margin_released + realized_pnl
        existing.quantity -= quantity
        existing.margin_eur -= margin_released
        if existing.quantity <= 1e-9:
            del self.positions[ticker]

        self._log_trade(ticker, existing.name, "long", "vente", quantity, price_eur,
                         existing.currency, 1.0, realized_pnl, trade_date=trade_date,
                         tp_sl_order_id=tp_sl_order_id, is_liquidation=is_liquidation)
        return realized_pnl

    # -- Position courte (short) ---------------------------------------------

    def open_short(self, ticker: str, name: str, quantity: float, price_eur: float, currency: str,
                    leverage: float = 1.0, trade_date: datetime | None = None) -> None:
        """Ouvre ou augmente une position courte sur `ticker`."""
        if quantity <= 0:
            raise ValueError("La quantité doit être supérieure à 0.")
        if leverage <= 0:
            raise ValueError("Le levier doit être supérieur à 0.")

        existing = self.positions.get(ticker)
        if existing and existing.side == "long":
            raise ValueError(
                f"Tu as une position longue ouverte sur {ticker}. "
                "Vends-la avant d'ouvrir une position courte."
            )

        margin = (quantity * price_eur) / leverage
        if margin > self.cash + 1e-9:
            raise ValueError(
                f"Fonds insuffisants : marge nécessaire de {margin:,.2f} € (levier x{leverage:g}) "
                f"pour {self.cash:,.2f} € de cash disponible."
            )

        trade_dt = trade_date or datetime.now()
        if existing:
            total_qty = existing.quantity + quantity
            existing.avg_price_eur = (
                existing.avg_price_eur * existing.quantity + price_eur * quantity
            ) / total_qty
            existing.quantity = total_qty
            existing.margin_eur += margin
        else:
            self.positions[ticker] = Position(
                ticker=ticker, name=name, quantity=quantity, avg_price_eur=price_eur,
                currency=currency, entry_date=trade_dt.strftime("%Y-%m-%d"), side="short",
                margin_eur=margin,
            )

        self.cash -= margin
        self._log_trade(ticker, name, "short", "ouverture short", quantity, price_eur, currency, leverage,
                         trade_date=trade_dt)

    def cover_short(self, ticker: str, quantity: float, price_eur: float,
                     trade_date: datetime | None = None, tp_sl_order_id: str | None = None,
                     is_liquidation: bool = False) -> float:
        """Réduit ou clôture (rachète) une position courte. Retourne le P&L réalisé (€).

        `tp_sl_order_id`, `is_liquidation` : voir sell() ci-dessus.
        """
        existing = self.positions.get(ticker)
        if not existing or existing.side != "short":
            raise ValueError(f"Aucune position courte sur {ticker} à racheter.")
        if quantity <= 0:
            raise ValueError("La quantité doit être supérieure à 0.")
        if quantity > existing.quantity + 1e-9:
            raise ValueError(
                f"Tu ne peux pas racheter {quantity:g} : la position courte n'est que de {existing.quantity:g}."
            )

        fraction = quantity / existing.quantity
        margin_released = existing.margin_eur * fraction
        realized_pnl = (existing.avg_price_eur - price_eur) * quantity

        self.cash += margin_released + realized_pnl
        existing.quantity -= quantity
        existing.margin_eur -= margin_released
        if existing.quantity <= 1e-9:
            del self.positions[ticker]

        self._log_trade(ticker, existing.name, "short", "rachat short", quantity, price_eur,
                         existing.currency, 1.0, realized_pnl, trade_date=trade_date,
                         tp_sl_order_id=tp_sl_order_id, is_liquidation=is_liquidation)
        return realized_pnl

    # -- Ordres à cours limité -------------------------------------------------

    def place_limit_order(self, ticker: str, name: str, action: str, quantity: float,
                           limit_price_eur: float, currency: str, leverage: float = 1.0) -> None:
        """Enregistre un ordre en attente, exécuté automatiquement (voir
        order_engine.process_pending_orders) quand le prix de marché atteint
        `limit_price_eur`. Une vérification de faisabilité est faite à la
        pose de l'ordre, mais le cash n'est pas réservé/bloqué entre-temps :
        il est revérifié au moment de l'exécution.
        """
        if quantity <= 0:
            raise ValueError("La quantité doit être supérieure à 0.")
        if limit_price_eur <= 0:
            raise ValueError("Le prix cible doit être supérieur à 0.")
        if leverage <= 0:
            raise ValueError("Le levier doit être supérieur à 0.")

        if action in ("achat", "ouverture short"):
            margin = (quantity * limit_price_eur) / leverage
            if margin > self.cash + 1e-9:
                raise ValueError(
                    f"Fonds insuffisants pour cet ordre : marge nécessaire de {margin:,.2f} € "
                    f"(levier x{leverage:g}) pour {self.cash:,.2f} € de cash disponible."
                )
        elif action == "vente":
            existing = self.positions.get(ticker)
            if not existing or existing.side != "long" or quantity > existing.quantity + 1e-9:
                raise ValueError(f"Position longue insuffisante sur {ticker} pour placer cet ordre de vente.")
        elif action == "rachat short":
            existing = self.positions.get(ticker)
            if not existing or existing.side != "short" or quantity > existing.quantity + 1e-9:
                raise ValueError(f"Position courte insuffisante sur {ticker} pour placer cet ordre de rachat.")
        else:
            raise ValueError(f"Type d'ordre inconnu : {action}")

        self.pending_orders.append(PendingOrder(
            id=str(uuid.uuid4()), ticker=ticker, name=name, action=action, quantity=quantity,
            limit_price_eur=limit_price_eur, currency=currency, leverage=leverage,
        ))

    def cancel_order(self, order_id: str) -> None:
        before = len(self.pending_orders)
        self.pending_orders = [o for o in self.pending_orders if o.id != order_id]
        if len(self.pending_orders) == before:
            raise ValueError("Ordre introuvable (peut-être déjà exécuté ou annulé).")

    # -- Suivi de performance et cycle de vie -----------------------------------

    def record_value_snapshot(self, total_value_eur: float) -> None:
        """Enregistre un point de la courbe de valeur du portefeuille. Un seul
        point est conservé par jour calendaire (mis à jour tant qu'on reste
        le même jour) : l'application n'a pas de tâche de fond, donc la
        granularité réelle dépend de la fréquence à laquelle l'utilisateur
        l'ouvre.
        """
        now_iso = datetime.now().isoformat()
        today = now_iso[:10]
        if self.value_history and self.value_history[-1]["date"][:10] == today:
            self.value_history[-1] = {"date": now_iso, "value_eur": total_value_eur}
        else:
            self.value_history.append({"date": now_iso, "value_eur": total_value_eur})

    def reset(self) -> None:
        """Remet ce portefeuille à son état initial : cash au capital de
        départ, positions/historique/ordres/courbe de valeur vidés. L'id, le
        nom et le capital de départ sont conservés.
        """
        self.cash = self.initial_capital
        self.positions = {}
        self.history = []
        self.pending_orders = []
        self.value_history = []

    # -- Interne ---------------------------------------------------------------

    def _log_trade(self, ticker, name, side, action, quantity, price_eur, currency,
                    leverage=1.0, realized_pnl_eur=None, trade_date: datetime | None = None,
                    tp_sl_order_id: str | None = None, is_liquidation: bool = False) -> None:
        trade_dt = trade_date or datetime.now()
        self.history.append(Trade(
            date=trade_dt.isoformat(), ticker=ticker, name=name, side=side,
            action=action, quantity=quantity, price_eur=price_eur, currency=currency,
            leverage=leverage, realized_pnl_eur=realized_pnl_eur, tp_sl_order_id=tp_sl_order_id,
            is_liquidation=is_liquidation,
        ))

    # -- Sérialisation -----------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Portfolio":
        positions = {}
        for ticker, pos in data.get("positions", {}).items():
            pos = dict(pos)
            if "margin_eur" not in pos:
                # Migration des portefeuilles créés avant l'introduction du levier
                # (Phase 3) : les positions longues avaient déjà débité le
                # notionnel complet du cash (équivalent à une marge = notionnel,
                # levier x1) ; les positions courtes avaient au contraire crédité
                # le notionnel au cash à l'ouverture (aucune marge distincte n'a
                # donc été prélevée, marge = 0 pour rester cohérent avec le cash
                # déjà enregistré).
                pos["margin_eur"] = (
                    pos["quantity"] * pos["avg_price_eur"] if pos.get("side", "long") == "long" else 0.0
                )
            positions[ticker] = Position(**pos)

        history = [Trade(**t) for t in data.get("history", [])]
        pending_orders = [PendingOrder(**o) for o in data.get("pending_orders", [])]

        return Portfolio(
            initial_capital=data["initial_capital"],
            cash=data["cash"],
            id=data.get("id") or str(uuid.uuid4()),
            name=data.get("name") or "Portefeuille principal",
            positions=positions,
            history=history,
            pending_orders=pending_orders,
            value_history=data.get("value_history", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
        )


# Nombre max de portefeuilles par utilisateur (1 officiel + quelques-uns pour
# tester/s'amuser) : impact réseau/DB jugé négligeable à l'échelle de ce
# projet (le cache de prix est partagé entre tickers, pas par portefeuille),
# mais une limite raisonnable évite une dérive incontrôlée du nombre de
# lignes en base.
MAX_PORTFOLIOS_PER_USER = 3
