"""Schéma SQLAlchemy (PostgreSQL / Supabase).

Chaque table métier porte un `user_id` (pas seulement via une jointure sur
`portfolio_id`), pour que l'isolation des données par utilisateur — et
d'éventuelles policies RLS Postgres plus tard — reste simple à exprimer
directement sur chaque table.

La table `users` (comptes, rôles) est créée dès maintenant même si
l'authentification n'arrive qu'à la phase suivante : ça évite une nouvelle
migration de schéma quand elle sera branchée, et permet de faire pointer un
utilisateur "propriétaire" par défaut sur les données existantes dès cette
phase.

Les horodatages (dates, created_at...) restent stockés en texte ISO 8601,
comme dans les dataclasses historiques (Trade.date, PendingOrder.created_at,
value_history...) : ça évite toute divergence de comportement entre
l'ancien stockage JSON et celui-ci, la logique métier qui les manipule
(order_engine, valuation...) n'a pas besoin de changer.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    username = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="standard")  # admin | contributor | standard
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(String, nullable=False, default=_now_iso)
    # Dernier portefeuille consulté, retrouvé automatiquement à la reconnexion.
    # use_alter=True : "users" et "portfolios" se référencent mutuellement
    # (portfolios.user_id -> users.id), SQLAlchemy crée donc cette contrainte
    # via un ALTER TABLE séparé une fois les deux tables en place.
    active_portfolio_id = Column(
        UUID(as_uuid=False),
        ForeignKey("portfolios.id", use_alter=True, name="fk_users_active_portfolio"),
        nullable=True,
    )


class PortfolioRow(Base):
    __tablename__ = "portfolios"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    initial_capital = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    created_at = Column(String, nullable=False, default=_now_iso)
    # Un seul portefeuille officiel par utilisateur (celui qui compte pour le
    # classement) : désigné automatiquement au tout premier portefeuille créé
    # pour un nouveau compte (voir app.py), ou manuellement une fois par
    # l'Admin pour un compte préexistant (voir auth.set_official_portfolio) —
    # jamais modifiable ensuite depuis l'interface standard. `create_all` ne
    # modifie pas les tables déjà existantes : voir la migration ALTER TABLE
    # dans db.init_db() pour les bases créées avant l'ajout de cette colonne.
    is_official = Column(Boolean, nullable=False, default=False)


class PositionRow(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker", name="uq_position_portfolio_ticker"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    portfolio_id = Column(UUID(as_uuid=False), ForeignKey("portfolios.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String, nullable=False)
    name = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    avg_price_eur = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    entry_date = Column(String, nullable=False)
    side = Column(String, nullable=False, default="long")
    margin_eur = Column(Float, nullable=False, default=0.0)


class TradeRow(Base):
    __tablename__ = "trades"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    portfolio_id = Column(UUID(as_uuid=False), ForeignKey("portfolios.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    date = Column(String, nullable=False)
    ticker = Column(String, nullable=False)
    name = Column(String, nullable=False)
    side = Column(String, nullable=False)
    action = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price_eur = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    leverage = Column(Float, nullable=False, default=1.0)
    realized_pnl_eur = Column(Float, nullable=True)
    # Renseigné uniquement si ce trade a été déclenché automatiquement par un
    # palier Take Profit / Stop Loss (voir TpSlOrderRow, tp_sl.py) plutôt que
    # par un ordre manuel — sert à l'afficher distinctement dans l'historique
    # (ui_portfolio.py, ui_history.py).
    tp_sl_order_id = Column(UUID(as_uuid=False), ForeignKey("tp_sl_orders.id"), nullable=True)
    # Vrai uniquement si cette clôture est une liquidation automatique par
    # marge de maintenance (voir valuation.is_liquidatable,
    # scripts/check_liquidation.py) — badge "Liquidation auto" distinct de
    # "Auto (TP/SL)" dans l'historique (ui_portfolio.py, ui_history.py).
    is_liquidation = Column(Boolean, nullable=False, default=False)
    # Traçabilité des ordres manuels exécutés (voir Trade.price_age_seconds) :
    # permet de repérer, et au besoin d'écarter, un ordre passé sur un prix
    # daté. Colonnes nullables ajoutées par ALTER (db_core.ensure_schema).
    price_age_seconds = Column(Float, nullable=True)
    price_source = Column(String, nullable=True)


class PendingOrderRow(Base):
    __tablename__ = "pending_orders"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    portfolio_id = Column(UUID(as_uuid=False), ForeignKey("portfolios.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String, nullable=False)
    name = Column(String, nullable=False)
    action = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    limit_price_eur = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    leverage = Column(Float, nullable=False, default=1.0)
    created_at = Column(String, nullable=False, default=_now_iso)
    last_checked_at = Column(String, nullable=False, default=_now_iso)


class ValueHistoryRow(Base):
    __tablename__ = "value_history"
    __table_args__ = (UniqueConstraint("portfolio_id", "date", name="uq_value_history_portfolio_date"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    portfolio_id = Column(UUID(as_uuid=False), ForeignKey("portfolios.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    date = Column(String, nullable=False)
    value_eur = Column(Float, nullable=False)


class MarketPriceSnapshotRow(Base):
    """Prix en euros collecté par le workflow de contrôle périodique.

    Cette table est la seule source utilisée par la page Admin News : son
    affichage ne déclenche donc jamais d'appel à une API de marché.
    """
    __tablename__ = "market_price_snapshots"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    ticker = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, default="")
    recorded_at = Column(String, nullable=False, index=True)
    price_eur = Column(Float, nullable=False)


class PortfolioValueSnapshotRow(Base):
    """Valeur périodique des portefeuilles officiels pour le tableau Admin."""
    __tablename__ = "portfolio_value_snapshots"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    portfolio_id = Column(UUID(as_uuid=False), ForeignKey("portfolios.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    recorded_at = Column(String, nullable=False, index=True)
    value_eur = Column(Float, nullable=False)


class ApiCircuitStateRow(Base):
    """Coupe-circuit par source de marché (yahoo, kraken), partagé entre
    processus — voir market_store.py. Même définition que le
    CREATE TABLE IF NOT EXISTS de market_store._CREATE_TABLES_SQL (qui crée la
    table même si l'app n'a pas encore redémarré depuis son ajout)."""
    __tablename__ = "api_circuit_state"

    source = Column(String, primary_key=True)
    blocked_until = Column(String, nullable=True)  # ISO 8601 UTC, NULL = pas de pause
    consecutive_failures = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)
    updated_at = Column(String, nullable=False, default=_now_iso)


class LastKnownPriceRow(Base):
    """Dernier prix obtenu d'une source live, une ligne par ticker (ou
    "FX:USD" pour un taux de change -> EUR) — alimenté par l'app et les
    scripts à chaque prix frais, sans aucune requête dédiée. Sert de prix
    daté quand la source est en pause (voir market_store.py)."""
    __tablename__ = "last_known_prices"

    ticker = Column(String, primary_key=True)
    price = Column(Float, nullable=False)  # devise native (pas en euros)
    currency = Column(String, nullable=False)  # devise réelle de l'actif
    previous_close = Column(Float, nullable=True)
    quote_type = Column(String, nullable=True)
    market_time = Column(String, nullable=True)  # heure de cotation réelle (ISO), si connue
    fetched_at = Column(String, nullable=False)  # heure d'obtention auprès de la source (ISO)
    change_30d_pct = Column(Float, nullable=True)
    change_30d_at = Column(String, nullable=True)


class AssetDailySnapshotRow(Base):
    """Prix indicatif quotidien d'un actif des pages de liste Trading
    (clôture de la veille, devise réelle, variation 30 j) — voir
    daily_snapshot.py, qui crée aussi la table (CREATE TABLE IF NOT EXISTS)
    et l'amorce avec asset_universe. Données de marché publiques, aucune
    donnée utilisateur."""
    __tablename__ = "asset_daily_snapshot"

    ticker = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, index=True)
    zone = Column(String, nullable=True)  # réservé à une phase ultérieure
    country = Column(String, nullable=True)  # réservé à une phase ultérieure
    close_price = Column(Float, nullable=True)  # devise native
    currency = Column(String, nullable=True)
    change_30d_pct = Column(Float, nullable=True)
    as_of_date = Column(String, nullable=True)  # date de la clôture (AAAA-MM-JJ)
    updated_at = Column(String, nullable=True)  # dernière mise à jour réussie (ISO)
    last_attempt_at = Column(String, nullable=True)  # dernière tentative, réussie ou non (ISO)


class RefreshLeaseRow(Base):
    """Bail de rafraîchissement (un seul processus à la fois par nom), voir
    daily_snapshot.acquire_lease."""
    __tablename__ = "refresh_leases"

    name = Column(String, primary_key=True)
    leased_until = Column(String, nullable=False)  # ISO 8601 UTC, format fixe
    holder = Column(String, nullable=True)


class TpSlOrderRow(Base):
    """Palier Take Profit / Stop Loss sur une position : prix cible EXACT (en
    euros, pas un pourcentage) et quantité exprimée en % de la position
    INITIALE au moment de la création de CE palier — jamais recalculée sur la
    quantité résiduelle si la position a déjà été partiellement réduite
    depuis (par ce palier ou par un autre trade). La quantité absolue à
    vendre au déclenchement est donc figée une fois pour toutes ici
    (`trigger_quantity`), calculée à la création à partir de
    `initial_quantity`/`quantity_pct` mais jamais recalculée ensuite — voir
    scripts/check_tp_sl.py pour la logique d'exécution.

    Plusieurs paliers peuvent coexister sur la même position (pas de
    contrainte de somme à 100%) : la partie de la position sans palier reste
    simplement une position normale.

    `side` (long/short de la position au moment de la création) détermine
    l'action à exécuter (vente vs rachat short) ; combiné à `kind`
    (take_profit/stop_loss, affichage uniquement), il détermine le sens de
    la comparaison au déclenchement (voir scripts/check_tp_sl.py).
    """
    __tablename__ = "tp_sl_orders"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    portfolio_id = Column(UUID(as_uuid=False), ForeignKey("portfolios.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String, nullable=False)
    name = Column(String, nullable=False)
    currency = Column(String, nullable=False)
    side = Column(String, nullable=False)  # "long" ou "short"
    kind = Column(String, nullable=False)  # "take_profit" ou "stop_loss"
    target_price_eur = Column(Float, nullable=False)
    quantity_pct = Column(Float, nullable=False)  # pour affichage/audit
    initial_quantity = Column(Float, nullable=False)  # pour affichage/audit
    trigger_quantity = Column(Float, nullable=False)  # figé à la création, utilisé à l'exécution
    # active : en attente de déclenchement
    # executed : déclenché et exécuté avec succès
    # cancelled : annulé par l'utilisateur, OU auto-annulé par le cron si la
    #             position d'origine n'existe plus dans le même sens (fermée/
    #             inversée entre-temps par un autre trade) — voir
    #             scripts/check_tp_sl.py.
    status = Column(String, nullable=False, default="active")
    created_at = Column(String, nullable=False, default=_now_iso)
    executed_at = Column(String, nullable=True)
    executed_price_eur = Column(Float, nullable=True)


class SearchHistoryRow(Base):
    """Derniers actifs consultés par utilisateur, dans l'onglet Trading (barre
    de recherche vide -> historique récent). Une ligne par (utilisateur,
    ticker) : revoir un actif déjà vu renouvelle juste `searched_at` au lieu
    d'empiler des doublons."""
    __tablename__ = "search_history"
    __table_args__ = (UniqueConstraint("user_id", "ticker", name="uq_search_history_user_ticker"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String, nullable=False)
    name = Column(String, nullable=False)
    quote_type = Column(String, nullable=False, default="")
    searched_at = Column(String, nullable=False, default=_now_iso)


class CourseRow(Base):
    """Contenu partagé (lu par tous, écrit par Admin/Contributeur) : `user_id`
    identifie l'auteur/dernier éditeur, ce n'est pas une clé d'isolation
    (pas de filtre par utilisateur à la lecture). Nullable : un compte
    supprimé laisse ses cours en place, juste détachés (auteur "inconnu")."""
    __tablename__ = "courses"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    theme = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(String, nullable=False, default=_now_iso)
    updated_at = Column(String, nullable=False, default=_now_iso)


class NewsRow(Base):
    """Article du fil News (onglet News) : contenu partagé, lu par tous,
    écrit par Admin/Contributeur. Même principe que CourseRow pour
    `user_id` (auteur d'origine, nullable — détaché si le compte est
    supprimé, l'article reste en place)."""
    __tablename__ = "news"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    link = Column(String, nullable=True)
    # Couverture pour la carte d'aperçu (grille de l'onglet News) : une URL
    # d'image détectée dans `content`, une image envoyée par upload (stockée
    # ici en data URI base64 — pas de stockage de fichiers dédié, d'où Text
    # plutôt que String), ou le sentinel "__LINK__" (voir ui_news._LINK_COVER)
    # quand la couverture doit reprendre l'aperçu du lien externe. None = pas
    # de couverture (carte texte seule). Choisie automatiquement s'il n'y a
    # qu'un seul visuel candidat à la publication, sinon explicitement par
    # l'auteur.
    image_couverture = Column(Text, nullable=True)
    created_at = Column(String, nullable=False, default=_now_iso)
    # Article généré automatiquement (résumé hebdomadaire, voir
    # weekly_summary.py) : `user_id` reste NULL comme pour un compte
    # supprimé (aucun "utilisateur système" en base), donc ce flag distingue
    # explicitement les deux cas à l'affichage (voir ui_news.py) plutôt que
    # d'afficher "(compte supprimé)" pour un résumé automatique.
    is_system = Column(Boolean, nullable=False, default=False)
