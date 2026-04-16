"""SQLAlchemy models for the web API."""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    profile = relationship("Profile", back_populates="user", uselist=False)
    runs = relationship("Run", back_populates="user")
    resumes = relationship("Resume", back_populates="user")


class Profile(Base):
    __tablename__ = "profiles"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    config = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    auto_run_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    auto_run_interval_h = Column(Integer, nullable=False, default=12, server_default="12")
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0, server_default="0")

    user = relationship("User", back_populates="profile")


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="pending")
    progress = Column(JSON, default=dict)
    error = Column(Text)
    machine_id = Column(String)  # Fly Machine ID
    trigger = Column(String, nullable=False, default="manual", server_default="manual")
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="runs")


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    track = Column(String)
    s3_key = Column(String, nullable=False)
    resume_type = Column(String, default="tex")  # "tex" or "pdf"
    extracted_text_key = Column(String)  # S3 key for extracted text (PDF only)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="resumes")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String)
    url = Column(String)
    description = Column(Text)
    description_hash = Column(String, nullable=False)
    salary_text = Column(String)
    sources_seen = Column(JSON, default=list)
    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    posted_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default="new")
    reject_reason = Column(String)
    fit_score = Column(Integer)
    matched_track = Column(String)
    score_reasoning = Column(Text)
    yellow_flags = Column(Text)
    salary_estimate = Column(String)
    salary_confidence = Column(String)
    salary_basis = Column(Text)
    enrichment = Column(JSON)
    enriched_at = Column(DateTime(timezone=True))
    tailored_resume_key = Column(String)  # S3 key instead of local path
    tailored_resume_pdf_key = Column(String)  # S3 key for compiled PDF
    interest_note = Column(Text)
    career_page_url = Column(String)
    cover_letter = Column(Text)
    notes = Column(Text)
    first_briefed = Column(DateTime(timezone=True))
    brief_count = Column(Integer, default=0)
    user_status = Column(String)  # applied, skipped, saved
    is_closed = Column(Boolean, default=False, server_default="false")
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_reason = Column(String, nullable=True)
    prestige_tier = Column(String(1), nullable=True)
    viewed_at = Column(DateTime(timezone=True), nullable=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=True)

    __table_args__ = (
        Index("idx_jobs_web_user_hash", "user_id", "description_hash", unique=True),
        Index("idx_jobs_web_user_status", "user_id", "status"),
        Index("idx_jobs_web_user_score", "user_id", "fit_score"),
        Index("idx_jobs_web_user_run", "user_id", "run_id"),
    )


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    name_normalized = Column(String, nullable=False)
    domain = Column(String)
    career_page_url = Column(String)
    ats_platform = Column(String)
    stage = Column(String)
    last_funding = Column(String)
    headcount = Column(Integer)
    growth_signals = Column(Text)
    glassdoor_rating = Column(Float)
    eng_blog_url = Column(String)
    enriched_at = Column(DateTime(timezone=True))
    source = Column(String)

    __table_args__ = (
        Index("idx_companies_web_user_name", "user_id", "name_normalized", "domain", unique=True),
    )
