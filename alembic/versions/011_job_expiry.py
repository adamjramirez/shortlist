"""Add job expiry tracking columns.

Revision ID: 011
Revises: 010
Create Date: 2026-04-07
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS closed_reason VARCHAR")
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS expiry_checked_at TIMESTAMPTZ")
    # Backfill: mark existing user-toggled closes with reason='user'
    op.execute("UPDATE jobs SET closed_reason = 'user' WHERE is_closed = true AND closed_reason IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_expiry_check ON jobs(is_closed, expiry_checked_at, fit_score DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_jobs_expiry_check")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS expiry_checked_at")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS closed_reason")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS closed_at")
