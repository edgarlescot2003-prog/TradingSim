"""Modèle d'un article du fil News (onglet News)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class NewsItem:
    title: str
    content: str
    link: str | None = None
    # Couverture de la carte d'aperçu (grille onglet News) : URL d'image, le
    # sentinel "__LINK__" (aperçu du lien externe), ou None (carte texte
    # seule) — voir ui_news.py pour la résolution à la publication.
    image_couverture: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Auteur d'origine. None si l'auteur a supprimé son compte (l'article
    # est conservé, juste détaché — voir auth.delete_user) OU si l'article
    # est généré automatiquement (voir is_system ci-dessous, qui distingue
    # les deux cas à l'affichage).
    author_id: str | None = None
    # Résumé hebdomadaire automatique (voir weekly_summary.py) plutôt
    # qu'un article publié par un compte réel.
    is_system: bool = False
