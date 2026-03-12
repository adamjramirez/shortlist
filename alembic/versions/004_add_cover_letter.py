"""Add cover_letter to jobs.

Revision ID: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("cover_letter", sa.Text()))


def downgrade():
    op.drop_column("jobs", "cover_letter")
