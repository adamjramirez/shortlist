"""Add viewed_at and run_id columns to jobs table.

Revision ID: 008
Revises: 007
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True))
    op.create_index("idx_jobs_web_user_run", "jobs", ["user_id", "run_id"])


def downgrade():
    op.drop_index("idx_jobs_web_user_run", table_name="jobs")
    op.drop_column("jobs", "run_id")
    op.drop_column("jobs", "viewed_at")
