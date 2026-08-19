"""Scenario: RESOLVED -- issue fixed by a commit that is in HEAD ancestry.

End-to-end: RepoBuilder -> FakeProvider -> AnalysisEngine.analyze()
"""

from __future__ import annotations

from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.models import Classification
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import FakeProvider, assert_has_evidence, make_issue


class TestScenarioResolved:
    def test_classification_is_resolved(self) -> None:
        """issue -> fix commit -> HEAD => RESOLVED."""
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
            res = results[0]
            assert res.issue.number == 1
            assert res.classification == Classification.RESOLVED
        finally:
            builder.cleanup()

    def test_confidence_is_high(self) -> None:
        """RESOLVED result must have high confidence (>= 0.70)."""
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
            assert results[0].confidence >= 0.70
        finally:
            builder.cleanup()

    def test_fix_commit_evidence_present(self) -> None:
        """RESOLVED result must include evidence about the fix commit in HEAD."""
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
            evidence = results[0].evidence
            assert_has_evidence(evidence, "Fix commit")
        finally:
            builder.cleanup()

    def test_fix_commit_source_ref_is_short_sha(self) -> None:
        """Fix-commit evidence source_ref must be a 7-char short SHA."""
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
            fix_items = [
                e for e in results[0].evidence
                if "Fix commit" in e.description
            ]
            assert fix_items, "Expected a 'Fix commit' evidence item"
            for item in fix_items:
                assert item.source_ref is not None
                assert len(item.source_ref) == 7, (
                    f"source_ref '{item.source_ref}' is not a 7-char short SHA"
                )
        finally:
            builder.cleanup()
