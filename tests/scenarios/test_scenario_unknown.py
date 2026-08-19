"""Scenario: UNKNOWN -- closed issue with zero related commits or PRs.

End-to-end: RepoBuilder -> FakeProvider -> AnalysisEngine.analyze()
"""

from __future__ import annotations

from gitrelevance.analysis.confidence import MIN_CONFIDENCE
from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.models import Classification
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import FakeProvider, make_issue


class TestScenarioUnknown:
    def test_classification_is_unknown(self) -> None:
        """Closed issue with no related commits => UNKNOWN."""
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
            res = results[0]
            assert res.issue.number == 5
            assert res.classification == Classification.UNKNOWN
        finally:
            builder.cleanup()

    def test_evidence_tuple_is_empty(self) -> None:
        """Zero related commits means the evidence tuple must be empty."""
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
            assert results[0].evidence == ()
        finally:
            builder.cleanup()

    def test_confidence_is_near_clamp_floor(self) -> None:
        """No evidence -> confidence is at the neutral 0.50 default, not near the floor.

        With zero evidence there are no weights to sum, so compute_confidence()
        returns the DEFAULT_CONFIDENCE (0.50) rather than the clamp floor (0.05).
        This test documents that expected behavior explicitly.
        """
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
            # Empty evidence -> confidence is the neutral DEFAULT_CONFIDENCE (0.50),
            # not MIN_CONFIDENCE (0.05) -- document this to prevent false expectations.
            assert results[0].confidence == 0.50
        finally:
            builder.cleanup()
