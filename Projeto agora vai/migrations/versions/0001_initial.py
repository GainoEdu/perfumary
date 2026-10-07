"""Esquema inicial da loja.

Cria todas as tabelas (checkfirst: nunca recria nem apaga o que já existe).
Alterações futuras nos modelos: `flask db migrate` gera as próximas revisões.
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    from app.extensions import db
    from app import models  # noqa: F401  (registra os modelos)

    db.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    pass  # nunca apagamos dados automaticamente
