"""Initial schema.

Revision ID: 001
Revises:
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("progress", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("machine_id", sa.String()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "resumes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("track", sa.String()),
        sa.Column("s3_key", sa.String(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "jobs_web",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=False),
        sa.Column("location", sa.String()),
        sa.Column("url", sa.String()),
        sa.Column("description", sa.Text()),
        sa.Column("description_hash", sa.String(), nullable=False),
        sa.Column("salary_text", sa.String()),
        sa.Column("sources_seen", sa.JSON()),
        sa.Column("first_seen", sa.DateTime(timezone=True)),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(), server_default="new"),
        sa.Column("reject_reason", sa.String()),
        sa.Column("fit_score", sa.Integer()),
        sa.Column("matched_track", sa.String()),
        sa.Column("score_reasoning", sa.Text()),
        sa.Column("yellow_flags", sa.Text()),
        sa.Column("salary_estimate", sa.String()),
        sa.Column("salary_confidence", sa.String()),
        sa.Column("enrichment", sa.JSON()),
        sa.Column("enriched_at", sa.DateTime(timezone=True)),
        sa.Column("tailored_resume_key", sa.String()),
        sa.Column("notes", sa.Text()),
        sa.Column("first_briefed", sa.DateTime(timezone=True)),
        sa.Column("brief_count", sa.Integer(), server_default="0"),
        sa.Column("user_status", sa.String()),
    )
    op.create_index("idx_jobs_web_user_hash", "jobs_web", ["user_id", "description_hash"], unique=True)
    op.create_index("idx_jobs_web_user_status", "jobs_web", ["user_id", "status"])
    op.create_index("idx_jobs_web_user_score", "jobs_web", ["user_id", "fit_score"])

    op.create_table(
        "companies_web",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_normalized", sa.String(), nullable=False),
        sa.Column("domain", sa.String()),
        sa.Column("career_page_url", sa.String()),
        sa.Column("ats_platform", sa.String()),
        sa.Column("stage", sa.String()),
        sa.Column("last_funding", sa.String()),
        sa.Column("headcount", sa.Integer()),
        sa.Column("growth_signals", sa.Text()),
        sa.Column("glassdoor_rating", sa.Float()),
        sa.Column("eng_blog_url", sa.String()),
        sa.Column("enriched_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String()),
    )
    op.create_index("idx_companies_web_user_name", "companies_web", ["user_id", "name_normalized", "domain"], unique=True)


def downgrade() -> None:
    op.drop_table("companies_web")
    op.drop_table("jobs_web")
    op.drop_table("resumes")
    op.drop_table("runs")
    op.drop_table("profiles")
    op.drop_table("users")
