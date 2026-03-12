"""Add interest_note and career_page_url to jobs.

Revision ID: 003
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("interest_note", sa.Text()))
    op.add_column("jobs", sa.Column("career_page_url", sa.String()))


def downgrade():
    op.drop_column("jobs", "career_page_url")
    op.drop_column("jobs", "interest_note")
