"""Add is_closed column to jobs table.

Revision ID: 007
Revises: 006
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("is_closed", sa.Boolean(), server_default="false", nullable=True))


def downgrade():
    op.drop_column("jobs", "is_closed")
