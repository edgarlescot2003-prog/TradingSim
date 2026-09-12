"""Page Règlement du concours : contenu STATIQUE chargé depuis
content/reglement.md, volontairement séparé du code Python — Edgar peut
modifier ce fichier directement (ex : dates de début/fin à venir) sans
toucher au code, juste en éditant ce fichier puis en commitant/poussant.

Affichage informatif uniquement, pas de case à cocher/validation obligatoire
(voir la doc de conception d'origine) : rien n'empêche un compte d'utiliser
l'app sans être passé par cette page.
"""

from pathlib import Path

import streamlit as st

_CONTENT_PATH = Path(__file__).resolve().parent.parent / "content" / "reglement.md"


def render() -> None:
    st.title("Règlement du concours")
    try:
        content = _CONTENT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        st.error("Contenu du règlement introuvable (content/reglement.md manquant).")
        return
    st.markdown(content)
