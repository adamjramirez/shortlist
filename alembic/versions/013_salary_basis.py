"""Add salary_basis to jobs.

Revision ID: 013
Revises: 012
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('salary_basis', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'salary_basis')
