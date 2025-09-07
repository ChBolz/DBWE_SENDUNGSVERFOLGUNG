"""add shipment_number to ShipmentHead

Revision ID: e9cee3667b47
Revises: 8a13c693bb81
Create Date: 2025-09-07 19:02:17.699066

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e9cee3667b47'
down_revision = '8a13c693bb81'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("shipment_head", schema=None) as batch_op:
        batch_op.add_column(sa.Column("shipment_number", sa.String(length=50), nullable=True))
        # Name the unique constraint explicitly (works across SQLite/MySQL/Postgres)
        batch_op.create_unique_constraint(
            "uq_shipment_head_shipment_number",
            ["shipment_number"],
        )

def downgrade():
    with op.batch_alter_table("shipment_head", schema=None) as batch_op:
        batch_op.drop_constraint("uq_shipment_head_shipment_number", type_="unique")
        batch_op.drop_column("shipment_number")
