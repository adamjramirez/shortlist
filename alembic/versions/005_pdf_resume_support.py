"""Add PDF resume support columns.

- resumes.resume_type: "tex" or "pdf"
- resumes.extracted_text_key: S3 key for extracted text (PDF only)
- jobs.tailored_resume_pdf_key: S3 key for compiled PDF

Revision ID: 005
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("resumes", sa.Column("resume_type", sa.String(), server_default="tex"))
    op.add_column("resumes", sa.Column("extracted_text_key", sa.String()))
    op.add_column("jobs", sa.Column("tailored_resume_pdf_key", sa.String()))


def downgrade():
    op.drop_column("jobs", "tailored_resume_pdf_key")
    op.drop_column("resumes", "extracted_text_key")
    op.drop_column("resumes", "resume_type")
