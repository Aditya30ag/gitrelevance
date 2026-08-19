"""Scenario: OBSOLETE -- issue's related file was deleted without replacement.

issue -> fix commit adds a file -> file is deleted -> HEAD => OBSOLETE

End-to-end: RepoBuilder -> FakeProvider -> AnalysisEngine.analyze()
"""

from __future__ import annotations

import git

from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.models import Classification
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import FakeProvider, assert_has_evidence, make_issue


class TestScenarioObsolete:
    def _build(self) -> tuple[str, "RepoBuilder"]:
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #3: add legacy_v1.py", files={"legacy_v1.py": "# legacy code"})
        )
        path = builder.build()
        g = git.Repo(path)
        g.index.remove(["legacy_v1.py"], working_tree=True)
        g.index.commit("Delete legacy_v1.py -- no longer needed")
        return path, builder

    def test_classification_is_obsolete(self) -> None:
        """issue -> file added -> file deleted -> HEAD => OBSOLETE."""
        path, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=3, title="Legacy V1 issue", state="closed")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()

            assert len(results) == 1
            res = results[0]
            assert res.issue.number == 3
            assert res.classification == Classification.OBSOLETE
        finally:
            builder.cleanup()

    def test_deleted_file_evidence_is_present(self) -> None:
        """Must include evidence about deleted files."""
        path, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=3, title="Legacy V1 issue", state="closed")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()
            assert_has_evidence(results[0].evidence, "deleted")
        finally:
            builder.cleanup()

    def test_deleted_file_evidence_category_is_obsolescence(self) -> None:
        """Deleted-file evidence must be in the 'obsolescence' category."""
        path, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=3, title="Legacy V1 issue", state="closed")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()
            deleted_items = [
                e for e in results[0].evidence
                if "deleted" in e.description.lower()
            ]
            assert deleted_items
            assert all(item.category == "obsolescence" for item in deleted_items)
        finally:
            builder.cleanup()

    def test_deleted_file_name_in_description(self) -> None:
        """The file path must appear in the deleted-file evidence description."""
        path, builder = self._build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=3, title="Legacy V1 issue", state="closed")
            provider = FakeProvider(issues=[issue])

            results = AnalysisEngine(repo, provider).analyze()
            deleted_items = [
                e for e in results[0].evidence
                if "deleted" in e.description.lower()
            ]
            assert deleted_items
            assert "legacy_v1.py" in deleted_items[0].description
        finally:
            builder.cleanup()
