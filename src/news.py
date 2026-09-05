"""Modèle d'un article du fil News (onglet News)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class NewsItem:
    title: str
    content: str
    link: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Auteur d'origine. None si l'auteur a supprimé son compte (l'article
    # est conservé, juste détaché — voir auth.delete_user).
    author_id: str | None = None
