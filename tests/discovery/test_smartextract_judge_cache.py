"""Tests for smart extraction API response judge denylist and cache."""

import os
import sys
from unittest.mock import Mock, patch

import pytest

# Ensure src is on sys.path for tests when running from repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from applypilot.discovery.smartextract import (
    _reset_judge_verdict_cache,
    judge_api_responses,
)


@pytest.fixture(autouse=True)
def reset_judge_cache():
    _reset_judge_verdict_cache()
    yield
    _reset_judge_verdict_cache()


def _make_response(url: str, **extra: object) -> dict:
    response = {
        "url": url,
        "status": 200,
        "size": 1234,
        "type": "json",
    }
    response.update(extra)
    return response


def test_denylisted_host_is_dropped_without_llm_call():
    client = Mock()

    with (
        patch("applypilot.discovery.smartextract.config.load_judge_denylist",
              return_value=["sentry.io"]),
        patch("applypilot.discovery.smartextract.get_client", return_value=client),
    ):
        result = judge_api_responses([
            _make_response("https://o50017.ingest.us.sentry.io/api/1268170/envelope/?sentry_key=abc"),
        ])

    assert result == []
    client.chat.assert_not_called()


def test_same_host_and_path_different_query_uses_one_llm_call():
    client = Mock()
    client.chat.return_value = '{"relevant": true, "reason": "job listings"}'
    responses = [
        _make_response("https://ads.example.com/jobs?pubid=157743"),
        _make_response("https://ads.example.com/jobs?pubid=162412"),
    ]

    with (
        patch("applypilot.discovery.smartextract.config.load_judge_denylist", return_value=[]),
        patch("applypilot.discovery.smartextract.get_client", return_value=client),
    ):
        result = judge_api_responses(responses)

    assert result == responses
    assert client.chat.call_count == 1


def test_segment_careers_host_is_not_denylisted_by_segment_com_entry():
    client = Mock()
    client.chat.return_value = '{"relevant": true, "reason": "job listings"}'
    response = _make_response("https://segment-careers.com/api/jobs")

    with (
        patch("applypilot.discovery.smartextract.config.load_judge_denylist",
              return_value=["segment.com"]),
        patch("applypilot.discovery.smartextract.get_client", return_value=client),
    ):
        result = judge_api_responses([response])

    assert result == [response]
    client.chat.assert_called_once()


def test_same_host_different_paths_use_separate_llm_calls():
    client = Mock()
    client.chat.side_effect = [
        '{"relevant": true, "reason": "job listings"}',
        '{"relevant": true, "reason": "job listings"}',
    ]
    responses = [
        _make_response("https://api.example.com/jobs"),
        _make_response("https://api.example.com/jobs/search"),
    ]

    with (
        patch("applypilot.discovery.smartextract.config.load_judge_denylist", return_value=[]),
        patch("applypilot.discovery.smartextract.get_client", return_value=client),
    ):
        result = judge_api_responses(responses)

    assert result == responses
    assert client.chat.call_count == 2


def test_same_host_and_path_different_shape_uses_two_llm_calls():
    client = Mock()
    client.chat.side_effect = [
        '{"relevant": true, "reason": "job listings"}',
        '{"relevant": false, "reason": "metadata"}',
    ]
    keep_response = _make_response(
        "https://api.example.com/jobs?query=engineer",
        first_item_keys=["title", "company"],
    )
    drop_response = _make_response(
        "https://api.example.com/jobs?query=designer",
        first_item_keys=["error", "message"],
    )

    with (
        patch("applypilot.discovery.smartextract.config.load_judge_denylist", return_value=[]),
        patch("applypilot.discovery.smartextract.get_client", return_value=client),
    ):
        result = judge_api_responses([keep_response, drop_response])

    assert result == [keep_response]
    assert client.chat.call_count == 2


def test_keep_and_drop_verdicts_affect_output():
    keep_client = Mock()
    keep_client.chat.return_value = '{"relevant": true, "reason": "job listings"}'
    drop_client = Mock()
    drop_client.chat.return_value = '{"relevant": false, "reason": "telemetry"}'

    with (
        patch("applypilot.discovery.smartextract.config.load_judge_denylist", return_value=[]),
        patch("applypilot.discovery.smartextract.get_client", return_value=keep_client),
    ):
        kept = judge_api_responses([_make_response("https://api.example.com/jobs")])

    with (
        patch("applypilot.discovery.smartextract.config.load_judge_denylist", return_value=[]),
        patch("applypilot.discovery.smartextract.get_client", return_value=drop_client),
    ):
        dropped = judge_api_responses([_make_response("https://api.example.com/telemetry")])

    assert kept == [_make_response("https://api.example.com/jobs")]
    assert dropped == []


def test_llm_exception_keeps_response_and_does_not_cache_failure():
    client = Mock()
    response = _make_response("https://api.example.com/jobs")
    client.chat.side_effect = [
        RuntimeError("transient failure"),
        '{"relevant": false, "reason": "telemetry"}',
    ]

    with (
        patch("applypilot.discovery.smartextract.config.load_judge_denylist", return_value=[]),
        patch("applypilot.discovery.smartextract.get_client", return_value=client),
    ):
        first_result = judge_api_responses([response])
        second_result = judge_api_responses([response])

    assert first_result == [response]
    assert second_result == []
    assert client.chat.call_count == 2
