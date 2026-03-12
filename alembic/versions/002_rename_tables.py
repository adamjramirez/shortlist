"""Rename jobs_web/companies_web to jobs/companies.

Revision ID: 002
Revises: 001
"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("jobs_web", "jobs")
    op.rename_table("companies_web", "companies")

    # Rename indexes to match new table names
    op.execute("ALTER INDEX IF EXISTS idx_jobs_web_user_hash RENAME TO idx_jobs_user_hash")
    op.execute("ALTER INDEX IF EXISTS idx_jobs_web_user_status RENAME TO idx_jobs_user_status")
    op.execute("ALTER INDEX IF EXISTS idx_jobs_web_user_score RENAME TO idx_jobs_user_score")
    op.execute("ALTER INDEX IF EXISTS idx_companies_web_user_name RENAME TO idx_companies_user_name")


def downgrade():
    op.rename_table("jobs", "jobs_web")
    op.rename_table("companies", "companies_web")

    op.execute("ALTER INDEX IF EXISTS idx_jobs_user_hash RENAME TO idx_jobs_web_user_hash")
    op.execute("ALTER INDEX IF EXISTS idx_jobs_user_status RENAME TO idx_jobs_web_user_status")
    op.execute("ALTER INDEX IF EXISTS idx_jobs_user_score RENAME TO idx_jobs_web_user_score")
    op.execute("ALTER INDEX IF EXISTS idx_companies_user_name RENAME TO idx_companies_web_user_name")
