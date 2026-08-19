"""End-to-end scenario tests for AnalysisEngine."""

from __future__ import annotations

from datetime import datetime, timezone
import git
import pytest

from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.issues.models import Issue, PullRequest
from gitrelevance.models import Classification
from gitrelevance.providers.base import Provider
from tests.fixtures.repo_builder import RepoBuilder


class FakeProvider:
    """In-memory fake provider for scenario testing."""

    def __init__(
        self,
        issues: list[Issue] | None = None,
        pull_requests: list[PullRequest] | None = None,
    ) -> None:
        self.issues = issues or []
        self.pull_requests = pull_requests or []

    def parse_remote(self, remote_url: str) -> tuple[str, str] | None:
        return ("fake_owner", "fake_repo")

    def get_issues(self, state: str = "all") -> list[Issue]:
        return self.issues

    def get_pull_requests(self, state: str = "all") -> list[PullRequest]:
        return self.pull_requests

    def get_issue_comments(self, issue_number: int) -> list[str]:
        return []


def make_issue(
    number: int,
    title: str = "Test Issue",
    state: str = "open",
    linked_pr_numbers: tuple[int, ...] = (),
) -> Issue:
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


class TestAnalysisScenarios:
    """End-to-end scenario tests matching the 5 core specifications."""

    def test_scenario_1_resolved(self) -> None:
        """Scenario 1: issue -> fix commit -> HEAD => RESOLVED."""
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

            engine = AnalysisEngine(repo, provider)
            results = engine.analyze()

            assert len(results) == 1
            res = results[0]
            assert res.issue.number == 1
            assert res.classification == Classification.RESOLVED
            assert res.confidence >= 0.70
            assert any("Fix commit" in e.description for e in res.evidence)
        finally:
            builder.cleanup()

    def test_scenario_2_reverted_fix(self) -> None:
        """Scenario 2: issue -> fix commit -> real git revert of it -> HEAD => STILL_RELEVANT.

        Explanation:
        The fix commit for issue #1 was reverted via genuine 'git revert', which generates
        a revert-of-fix evidence item (weight -3). This invalidates the RESOLVED and PROBABLY_RESOLVED
        classifications. Since issue #1 is open and its related files still exist, the pipeline
        correctly classifies it as STILL_RELEVANT.
        """
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

            engine = AnalysisEngine(repo, provider)
            results = engine.analyze()

            assert len(results) == 1
            res = results[0]
            assert res.issue.number == 1
            assert res.classification == Classification.STILL_RELEVANT
            assert any("reverted" in e.description.lower() for e in res.evidence)
        finally:
            builder.cleanup()

    def test_scenario_3_obsolete(self) -> None:
        """Scenario 3: issue -> file referenced -> file deleted -> HEAD => OBSOLETE."""
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

            engine = AnalysisEngine(repo, provider)
            results = engine.analyze()

            assert len(results) == 1
            res = results[0]
            assert res.issue.number == 3
            assert res.classification == Classification.OBSOLETE
            assert any("deleted" in e.description.lower() for e in res.evidence)
        finally:
            builder.cleanup()

    def test_scenario_4_still_relevant(self) -> None:
        """Scenario 4: open issue -> related code still exists -> no fix => STILL_RELEVANT."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme", "core.py": "def run(): pass"})
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=4, title="Refactor core", state="open", linked_pr_numbers=(10,))
            pr10 = PullRequest(
                number=10,
                title="WIP core PR",
                merged=False,
                merge_commit_sha=None,
                closes_issue_numbers=(),
                files_changed=("core.py",),
            )
            provider = FakeProvider(issues=[issue], pull_requests=[pr10])

            engine = AnalysisEngine(repo, provider)
            results = engine.analyze()

            assert len(results) == 1
            res = results[0]
            assert res.issue.number == 4
            assert res.classification == Classification.STILL_RELEVANT
            assert any("files exist" in e.description.lower() for e in res.evidence)
        finally:
            builder.cleanup()

    def test_scenario_5_unknown(self) -> None:
        """Scenario 5: closed issue -> no related commit at all => UNKNOWN."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=5, title="Unrelated issue", state="closed")
            provider = FakeProvider(issues=[issue])

            engine = AnalysisEngine(repo, provider)
            results = engine.analyze()

            assert len(results) == 1
            res = results[0]
            assert res.issue.number == 5
            assert res.classification == Classification.UNKNOWN
            assert res.evidence == ()
        finally:
            builder.cleanup()
