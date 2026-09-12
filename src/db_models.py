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

from sqlalchemy import Boolean, Column, Float, ForeignKey, String, Text, UniqueConstraint
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
