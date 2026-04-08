"""Add prestige_tier to jobs.

Revision ID: 012
Revises: 011
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('prestige_tier', sa.String(1), nullable=True))
    op.create_index('ix_jobs_prestige_tier', 'jobs', ['prestige_tier'])


def downgrade() -> None:
    op.drop_index('ix_jobs_prestige_tier', table_name='jobs')
    op.drop_column('jobs', 'prestige_tier')
