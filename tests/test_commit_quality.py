"""Tests for the Commit Message Quality Analyzer (Tool 4).

Rule-based scorer + reporter are pure stdlib; the suggester is tested with the
in-process FakeProvider (no network, no LLM SDK).

    python tests/test_commit_quality.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import FakeProvider
from tools.commit_quality.reporter import build_report
from tools.commit_quality.scorer import score_message
from tools.commit_quality.suggester import suggest

NOW = datetime(2026, 6, 29, tzinfo=timezone.utc)

GOOD = ("Fix null pointer in session validation when token expires\n\n"
        "The validation logic did not handle a token expiring mid-request, "
        "causing a 500 error. Closes #142")


def test_vague_messages_score_low():
    for msg in ("fix", "update", "wip", "fix bug", "update stuff", "minor changes"):
        res = score_message(msg)
        assert res["vague"], msg
        assert res["score"] < 4, (msg, res["score"])
    print("  ok: vague messages score low")


def test_good_message_scores_high():
    res = score_message(GOOD)
    assert res["score"] >= 8, res
    assert res["imperative"] and res["has_context"] and res["has_reference"]
    assert res["issues"] == [], res["issues"]
    print("  ok: good message scores high")


def test_individual_dimensions():
    assert score_message("Add user authentication endpoint")["imperative"]
    assert not score_message("user authentication endpoint")["imperative"]
    assert score_message("Fix crash (#142)")["has_reference"]
    assert score_message("Fix crash JIRA-42")["has_reference"]
    assert not score_message("Fix crash")["has_reference"]
    # too-short subject is flagged
    assert any("too short" in i for i in score_message("fix")["issues"])
    print("  ok: individual dimensions")


def _commit(days_ago, author, msg):
    return {"sha": f"sha{days_ago:04d}", "author": author,
            "date": NOW - timedelta(days=days_ago), "message": msg}


def test_report_aggregation():
    commits = [
        _commit(1, "alice", GOOD),
        _commit(2, "bob", "fix"),
        _commit(3, "bob", "update stuff"),
        _commit(40, "alice", "Add payments route with validation and tests"),
    ]
    rep = build_report(commits)
    assert rep["commits"] == 4
    assert 0 <= rep["avg_score"] <= 10
    assert rep["weak"] >= 2                       # the two vague ones
    # bob (two vague commits) should rank below alice
    by = {c["author"]: c for c in rep["contributors"]}
    assert by["bob"]["avg_score"] < by["alice"]["avg_score"]
    # worst-first ordering
    assert rep["worst"][0]["score"] <= rep["worst"][-1]["score"]
    assert rep["common_issues"]
    print("  ok: report aggregation")


def test_suggester_with_fake_and_no_llm():
    assert suggest(FakeProvider("Better: Fix the bug"), "fix", "diff") == "Better: Fix the bug"
    assert "unavailable" in suggest(None, "fix", "diff").lower()
    assert "unavailable" in suggest(FakeProvider(available=False), "fix", "diff").lower()
    print("  ok: suggester (fake + no-LLM)")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
