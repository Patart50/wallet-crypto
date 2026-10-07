"""Environnement Alembic de wallet-crypto (wallet D-018, D-034).

Lancé par ``wallet_crypto.db.migrate`` avec une connexion déjà ouverte : pas de fichier
``alembic.ini``, rien à configurer pour l'utilisateur.
"""

from alembic import context

from wallet_crypto.db.models import Base

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=True,  # SQLite ne sait pas modifier une colonne : Alembic recopie la table
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
