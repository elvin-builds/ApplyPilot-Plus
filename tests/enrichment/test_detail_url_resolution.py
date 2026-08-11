"""Tests for detail URL resolution and retirement of unresolvable rows."""

import os
import sys

# Ensure src is on sys.path for tests when running from repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from applypilot.database import init_db
from applypilot.enrichment.detail import resolve_all_urls, resolve_url


def test_resolve_url_acceptance_cases():
    assert resolve_url("/job/abc", "SimplyHired") == "https://www.simplyhired.com/job/abc"
    assert (
        resolve_url("data-analyst-x-123", "Working Nomads")
        == "https://www.workingnomads.com/jobs/data-analyst-x-123"
    )
    assert resolve_url("2567886", "PowerToFly") is None
    assert resolve_url("/remote-dev-jobs/x", "RemoteOK") is None
    assert resolve_url("/en/jobs/x", "WelcomeToTheJungle") is None
    assert resolve_url("https://x.com/j", "AnySite") == "https://x.com/j"


def test_resolve_url_derived_base_for_missing_base_urls_entry():
    assert resolve_url("/jobs/123-role", "Wellfound") == "https://wellfound.com/jobs/123-role"


def test_resolve_all_urls_marks_unresolvable_relative_rows_terminal():
    conn = init_db(":memory:")
    conn.execute("DELETE FROM jobs")
    conn.execute(
        "INSERT INTO jobs (url, title, site) VALUES (?, ?, ?)",
        ("/job/abc", "Resolvable", "SimplyHired"),
    )
    conn.execute(
        "INSERT INTO jobs (url, title, site) VALUES (?, ?, ?)",
        ("2567886", "Bare ID", "PowerToFly"),
    )
    conn.execute(
        "INSERT INTO jobs (url, title, site) VALUES (?, ?, ?)",
        ("/remote-dev-jobs/x", "Remote", "RemoteOK"),
    )
    conn.commit()

    stats = resolve_all_urls(conn)

    assert stats["resolved"] == 1
    assert stats["failed"] == 2

    resolved = conn.execute(
        "SELECT url, detail_scraped_at, detail_error FROM jobs WHERE title = ?",
        ("Resolvable",),
    ).fetchone()
    assert resolved[0] == "https://www.simplyhired.com/job/abc"
    assert resolved[1] is None
    assert resolved[2] is None

    bare_id = conn.execute(
        "SELECT url, detail_scraped_at, detail_error FROM jobs WHERE title = ?",
        ("Bare ID",),
    ).fetchone()
    assert bare_id[0] == "2567886"
    assert bare_id[1] is not None
    assert bare_id[2] == "unresolvable relative URL"

    remote_ok = conn.execute(
        "SELECT url, detail_scraped_at, detail_error FROM jobs WHERE title = ?",
        ("Remote",),
    ).fetchone()
    assert remote_ok[0] == "/remote-dev-jobs/x"
    assert remote_ok[1] is not None
    assert remote_ok[2] == "unresolvable relative URL"


def test_resolve_all_urls_does_not_retire_wttj_rows():
    conn = init_db(":memory:")
    conn.execute("DELETE FROM jobs")
    conn.execute(
        "INSERT INTO jobs (url, title, site) VALUES (?, ?, ?)",
        ("/en/jobs/x", "WTTJ", "WelcomeToTheJungle"),
    )
    conn.commit()

    stats = resolve_all_urls(conn)

    assert stats["resolved"] == 0
    assert stats["failed"] == 1

    wttj = conn.execute(
        "SELECT url, detail_scraped_at, detail_error FROM jobs WHERE title = ?",
        ("WTTJ",),
    ).fetchone()
    assert wttj[0] == "/en/jobs/x"
    assert wttj[1] is None
    assert wttj[2] is None
