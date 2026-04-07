"""Add career_page_sources table for curated job sources with state tracking.

Revision ID: 010
Revises: 009
Create Date: 2026-04-07
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS career_page_sources (
            id SERIAL PRIMARY KEY,
            company_name TEXT NOT NULL,
            career_url TEXT NOT NULL UNIQUE,
            ats TEXT,
            slug TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            consecutive_empty INT NOT NULL DEFAULT 0,
            last_jobs_count INT NOT NULL DEFAULT 0,
            last_checked_at TIMESTAMPTZ,
            added_at TIMESTAMPTZ DEFAULT NOW(),
            source TEXT,
            notes TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_career_page_sources_status "
        "ON career_page_sources(status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS career_page_sources")
