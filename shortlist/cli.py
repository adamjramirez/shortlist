"""CLI interface for shortlist."""
import sqlite3
from datetime import date
from pathlib import Path

import click

from shortlist.config import load_config
from shortlist.db import init_db, get_db


def _find_project_root() -> Path:
    """Find the project root (directory containing pyproject.toml)."""
    current = Path.cwd()
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


def _get_config(config_path: str | None = None) -> tuple:
    """Load config and determine project root."""
    root = _find_project_root()
    if config_path:
        cfg = load_config(Path(config_path))
    else:
        default = root / "config" / "profile.yaml"
        if default.exists():
            cfg = load_config(default)
        else:
            from shortlist.config import Config
            cfg = Config()
    return cfg, root


@click.group()
def cli():
    """Shortlist — your job search chief of staff."""
    pass


@cli.command()
def init():
    """Set up a new shortlist project in the current directory."""
    from importlib import resources

    root = Path.cwd()
    config_dir = root / "config"
    config_dir.mkdir(exist_ok=True)

    target = config_dir / "profile.yaml"
    if target.exists():
        click.echo(f"Config already exists: {target}")
        if not click.confirm("Overwrite?"):
            return

    # Load example config from package data (works in any install mode)
    try:
        example_text = resources.files("shortlist.data").joinpath(
            "example-profile.yaml"
        ).read_text()
    except Exception:
        click.echo("Error: example-profile.yaml not found in package.")
        return

    target.write_text(example_text)
    click.echo(f"Created {target}")

    # Create directories
    for d in ["resumes", "briefs"]:
        (root / d).mkdir(exist_ok=True)
        click.echo(f"Created {d}/")

    # Create .env template
    env_file = root / ".env"
    if not env_file.exists():
        env_file.write_text(
            "# LLM API key — set ONE of these based on your config/profile.yaml llm.model setting\n"
            "# Default model is gemini-2.0-flash (cheapest option)\n"
            "GEMINI_API_KEY=your-key-here\n"
            "# OPENAI_API_KEY=your-key-here\n"
            "# ANTHROPIC_API_KEY=your-key-here\n"
            "\n"
            "# Optional: NextPlay Substack session cookie for paid articles.\n"
            "# Without this, shortlist still collects from NextPlay's free articles.\n"
            "# With it, you also get job listings from their paid newsletter.\n"
            "# To get it: log in to nextplay.substack.com, open browser DevTools →\n"
            "# Application → Cookies → copy the value of 'substack.sid'.\n"
            "# SUBSTACK_SID=\n"
        )
        click.echo("Created .env (add your API key)")

    # Create .gitignore
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            ".env\njobs.db\nbriefs/\nresumes/\n.venv/\n"
            "__pycache__/\n*.pyc\n.pytest_cache/\n*.egg-info/\n"
        )
        click.echo("Created .gitignore")

    click.echo("\nNext steps:")
    click.echo("  1. Get a Gemini API key: https://aistudio.google.com/ → Get API key → Create API key")
    click.echo("  2. Paste it in .env: GEMINI_API_KEY=AIzaSy...your-key")
    click.echo("  3. Edit config/profile.yaml with your search criteria")
    click.echo("  4. Put your resume(s) in resumes/ (LaTeX format)")
    click.echo("  5. Run: shortlist run")


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to profile.yaml")
@click.option("--no-collect", is_flag=True, help="Skip collection, process existing jobs only")
def run(config_path, no_collect):
    """Run the full pipeline: collect → filter → score → enrich → tailor → brief."""
    from shortlist.pipeline import run_pipeline
    from shortlist.config import validate_config, validate_env, test_llm_key
    from shortlist import llm

    config, root = _get_config(config_path)

    # Validate everything before spending time collecting
    click.echo("Checking configuration...")
    errors = validate_config(config, root) + validate_env(root, config)
    if errors:
        click.echo("\n❌ Fix these issues before running:\n", err=True)
        for i, err in enumerate(errors, 1):
            click.echo(f"  {i}. {err}\n", err=True)
        raise SystemExit(1)

    # Configure and test LLM
    model = config.llm.model
    provider = llm.detect_provider(model)
    click.echo(f"Testing {provider} API key (model: {model})...")
    llm_err = test_llm_key(root, config)
    if llm_err:
        click.echo(f"\n❌ {llm_err}\n", err=True)
        raise SystemExit(1)
    click.echo("  ✓ API key works\n")

    llm.configure(model)

    if no_collect:
        click.echo("Running pipeline (skipping collection)...")
    else:
        click.echo("Running full pipeline...")
    brief_path = run_pipeline(config, root, skip_collect=no_collect)
    click.echo(f"\n✅ Brief generated: {brief_path}")
    click.echo(f"   Run 'shortlist today' to read it.")


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to profile.yaml")
def collect(config_path):
    """Collect jobs from all configured sources."""
    from shortlist.pipeline import run_collect_only
    from shortlist.config import validate_config

    config, root = _get_config(config_path)
    errors = validate_config(config, root)
    if errors:
        click.echo("❌ Fix these issues first:\n", err=True)
        for i, err in enumerate(errors, 1):
            click.echo(f"  {i}. {err}\n", err=True)
        raise SystemExit(1)

    click.echo("Collecting jobs...")
    count = run_collect_only(config, root)
    click.echo(f"Collected {count} jobs.")


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to profile.yaml")
def brief(config_path):
    """Generate today's daily brief."""
    from shortlist.pipeline import run_brief_only
    config, root = _get_config(config_path)
    click.echo("Generating brief...")
    path = run_brief_only(config, root)
    click.echo(f"Brief: {path}")


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to profile.yaml")
def today(config_path):
    """Show today's brief."""
    _, root = _get_config(config_path)
    today_file = root / "briefs" / f"{date.today().isoformat()}.md"
    if today_file.exists():
        click.echo(today_file.read_text())
    else:
        click.echo("No brief for today. Run 'shortlist run' first.")


@cli.command()
@click.argument("target")
@click.argument("role", required=False, default=None)
@click.argument("new_status", required=False, default=None)
@click.option("--note", default=None, help="Add a note to the status update.")
@click.option("--config", "config_path", default=None, help="Path to profile.yaml")
def status(target, role, new_status, note, config_path):
    """Update job application status. TARGET can be company name or job ID."""
    _, root = _get_config(config_path)
    db_path = root / "jobs.db"
    if not db_path.exists():
        click.echo("No database found. Run 'shortlist run' first.")
        return

    db = get_db(db_path)

    # If target is numeric, treat as job ID
    try:
        job_id = int(target)
        # Shift: role is actually the status, new_status is unused
        actual_status = role
        if not actual_status:
            click.echo("Usage: shortlist status <id> <status> [--note ...]")
            return
        _update_status_by_id(db, job_id, actual_status, note)
        return
    except (ValueError, TypeError):
        pass

    # Target is company name
    if role and new_status:
        # shortlist status "Acme" "VP Eng" applied
        _update_status_by_company_role(db, target, role, new_status, note)
    elif role and not new_status:
        # shortlist status "Acme" applied (role is actually status, only one job at company)
        actual_status = role
        _update_status_by_company(db, target, actual_status, note)
    else:
        click.echo("Usage: shortlist status <company> [role] <status> [--note ...]")

    db.close()


def _update_status_by_id(db, job_id, new_status, note):
    row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        click.echo(f"No job found with ID {job_id}")
        return
    updates = {"status": new_status}
    if note:
        updates["notes"] = note
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?",
               list(updates.values()) + [job_id])
    db.commit()
    click.echo(f"Updated: {row['title']} at {row['company']} → {new_status}")


def _update_status_by_company_role(db, company, role, new_status, note):
    rows = db.execute(
        "SELECT * FROM jobs WHERE company LIKE ? AND title LIKE ?",
        (f"%{company}%", f"%{role}%"),
    ).fetchall()
    if not rows:
        click.echo(f"No job found matching '{company}' / '{role}'")
        return
    if len(rows) > 1:
        click.echo(f"Multiple matches:")
        for r in rows:
            click.echo(f"  [{r['id']}] {r['title']} at {r['company']}")
        click.echo("Use job ID instead: shortlist status <id> <status>")
        return
    _update_status_by_id(db, rows[0]["id"], new_status, note)


def _update_status_by_company(db, company, new_status, note):
    rows = db.execute(
        "SELECT * FROM jobs WHERE company LIKE ?", (f"%{company}%",)
    ).fetchall()
    if not rows:
        click.echo(f"No jobs found for '{company}'")
        return
    if len(rows) > 1:
        click.echo(f"Multiple roles at {company}:")
        for r in rows:
            click.echo(f"  [{r['id']}] {r['title']} (score: {r['fit_score'] or '?'})")
        click.echo("Specify role: shortlist status \"company\" \"role\" <status>")
        return
    _update_status_by_id(db, rows[0]["id"], new_status, note)


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to profile.yaml")
def health(config_path):
    """Check source health."""
    _, root = _get_config(config_path)
    db_path = root / "jobs.db"
    if not db_path.exists():
        click.echo("No database found. Run 'shortlist run' first.")
        return

    db = get_db(db_path)
    rows = db.execute("""
        SELECT s.name, s.last_run,
               (SELECT sr.status FROM source_runs sr WHERE sr.source_id = s.id
                ORDER BY sr.finished_at DESC LIMIT 1) as last_status,
               (SELECT sr.jobs_found FROM source_runs sr WHERE sr.source_id = s.id
                ORDER BY sr.finished_at DESC LIMIT 1) as last_jobs
        FROM sources s ORDER BY s.name
    """).fetchall()

    if not rows:
        click.echo("No sources configured yet.")
        return

    click.echo(f"{'Source':<20} {'Status':<12} {'Last Run':<22} {'Jobs':<6}")
    click.echo("-" * 60)
    for r in rows:
        name = r["name"]
        status = r["last_status"] or "never"
        last_run = r["last_run"] or "never"
        jobs = r["last_jobs"] if r["last_jobs"] is not None else "—"
        click.echo(f"{name:<20} {status:<12} {last_run:<22} {jobs:<6}")

    db.close()
