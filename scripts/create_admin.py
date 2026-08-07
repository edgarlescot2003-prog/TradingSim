"""Crée (ou met à niveau) le compte Admin. À exécuter une fois, manuellement,
depuis la racine du projet :

    python -m scripts.create_admin

Si un compte "default" existe encore (utilisateur technique créé par la
migration Phase 1, avant l'authentification), il est mis à niveau en place
avec l'identifiant/mot de passe choisis ici plutôt que remplacé : tous les
portefeuilles/cours déjà migrés restent attachés au même compte, maintenant
ton compte Admin réel.
"""

import getpass

from sqlalchemy import select

from src import auth, db
from src.db_models import User


def main() -> None:
    db.init_db()

    username = input("Identifiant admin : ").strip()
    if not username:
        print("Identifiant vide, abandon.")
        return

    password = getpass.getpass("Mot de passe admin (8 caractères minimum) : ")
    password_confirm = getpass.getpass("Confirme le mot de passe : ")
    if password != password_confirm:
        print("Les mots de passe ne correspondent pas, abandon.")
        return
    if len(password) < 8:
        print("Le mot de passe doit faire au moins 8 caractères, abandon.")
        return

    with db.get_session() as session:
        legacy = session.execute(
            select(User).where(User.username == db.DEFAULT_USERNAME)
        ).scalar_one_or_none()
        existing_target = session.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()

        if existing_target is not None and (legacy is None or existing_target.id != legacy.id):
            print(f"L'identifiant « {username} » est déjà pris par un autre compte, abandon.")
            return

        if legacy is not None:
            legacy.username = username
            legacy.password_hash = auth.hash_password(password)
            legacy.role = auth.ROLE_ADMIN
            legacy.is_active = True
            session.commit()
            print(f"Compte technique '{db.DEFAULT_USERNAME}' mis à niveau vers l'admin « {username} » "
                  "— tes portefeuilles et cours déjà migrés restent attachés à ce compte.")
        else:
            user = User(
                username=username, password_hash=auth.hash_password(password),
                role=auth.ROLE_ADMIN, is_active=True,
            )
            session.add(user)
            session.commit()
            print(f"Compte admin « {username} » créé.")


if __name__ == "__main__":
    main()
