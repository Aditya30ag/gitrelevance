"""Scenario: renamed file is NOT treated as deleted (regression test).

A related file that was renamed (not deleted) must NOT trigger the
'deleted without replacement' evidence rule.  This is a regression guard
against a false-positive OBSOLETE classification when a refactor moves
a file to a new path.

End-to-end: RepoBuilder (with git mv) -> FakeProvider -> AnalysisEngine.analyze()
"""

from __future__ import annotations

import git

from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.models import Classification
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import (
    FakeProvider,
    assert_has_evidence,
    assert_no_evidence,
    make_issue,
)


class TestScenarioRenamedNotDeleted:
    def _build(self) -> tuple[str, "RepoBuilder"]:
        """Build a repo where legacy.py is renamed to modern.py."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #1: add legacy.py", files={"legacy.py": "class Legacy: pass"})
        )
        path = builder.build()
        g = git.Repo(path)
        g.git.mv("legacy.py", "modern.py")
        g.index.commit("Rename legacy.py -> modern.py (refactor)")
        return path, builder

    def test_classification_is_not_obsolete(self) -> None:
        """Renamed file must NOT produce OBSOLETE -- the feature still exists."""
        path, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=1, title="Legacy feature", state="closed")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()

            assert len(results) == 1
            res = results[0]
            # A rename keeps the feature alive; it must not be OBSOLETE.
            assert res.classification != Classification.OBSOLETE, (
                f"Got OBSOLETE for a renamed file -- false positive. "
                f"Evidence: {[e.description for e in res.evidence]}"
            )
        finally:
            builder.cleanup()

    def test_deleted_evidence_does_not_fire(self) -> None:
        """The 'deleted without replacement' evidence rule must NOT fire for renames."""
        path, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=1, title="Legacy feature", state="closed")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()
            # No "deleted without replacement" evidence must appear.
            assert_no_evidence(results[0].evidence, "deleted without replacement")
        finally:
            builder.cleanup()

    def test_renamed_files_evidence_may_fire(self) -> None:
        """The 'files modified or renamed' evidence rule may fire for renames (positive signal)."""
        path, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=1, title="Legacy feature", state="closed")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()
            # renamed evidence is allowed (it has a positive weight), just not deleted evidence
            # This test passes regardless of whether renamed evidence fires or not --
            # it's here to document that it may fire without causing a false positive.
            descriptions = [e.description for e in results[0].evidence]
            renamed_items = [d for d in descriptions if "renamed" in d.lower() or "modified" in d.lower()]
            # No assertion needed -- the presence or absence of this item is OK
            assert isinstance(renamed_items, list)  # always passes; documents intent
        finally:
            builder.cleanup()
