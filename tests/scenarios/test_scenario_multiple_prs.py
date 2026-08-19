"""Scenario: multiple PRs linked to a single issue (e.g. reopened issue).

Asserts that build_all_match_sets correctly handles multiple linked PRs:
- related_files is the union of files from all matched PRs
- no errors when the same issue matches multiple PRs
- the issue can appear in closes_issue_numbers of several PRs simultaneously

End-to-end: RepoBuilder -> FakeProvider -> AnalysisEngine.analyze()
"""

from __future__ import annotations

from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.analysis.matcher import build_match_set
from gitrelevance.git.repository import GitRepository
from gitrelevance.issues.models import PullRequest
from gitrelevance.models import Classification
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import FakeProvider, make_issue, make_pr


class TestScenarioMultiplePRs:
    def _build_setup(self):
        """Build repo + issue + two PRs (both closing issue #7)."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #7: first attempt", files={"fix_a.py": "# fix a"})
            .commit("Fix #7: second approach", files={"fix_b.py": "# fix b"})
        )
        path = builder.build()
        issue = make_issue(number=7, title="Complex issue", state="closed")
        # PR #20 closes #7 and touches fix_a.py
        pr20 = PullRequest(
            number=20, title="First fix PR", merged=True,
            merge_commit_sha=None, closes_issue_numbers=(7,), files_changed=("fix_a.py",),
        )
        # PR #21 also closes #7 and touches fix_b.py
        pr21 = PullRequest(
            number=21, title="Second fix PR", merged=True,
            merge_commit_sha=None, closes_issue_numbers=(7,), files_changed=("fix_b.py",),
        )
        return path, issue, [pr20, pr21], builder

    def test_no_error_with_multiple_prs(self) -> None:
        """build_all_match_sets must not raise with multiple PRs for one issue."""
        path, issue, prs, builder = self._build_setup()
        try:
            repo = GitRepository(path)
            provider = FakeProvider(issues=[issue], pull_requests=prs)
            # Must not raise
            results = AnalysisEngine(repo, provider).analyze()
            assert len(results) == 1
        finally:
            builder.cleanup()

    def test_related_files_unions_across_both_prs(self) -> None:
        """related_files must include files from BOTH linked PRs."""
        path, issue, prs, builder = self._build_setup()
        try:
            repo = GitRepository(path)
            match_set = build_match_set(issue, repo, prs)
            assert "fix_a.py" in match_set.related_files, (
                f"fix_a.py missing from related_files: {match_set.related_files}"
            )
            assert "fix_b.py" in match_set.related_files, (
                f"fix_b.py missing from related_files: {match_set.related_files}"
            )
        finally:
            builder.cleanup()

    def test_both_prs_appear_in_linked_prs(self) -> None:
        """Both PRs closing the issue must appear in match_set.linked_prs."""
        path, issue, prs, builder = self._build_setup()
        try:
            repo = GitRepository(path)
            match_set = build_match_set(issue, repo, prs)
            linked_numbers = {pr.number for pr in match_set.linked_prs}
            assert 20 in linked_numbers
            assert 21 in linked_numbers
        finally:
            builder.cleanup()

    def test_merged_pr_evidence_fires_for_at_least_one_pr(self) -> None:
        """At least one 'PR merged' evidence item must appear (first-match wins)."""
        path, issue, prs, builder = self._build_setup()
        try:
            repo = GitRepository(path)
            provider = FakeProvider(issues=[issue], pull_requests=prs)

            results = AnalysisEngine(repo, provider).analyze()
            pr_evidence = [
                e for e in results[0].evidence
                if "merged" in e.description.lower()
            ]
            assert pr_evidence, (
                "Expected at least one merged-PR evidence item for two closing PRs"
            )
        finally:
            builder.cleanup()

    def test_source_ref_is_pr_format(self) -> None:
        """Merged-PR evidence source_ref must use 'PR #N' format."""
        path, issue, prs, builder = self._build_setup()
        try:
            repo = GitRepository(path)
            provider = FakeProvider(issues=[issue], pull_requests=prs)

            results = AnalysisEngine(repo, provider).analyze()
            pr_evidence = [
                e for e in results[0].evidence
                if "merged" in e.description.lower()
            ]
            assert pr_evidence
            ref = pr_evidence[0].source_ref
            assert ref is not None
            assert ref.startswith("PR #"), (
                f"Expected 'PR #N' format, got '{ref}'"
            )
        finally:
            builder.cleanup()
