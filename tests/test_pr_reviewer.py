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
    assert report["level"] == "HIGH"            # hotspot + missing tests = corroborated
    assert "Pre-Review Report" in report["markdown"]
    assert "Change Summary" in report["markdown"]
    # low-risk PR -> LOW
    clean = assess_risk([_file("src/a.py"), _file("tests/test_a.py")], set())
    low = build_report({"title": "y", "files": []}, clean, sim, summary=None)
    assert low["level"] == "LOW"
    print("  ok: report levels + markdown")


def test_file_risk_ignores_non_source_hotspots():
    # churn-heavy docs/tests legitimately sit in the hotspot list, but a PR
    # touching them is not editing risky code (the flask#6066 false HIGH)
    hotspots = {"CHANGES.rst", "tests/test_basic.py", "src/app.py"}
    risk = assess_risk([_file("CHANGES.rst"), _file("tests/test_basic.py")], hotspots)
    assert risk["risky_files"] == []
    assert "file_risk" not in {k for k, _ in risk["warnings"]}
    # ...while a real source hotspot still fires
    risk = assess_risk([_file("src/app.py")], hotspots)
    assert risk["risky_files"] == ["src/app.py"]
    print("  ok: file risk counts source-file hotspots only")


def test_weighted_risk_levels():
    def _risk(kinds):
        return {"warnings": [(k, k) for k in kinds], "oks": [], "notes": [],
                "files_changed": 1, "lines_added": 1}

    no_sim = {"max_score": 0.0, "matches": [], "warn": False}
    sim_warn = {"max_score": 0.7, "matches": [], "warn": True}
    pr = {"title": "t", "files": []}
    # clean -> LOW; one weak signal (0.10) stays LOW; moderate (0.20) -> MEDIUM
    assert build_report(pr, _risk([]), no_sim, None)["level"] == "LOW"
    assert build_report(pr, _risk(["unfocused"]), no_sim, None)["level"] == "LOW"
    assert build_report(pr, _risk(["missing_tests"]), no_sim, None)["level"] == "MEDIUM"
    # similarity alone (0.25) -> MEDIUM
    assert build_report(pr, _risk([]), sim_warn, None)["level"] == "MEDIUM"
    # corroborated strong evidence crosses the HIGH band (>= 0.5)
    assert build_report(pr, _risk(["file_risk", "missing_tests"]),
                        no_sim, None)["level"] == "HIGH"
    r = build_report(pr, _risk(["file_risk"]), sim_warn, None)
    assert r["level"] == "HIGH" and r["risk_score"] == 0.55
    # the arithmetic is shown, so the level is explainable
    assert "Score = " in r["markdown"]
    assert {b["signal"] for b in r["breakdown"]} == {"file_risk", "similarity"}
    print("  ok: weighted risk score + bands (LOW/MEDIUM/HIGH)")


def test_description_and_bug_echo():
    files = [_file("src/auth/session.py")]
    # no PR body -> weak-description warning; recently-fixed file -> bug echo
    risk = assess_risk(files, set(),
                       recently_fixed={"src/auth/session.py": 6.0})
    kinds = {k for k, _ in risk["warnings"]}
    assert "weak_description" in kinds and "bug_echo" in kinds
    assert risk["bug_echo_files"] == ["src/auth/session.py"]
    # a clear description scores OK instead (Tool 4's scorer, reused)
    risk = assess_risk(
        files, set(), title="Fix session expiry handling",
        body="Refactor token validation because expiry was rechecked twice. "
             "Closes #42.")
    assert "weak_description" not in {k for k, _ in risk["warnings"]}
    assert any("description present" in ok for ok in risk["oks"])
    print("  ok: PR description quality + bug-echo checks")


def test_new_file_blind_spot_and_coverage_note():
    files = [_file("src/newmod.py", additions=300, status="added")]
    risk = assess_risk(files, set())
    assert any("no history" in n for n in risk["notes"])
    # when hotspot/similarity data was unavailable, the report says so
    sim = {"max_score": 0.0, "matches": [], "warn": False}
    report = build_report({"title": "t", "files": files}, risk, sim, None,
                          coverage={"hotspots": False, "similarity": False})
    assert any("risk computed from" in n for n in report["notes"])
    assert "Notes" in report["markdown"]
    print("  ok: new-file blind-spot note + coverage honesty note")


def test_bug_index_skips_docs_only_fixes():
    from pipeline.build_bug_index import build_bug_diff_index

    class _FakeGit:
        def commit_diff(self, sha):
            return f"diff for {sha}"

    commits = [
        {"sha": "a" * 12, "message": "Fix typo in the changelog", "is_bugfix": True,
         "files": [{"path": "CHANGES.rst"}]},
        {"sha": "b" * 12, "message": "Fix session expiry bug", "is_bugfix": True,
         "files": [{"path": "src/session.py"}, {"path": "CHANGES.rst"}]},
        {"sha": "c" * 12, "message": "Add feature", "is_bugfix": False,
         "files": [{"path": "src/feature.py"}]},
    ]
    _, n = build_bug_diff_index(commits, _FakeGit(),
                                _settings(similarity_backend="lite"))
    assert n == 1  # only the fix that touched source code is indexed
    print("  ok: bug-diff corpus skips docs/config-only fixes")


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
