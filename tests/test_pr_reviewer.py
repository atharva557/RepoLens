"""Tests for the PR Review Assistant (Tool 3).

Risk checks, similarity assessment, report assembly, and the LLM summarizer are
all exercised without network or heavy deps (LiteIndex + FakeProvider).

    python tests/test_pr_reviewer.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.embeddings import LiteIndex
from core.llm import FakeProvider
from tools.pr_reviewer.llm_summarizer import summarize
from tools.pr_reviewer.report_builder import build_report
from tools.pr_reviewer.risk_scorer import assess_risk
from tools.pr_reviewer.runner import parse_pr_spec
from tools.pr_reviewer.similarity import assess_similarity


def _file(path, additions=10, deletions=1, status="modified"):
    return {"path": path, "additions": additions, "deletions": deletions,
            "status": status, "patch": f"@@ patch for {path} @@"}


def _settings(**over):
    base = dict(pr_similarity_top_k=5, pr_similarity_warn=0.6)
    base.update(over)
    return SimpleNamespace(**base)


def test_missing_tests_and_file_risk():
    files = [_file("src/auth/session.py", additions=30)]
    risk = assess_risk(files, hotspot_paths={"src/auth/session.py"})
    kinds = {k for k, _ in risk["warnings"]}
    assert "missing_tests" in kinds
    assert "file_risk" in kinds
    assert risk["risky_files"] == ["src/auth/session.py"]
    print("  ok: missing-tests + file-risk warnings")


def test_tests_present_and_focused_ok():
    files = [_file("src/app.py"), _file("tests/test_app.py")]
    risk = assess_risk(files, hotspot_paths=set())
    kinds = {k for k, _ in risk["warnings"]}
    assert "missing_tests" not in kinds
    assert any("tests updated" in ok for ok in risk["oks"])
    assert any("focused" in ok for ok in risk["oks"])
    print("  ok: tests-present + focused OK")


def test_unfocused_and_large():
    files = [_file(f"area{i}/mod{i}.py", additions=60) for i in range(14)]
    risk = assess_risk(files, hotspot_paths=set())
    kinds = {k for k, _ in risk["warnings"]}
    assert "unfocused" in kinds
    assert "large_change" in kinds
    print("  ok: unfocused + large-change warnings")


def test_similarity_flags_known_bug_diff():
    index = LiteIndex()
    index.build([
        {"id": "bug1", "text": "fix null pointer in session token validation on expiry",
         "meta": {"sha": "bug1"}},
        {"id": "x", "text": "add unrelated payments refund route", "meta": {"sha": "x"}},
    ])
    pr = {"files": [{"patch": "session token validation null pointer on expiry fix"}]}
    sim = assess_similarity(index, pr, _settings(pr_similarity_warn=0.2))
    assert sim["matches"][0]["id"] == "bug1"
    assert sim["warn"] is True
    print("  ok: similarity flags a bug-like diff")


def test_report_levels_and_markdown():
    files = [_file("src/auth/session.py", additions=20)]
    risk = assess_risk(files, hotspot_paths={"src/auth/session.py"})
    sim = {"max_score": 0.1, "matches": [], "warn": False}
    report = build_report({"title": "x", "files": files}, risk, sim, summary="Does X.")
    assert report["level"] == "HIGH"            # touches a hotspot
    assert "Pre-Review Report" in report["markdown"]
    assert "Change Summary" in report["markdown"]
    # low-risk PR -> LOW
    clean = assess_risk([_file("src/a.py"), _file("tests/test_a.py")], set())
    low = build_report({"title": "y", "files": []}, clean, sim, summary=None)
    assert low["level"] == "LOW"
    print("  ok: report levels + markdown")


def test_summarizer_and_spec_parsing():
    pr = {"title": "t", "files": [{"patch": "some diff"}]}
    assert summarize(FakeProvider("It changes X."), pr) == "It changes X."
    assert summarize(None, pr) is None
    assert summarize(FakeProvider(available=False), pr) is None
    assert parse_pr_spec("octocat/Hello-World#42") == ("octocat", "Hello-World", 42)
    assert parse_pr_spec("https://github.com/a/b/pull/7") == ("a", "b", 7)
    print("  ok: summarizer + PR-spec parsing")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"running {len(fns)} test(s)...")
    for fn in fns:
        fn()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    _run_all()
