"""Pydantic request/response schemas."""
from typing import Literal

from pydantic import BaseModel, EmailStr


# --- Auth ---

class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    email: str
    user_id: int


class UserResponse(BaseModel):
    id: int
    email: str


# --- Profile ---

class GenerateProfileRequest(BaseModel):
    resume_id: int


class GenerateProfileResponse(BaseModel):
    fit_context: str
    tracks: dict
    filters: dict


class ProfileUpdate(BaseModel):
    """Profile config — same shape as profile.yaml.

    All fields optional. Only provided fields are merged into stored config.
    """
    fit_context: str | None = None
    tracks: dict | None = None
    filters: dict | None = None
    preferences: dict | None = None
    llm: dict | None = None
    brief: dict | None = None
    substack_sid: str | None = None
    aww_node_id: str | None = None  # AWW node ID for pulling networking slice


class ProfileResponse(BaseModel):
    fit_context: str
    tracks: dict
    filters: dict
    preferences: dict
    llm: dict
    brief: dict
    substack_sid: str = ""
    aww_node_id: str = ""


# --- Resume ---

class ResumeResponse(BaseModel):
    id: int
    filename: str
    track: str | None
    resume_type: str = "tex"
    uploaded_at: str


# --- Jobs ---

class JobSummary(BaseModel):
    id: int
    title: str
    company: str
    location: str | None
    fit_score: int | None
    matched_track: str | None
    salary_estimate: str | None
    url: str | None
    status: str | None
    user_status: str | None
    sources_seen: list[str]
    first_seen: str | None
    has_tailored_resume: bool
    has_tailored_pdf: bool = False
    is_new: bool = False
    company_intel: str | None  # One-line summary from enrichment
    score_reasoning: str | None = None  # Short explanation for the score


class JobDetail(JobSummary):
    description: str | None
    yellow_flags: str | None
    enrichment: dict | None
    interest_note: str | None = None
    career_page_url: str | None = None
    cover_letter: str | None = None
    notes: str | None


class JobListResponse(BaseModel):
    jobs: list[JobSummary]
    total: int
    page: int
    per_page: int


class JobStatusUpdate(BaseModel):
    status: Literal["applied", "skipped", "saved"]


# --- Runs ---

class RunResponse(BaseModel):
    id: int
    status: str
    progress: dict
    error: str | None
    machine_id: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
