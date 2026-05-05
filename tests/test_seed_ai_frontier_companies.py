"""Tests for the AI-frontier seed script."""
import sqlite3

import pytest

from scripts.seed_ai_frontier_companies import AI_FRONTIER_COMPANIES, seed


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE companies ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  name_normalized TEXT NOT NULL,"
        "  domain TEXT,"
        "  source TEXT,"
        "  UNIQUE(name_normalized, domain)"
        ")"
    )
    yield conn
    conn.close()


def test_seed_inserts_all_companies(db):
    inserted, skipped = seed(db, AI_FRONTIER_COMPANIES)
    assert inserted == len(AI_FRONTIER_COMPANIES)
    assert skipped == 0


def test_seed_is_idempotent(db):
    seed(db, AI_FRONTIER_COMPANIES)
    inserted, skipped = seed(db, AI_FRONTIER_COMPANIES)
    assert inserted == 0
    assert skipped == len(AI_FRONTIER_COMPANIES)


def test_seed_marks_source(db):
    seed(db, AI_FRONTIER_COMPANIES)
    rows = db.execute(
        "SELECT name FROM companies WHERE source = 'ai-frontier-seed'"
    ).fetchall()
    assert len(rows) == len(AI_FRONTIER_COMPANIES)


def test_seed_includes_openai_and_anthropic(db):
    seed(db, AI_FRONTIER_COMPANIES)
    rows = db.execute(
        "SELECT name, domain FROM companies "
        "WHERE name IN ('OpenAI', 'Anthropic')"
    ).fetchall()
    found = {(name, domain) for name, domain in rows}
    assert ("OpenAI", "openai.com") in found
    assert ("Anthropic", "anthropic.com") in found


def test_seed_subset(db):
    subset = [("OpenAI", "openai.com")]
    inserted, skipped = seed(db, subset)
    assert inserted == 1
    assert skipped == 0

    inserted, skipped = seed(db, subset)
    assert inserted == 0
    assert skipped == 1
