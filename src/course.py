"""Modèle d'un cours/résumé de révision (onglet Cours)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Course:
    title: str
    theme: str
    content: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # Auteur d'origine (immuable, jamais réassigné même si un Admin modifie
    # le cours ensuite) : c'est lui qui détermine qui a le droit de modifier
    # ce cours (voir auth.can_edit_course). None si l'auteur a supprimé son
    # compte (le cours est conservé, juste détaché).
    author_id: str | None = None
