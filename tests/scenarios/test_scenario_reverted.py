"""Scenario: STILL_RELEVANT (reverted) -- fix commit was later git-reverted.

issue -> fix commit -> real git revert of it -> HEAD

Classification rationale:
  The fix commit IS an ancestor of HEAD (fix_commit_in_head is set), but the
  revert-of-fix evidence fires (weight -3), setting has_unresolved_revert=True.
  This blocks RESOLVED and PROBABLY_RESOLVED.  Obsolescence score doesn't cross
  OBSOLETE_THRESHOLD (-3).  Issue is open and evidence exists -> STILL_RELEVANT.

End-to-end: RepoBuilder (with real git revert) -> FakeProvider -> AnalysisEngine.
"""

from __future__ import annotations

import git

from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.models import Classification
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import FakeProvider, assert_has_evidence, make_issue


class TestScenarioReverted:
    def _build(self):
        """Build repo and return (path, fix_sha, builder)."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #1: add feature", files={"feature.py": "def feature(): pass"})
        )
        path = builder.build()
        g = git.Repo(path)
        # second commit (index 1 in reverse-chronological means oldest non-initial)
        fix_sha = list(g.iter_commits(reverse=True))[1].hexsha
        builder.revert(fix_sha)
        return path, fix_sha, builder

    def test_classification_is_still_relevant(self) -> None:
        """After a real git revert of the fix, open issue => STILL_RELEVANT.

        The classifier reaches STILL_RELEVANT (not UNKNOWN) because:
          - has_unresolved_revert=True blocks RESOLVED and PROBABLY_RESOLVED
          - obsolescence_score > OBSOLETE_THRESHOLD (revert weight is -3 which
            exactly equals the threshold but the condition is <= so it does NOT
            trigger OBSOLETE)
          - issue is open and evidence exists -> STILL_RELEVANT fires
        """
        path, _, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=1, title="Feature issue", state="open")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()

            assert len(results) == 1
            res = results[0]
            assert res.issue.number == 1
            assert res.classification == Classification.STILL_RELEVANT
        finally:
            builder.cleanup()

    def test_revert_evidence_is_present(self) -> None:
        """Revert evidence item must appear in the evidence tuple."""
        path, _, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=1, title="Feature issue", state="open")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()
            assert_has_evidence(results[0].evidence, "reverted")
        finally:
            builder.cleanup()

    def test_revert_evidence_source_ref_points_to_revert_commit(self) -> None:
        """The revert EvidenceItem source_ref must be a short SHA of the revert commit."""
        path, fix_sha, builder = self._build()
        try:
            g = git.Repo(path)
            # The revert commit is HEAD after builder.revert()
            expected_revert_short_sha = g.head.commit.hexsha[:7]

            repo = GitRepository(path)
            issue = make_issue(number=1, title="Feature issue", state="open")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()
            revert_items = [
                e for e in results[0].evidence
                if "reverted" in e.description.lower()
            ]
            assert revert_items, "Expected a revert evidence item"
            assert revert_items[0].source_ref == expected_revert_short_sha, (
                f"Expected source_ref={expected_revert_short_sha!r}, "
                f"got {revert_items[0].source_ref!r}"
            )
        finally:
            builder.cleanup()

    def test_revert_evidence_has_negative_weight(self) -> None:
        """The revert evidence item must carry a negative weight."""
        path, _, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=1, title="Feature issue", state="open")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()
            revert_items = [
                e for e in results[0].evidence
                if "reverted" in e.description.lower()
            ]
            assert revert_items
            assert revert_items[0].weight < 0
        finally:
            builder.cleanup()
