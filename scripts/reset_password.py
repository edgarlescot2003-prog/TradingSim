"""Change le mot de passe d'un compte sans afficher ni stocker le nouveau mot de passe."""

import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import auth, db
from src.db_models import User


def reset_password(username: str) -> None:
    first = getpass.getpass("Nouveau mot de passe (8 caracteres minimum) : ")
    confirmation = getpass.getpass("Confirme le nouveau mot de passe : ")
    if first != confirmation:
        raise ValueError("Les deux mots de passe ne correspondent pas.")
    if len(first) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caracteres.")

    with db.get_session() as session:
        user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None:
            raise ValueError(f"Compte introuvable : {username}")
        user.password_hash = auth.hash_password(first)
        session.commit()

    print(f"Mot de passe mis a jour pour {username}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python -m scripts.reset_password nom_du_compte")
        raise SystemExit(1)
    reset_password(sys.argv[1])