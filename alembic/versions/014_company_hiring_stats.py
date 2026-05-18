"""Add company_hiring_stats table for evergreen-req signal (CSVFirst etc).

Revision ID: 014
Revises: 013
Create Date: 2026-05-17
"""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS company_hiring_stats (
            id SERIAL PRIMARY KEY,
            company_norm TEXT NOT NULL,
            source TEXT NOT NULL,
            snapshot_date DATE NOT NULL,
            total_active_jobs INT,
            share_180d_plus REAL,
            share_365d_plus REAL,
            mean_open_days REAL,
            oldest_job_open_days INT,
            ingested_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (company_norm, source, snapshot_date)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_hiring_stats_lookup "
        "ON company_hiring_stats(company_norm, source, snapshot_date DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS company_hiring_stats")
