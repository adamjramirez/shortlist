"""Add posted_at column to jobs table.

Stores the actual job posting date from the source (not crawl time).

Revision ID: 006
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("jobs", "posted_at")
