"""Add auto-run scheduling columns.

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("profiles", sa.Column("auto_run_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("profiles", sa.Column("auto_run_interval_h", sa.Integer(), nullable=False, server_default="12"))
    op.add_column("profiles", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("profiles", sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runs", sa.Column("trigger", sa.String(), nullable=False, server_default="manual"))
    op.create_index("idx_profiles_auto_run", "profiles", ["auto_run_enabled", "next_run_at"])


def downgrade():
    op.drop_index("idx_profiles_auto_run", table_name="profiles")
    op.drop_column("profiles", "auto_run_enabled")
    op.drop_column("profiles", "auto_run_interval_h")
    op.drop_column("profiles", "next_run_at")
    op.drop_column("profiles", "consecutive_failures")
    op.drop_column("runs", "trigger")
