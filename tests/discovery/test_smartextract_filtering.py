"""Tests for smart extraction target and record filtering."""

import os
import sqlite3
import sys
from unittest.mock import patch

# Ensure src is on sys.path for tests when running from repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from applypilot.discovery.smartextract import (
    _store_jobs_filtered,
    build_scrape_targets,
)


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


class TestBuildScrapeTargets:
    """Tests for scrape target expansion and deduplication."""

    def test_search_site_without_query_placeholder_is_deduplicated(self):
        sites = [{"name": "Example", "type": "search", "url": "https://example.com/jobs"}]
        search_cfg = {"queries": [{"query": "engineer"}, {"query": "designer"}]}

        with patch("applypilot.discovery.smartextract.log") as mock_log:
            targets = build_scrape_targets(sites=sites, search_cfg=search_cfg)

        assert targets == [{"name": "Example", "url": "https://example.com/jobs", "query": "engineer"}]
        mock_log.info.assert_called_once_with("Deduplicated scrape targets: %d -> %d", 2, 1)

    def test_search_site_with_query_placeholder_expands_per_query(self):
        sites = [{
            "name": "Example",
            "type": "search",
            "url": "https://example.com/jobs?q={query_encoded}",
        }]
        search_cfg = {"queries": [{"query": "machine learning"}, {"query": "designer"}]}

        targets = build_scrape_targets(sites=sites, search_cfg=search_cfg)

        assert targets == [
            {
                "name": "Example",
                "url": "https://example.com/jobs?q=machine+learning",
                "query": "machine learning",
            },
            {
                "name": "Example",
                "url": "https://example.com/jobs?q=designer",
                "query": "designer",
            },
        ]


class TestStoreJobsFiltered:
    """Tests for smart extraction database filtering."""

    def test_drops_records_without_titles(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        _make_jobs_table(conn)
        jobs = [
            {"url": "https://example.com/missing", "title": None},
            {"url": "https://example.com/empty", "title": ""},
            {"url": "https://example.com/whitespace", "title": "   "},
            {"url": "https://example.com/valid", "title": "Software Engineer"},
        ]

        with patch("applypilot.discovery.smartextract.log") as mock_log:
            result = _store_jobs_filtered(conn, jobs, "Example", "api_response", [], [])

        assert result == (1, 0)
        rows = conn.execute("SELECT url, title FROM jobs ORDER BY url").fetchall()
        assert rows == [("https://example.com/valid", "Software Engineer")]
        mock_log.warning.assert_called_once_with(
            "%s: dropped %d/%d records with no title", "Example", 3, 4
        )

    def test_all_records_without_titles_are_dropped(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        _make_jobs_table(conn)
        jobs = [
            {"url": "https://example.com/one", "title": None},
            {"url": "https://example.com/two", "title": "  \t"},
        ]

        result = _store_jobs_filtered(conn, jobs, "Example", "api_response", [], [])

        assert result == (0, 0)
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
