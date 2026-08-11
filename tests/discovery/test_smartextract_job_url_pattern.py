"""Tests for smart extraction job_url_pattern filtering."""

import os
import sqlite3
import sys
from unittest.mock import patch

# Ensure src is on sys.path for tests when running from repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from applypilot.discovery.smartextract import _store_jobs_filtered


def _make_jobs_table(conn):
    conn.execute("""
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            title TEXT,
            salary TEXT,
            description TEXT,
            location TEXT,
            site TEXT,
            strategy TEXT,
            discovered_at TEXT
        )
    """)


TECHSTARS_SITE = {
    "name": "Techstars Jobs",
    "url": "https://jobs.techstars.com/jobs?keywords={query_encoded}",
    "type": "search",
    "job_url_pattern": "^/companies/[^/]+/jobs/[^/]+",
}


class TestStoreJobsFilteredJobUrlPattern:
    """Tests for optional per-site job URL shape filtering."""

    def test_filters_same_domain_mismatches_but_keeps_off_host_urls(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        _make_jobs_table(conn)
        jobs = [
            {
                "url": "https://jobs.techstars.com/companies/acme/jobs/123-engineer",
                "title": "Platform Engineer",
            },
            {
                "url": "https://www.techstars.com/docokids",
                "title": "Docokids",
            },
            {
                "url": "https://www.linkedin.com/jobs/view/456",
                "title": "Senior Engineer",
            },
            {
                "url": "/companies/acme/jobs/123",
                "title": "Backend Engineer",
            },
            {
                "url": "/docokids",
                "title": "Relative company page",
            },
        ]

        with patch("applypilot.discovery.smartextract.load_sites", return_value=[TECHSTARS_SITE]), patch(
            "applypilot.discovery.smartextract.log"
        ) as mock_log:
            result = _store_jobs_filtered(conn, jobs, "Techstars Jobs", "api_response", [], [])

        assert result == (3, 0)
        rows = conn.execute("SELECT url, title FROM jobs ORDER BY url").fetchall()
        assert rows == [
            ("/companies/acme/jobs/123", "Backend Engineer"),
            ("https://jobs.techstars.com/companies/acme/jobs/123-engineer", "Platform Engineer"),
            ("https://www.linkedin.com/jobs/view/456", "Senior Engineer"),
        ]
        mock_log.warning.assert_called_once_with(
            "%s: dropped %d/%d records with URL not matching job_url_pattern",
            "Techstars Jobs",
            2,
            5,
        )

    def test_keeps_all_shapes_when_site_has_no_job_url_pattern(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        _make_jobs_table(conn)
        jobs = [
            {"url": "https://example.com/company/acme", "title": "Company page"},
            {"url": "https://jobs.otherhost.com/posting/123", "title": "Off-host job"},
            {"url": "/not-a-job-path", "title": "Relative oddity"},
        ]
        site = {
            "name": "Example Jobs",
            "url": "https://example.com/jobs?q={query_encoded}",
            "type": "search",
        }

        with patch("applypilot.discovery.smartextract.load_sites", return_value=[site]):
            result = _store_jobs_filtered(conn, jobs, "Example Jobs", "api_response", [], [])

        assert result == (3, 0)
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3

    def test_invalid_job_url_pattern_does_not_drop_records(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        _make_jobs_table(conn)
        jobs = [
            {"url": "https://broken.example.com/company/acme", "title": "Company page"},
            {"url": "/relative/company/acme", "title": "Relative page"},
        ]
        site = {
            "name": "Broken Jobs",
            "url": "https://broken.example.com/jobs?q={query_encoded}",
            "type": "search",
            "job_url_pattern": "[",
        }

        with patch("applypilot.discovery.smartextract.load_sites", return_value=[site]), patch(
            "applypilot.discovery.smartextract.log"
        ) as mock_log:
            result = _store_jobs_filtered(conn, jobs, "Broken Jobs", "api_response", [], [])

        assert result == (2, 0)
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
        mock_log.warning.assert_called_once_with(
            "%s: invalid job_url_pattern %r; ignoring",
            "Broken Jobs",
            "[",
        )

    def test_counts_stay_correct_when_bad_shapes_are_dropped(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        _make_jobs_table(conn)
        jobs = [
            {
                "url": "https://jobs.techstars.com/companies/acme/jobs/123-engineer",
                "title": "Platform Engineer",
            },
            {
                "url": "https://jobs.techstars.com/companies/acme/jobs/123-engineer",
                "title": "Duplicate Platform Engineer",
            },
            {
                "url": "https://www.techstars.com/docokids",
                "title": "Docokids",
            },
            {
                "url": "/docokids",
                "title": "Relative company page",
            },
        ]

        with patch("applypilot.discovery.smartextract.load_sites", return_value=[TECHSTARS_SITE]), patch(
            "applypilot.discovery.smartextract.log"
        ) as mock_log:
            result = _store_jobs_filtered(conn, jobs, "Techstars Jobs", "api_response", [], [])

        assert result == (1, 1)
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        mock_log.warning.assert_called_once_with(
            "%s: dropped %d/%d records with URL not matching job_url_pattern",
            "Techstars Jobs",
            2,
            4,
        )
