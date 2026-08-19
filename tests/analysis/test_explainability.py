"""Phase 6 explainability tests.

Every AnalysisResult must be self-contained for terminal display -- no additional
Git or GitHub lookups should be needed to explain a classification.

Properties asserted for each scenario:
  1. Every EvidenceItem has a non-empty description.
  2. Every EvidenceItem in category "strong" or "obsolescence" that references a
     specific commit or PR has a non-None source_ref.
  3. An AnalysisResult can be fully rendered to a plain-text summary using only
     fields on the object itself (proved by the tiny render_result() helper below).
"""

from __future__ import annotations

from datetime import datetime, timezone

import git
import pytest

from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.issues.models import Issue, PullRequest
from gitrelevance.models import AnalysisResult, EvidenceItem
from tests.fixtures.repo_builder import RepoBuilder


# ---------------------------------------------------------------------------
# Plain-text renderer -- uses ONLY fields on AnalysisResult, no extra lookups
# ---------------------------------------------------------------------------

def render_result(result: AnalysisResult) -> str:
    """Render an AnalysisResult to a plain-text summary using only its own fields."""
    lines: list[str] = [
        f"Issue #{result.issue.number}: {result.issue.title}",
        f"  State       : {result.issue.state}",
        f"  Classification: {result.classification.value}",
        f"  Confidence  : {result.confidence:.2f}  (evidence-strength heuristic, not a probability)",
        f"  Evidence ({len(result.evidence)} item(s)):",
    ]
    for item in result.evidence:
        ref = f" [{item.source_ref}]" if item.source_ref else ""
        lines.append(
            f"    {item.category:14s}  {item.weight:+d}  {item.description}{ref}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class FakeProvider:
    """In-memory fake provider for explainability testing."""

    def __init__(self, issues=None, pull_requests=None):
        self.issues = issues or []
        self.pull_requests = pull_requests or []

    def parse_remote(self, remote_url):
        return ("fake_owner", "fake_repo")

    def get_issues(self, state="all"):
        return self.issues

    def get_pull_requests(self, state="all"):
        return self.pull_requests

    def get_issue_comments(self, issue_number):
        return []


def make_issue(number, title="Test Issue", state="open", linked_pr_numbers=()):
    return Issue(
        number=number,
        title=title,
        body="Issue description",
        state="closed" if state == "closed" else "open",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc) if state == "closed" else None,
        labels=(),
        linked_pr_numbers=linked_pr_numbers,
    )


def assert_explainability_invariants(result: AnalysisResult) -> None:
    """Assert all Phase 6 explainability invariants on a single AnalysisResult."""
    # 1. Every EvidenceItem has a non-empty description.
    for item in result.evidence:
        assert item.description.strip(), (
            f"EvidenceItem in category '{item.category}' has an empty description"
        )

    # 2. Strong/obsolescence items referencing a commit or PR must have source_ref.
    commit_or_pr_keywords = ("commit", "merged", "revert", "referenced")
    for item in result.evidence:
        if item.category in ("strong", "obsolescence"):
            desc_lower = item.description.lower()
            if any(kw in desc_lower for kw in commit_or_pr_keywords):
                assert item.source_ref is not None, (
                    f"'{item.description}' (category={item.category}) has source_ref=None"
                )
                assert item.source_ref.strip(), (
                    f"'{item.description}' has an empty source_ref"
                )

    # 3. render_result() must succeed using only fields on result.
    rendered = render_result(result)
    assert str(result.issue.number) in rendered
    assert result.issue.title in rendered
    assert result.classification.value in rendered
    assert f"{result.confidence:.2f}" in rendered


class TestExplainabilityScenario1Resolved:
    def test_invariants(self):
        """Scenario 1: RESOLVED result is fully self-contained for display."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #1: login bug", files={"auth.py": "def login(): pass"})
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=1, title="Login bug", state="closed")
            provider = FakeProvider(issues=[issue])
            results = AnalysisEngine(repo, provider).analyze()
            assert len(results) == 1
            assert_explainability_invariants(results[0])
            # Commit source_refs must be 7-char short SHAs
            for item in results[0].evidence:
                if item.source_ref and not item.source_ref.startswith("PR #"):
                    assert len(item.source_ref) == 7, (
                        f"source_ref '{item.source_ref}' is not a 7-char short SHA"
                    )
        finally:
            builder.cleanup()


class TestExplainabilityScenario2Reverted:
    def test_invariants(self):
        """Scenario 2: STILL_RELEVANT result (reverted fix) is fully self-contained."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #1: add feature", files={"feature.py": "def feature(): pass"})
        )
        path = builder.build()
        try:
            g = git.Repo(path)
            fix_sha = list(g.iter_commits(reverse=True))[1].hexsha
            builder.revert(fix_sha)
            repo = GitRepository(path)
            issue = make_issue(number=1, title="Feature issue", state="open")
            provider = FakeProvider(issues=[issue])
            results = AnalysisEngine(repo, provider).analyze()
            assert len(results) == 1
            assert_explainability_invariants(results[0])
            revert_items = [e for e in results[0].evidence if "reverted" in e.description.lower()]
            assert revert_items, "Expected a revert evidence item"
            for item in revert_items:
                assert item.source_ref is not None
                assert len(item.source_ref) == 7, (
                    f"Revert source_ref '{item.source_ref}' must be 7-char short SHA"
                )
        finally:
            builder.cleanup()


class TestExplainabilityScenario3Obsolete:
    def test_invariants(self):
        """Scenario 3: OBSOLETE result is fully self-contained."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #3: add legacy_v1.py", files={"legacy_v1.py": "# legacy"})
        )
        path = builder.build()
        try:
            g = git.Repo(path)
            g.index.remove(["legacy_v1.py"], working_tree=True)
            g.index.commit("Delete legacy_v1.py")
            repo = GitRepository(path)
            issue = make_issue(number=3, title="Legacy V1 issue", state="closed")
            provider = FakeProvider(issues=[issue])
            results = AnalysisEngine(repo, provider).analyze()
            assert len(results) == 1
            assert_explainability_invariants(results[0])
            deleted_items = [e for e in results[0].evidence if "deleted" in e.description.lower()]
            assert deleted_items, "Expected a deleted-files evidence item"
        finally:
            builder.cleanup()


class TestExplainabilityScenario4StillRelevant:
    def test_invariants(self):
        """Scenario 4: STILL_RELEVANT result is fully self-contained."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme", "core.py": "def run(): pass"})
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=4, title="Refactor core", state="open", linked_pr_numbers=(10,))
            pr10 = PullRequest(
                number=10, title="WIP core PR", merged=False,
                merge_commit_sha=None, closes_issue_numbers=(), files_changed=("core.py",),
            )
            provider = FakeProvider(issues=[issue], pull_requests=[pr10])
            results = AnalysisEngine(repo, provider).analyze()
            assert len(results) == 1
            assert_explainability_invariants(results[0])
        finally:
            builder.cleanup()


class TestExplainabilityScenario5Unknown:
    def test_invariants(self):
        """Scenario 5: UNKNOWN result with empty evidence is self-contained."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=5, title="Unrelated issue", state="closed")
            provider = FakeProvider(issues=[issue])
            results = AnalysisEngine(repo, provider).analyze()
            assert len(results) == 1
            result = results[0]
            assert_explainability_invariants(result)
            rendered = render_result(result)
            assert "0 item(s)" in rendered
        finally:
            builder.cleanup()
