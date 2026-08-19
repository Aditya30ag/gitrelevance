"""Scenario: STILL_RELEVANT -- open issue, related code still exists, no fix commit.

End-to-end: RepoBuilder -> FakeProvider -> AnalysisEngine.analyze()
"""

from __future__ import annotations

from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.issues.models import PullRequest
from gitrelevance.models import Classification
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import FakeProvider, assert_has_evidence, make_issue


class TestScenarioStillRelevant:
    def test_classification_is_still_relevant(self) -> None:
        """open issue + related code still exists + no fix => STILL_RELEVANT."""
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
            res = results[0]
            assert res.issue.number == 4
            assert res.classification == Classification.STILL_RELEVANT
        finally:
            builder.cleanup()

    def test_files_exist_evidence_present(self) -> None:
        """Related files still exist -> files-exist evidence must fire."""
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
            assert_has_evidence(results[0].evidence, "files exist")
        finally:
            builder.cleanup()

    def test_no_fix_commit_evidence(self) -> None:
        """No fix commit => the fix-commit-in-HEAD evidence rule must NOT fire."""
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
            fix_items = [
                e for e in results[0].evidence
                if "Fix commit is present" in e.description
            ]
            assert not fix_items, (
                "Unexpected fix-commit evidence in STILL_RELEVANT scenario"
            )
        finally:
            builder.cleanup()

    def test_issue_must_be_open(self) -> None:
        """Closed issue in identical repo would NOT classify as STILL_RELEVANT."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme", "core.py": "def run(): pass"})
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            # Same setup but closed -- files exist but no fix -> UNKNOWN
            issue = make_issue(number=4, title="Refactor core", state="closed", linked_pr_numbers=(10,))
            pr10 = PullRequest(
                number=10, title="WIP core PR", merged=False,
                merge_commit_sha=None, closes_issue_numbers=(), files_changed=("core.py",),
            )
            provider = FakeProvider(issues=[issue], pull_requests=[pr10])

            results = AnalysisEngine(repo, provider).analyze()
            assert results[0].classification != Classification.STILL_RELEVANT
        finally:
            builder.cleanup()
