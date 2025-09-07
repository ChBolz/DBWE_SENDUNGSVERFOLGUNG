"""add 'packed' to package_status enum

Revision ID: 2514ca1f8ad1
Revises: d04069ca5a9c
Create Date: 2025-09-07 20:39:16.857996

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2514ca1f8ad1'
down_revision = 'd04069ca5a9c'
branch_labels = None
depends_on = None


def upgrade():
   bind = op.get_bind()
   if bind.dialect.name == "mysql":
    op.execute("ALTER TABLE package_head MODIFY status ENUM('open','packed','shipped') NOT NULL")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute("ALTER TABLE package_head MODIFY status ENUM('open','shipped') NOT NULL")
