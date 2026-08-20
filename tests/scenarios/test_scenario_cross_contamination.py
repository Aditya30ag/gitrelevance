"""Scenario: Cross-contamination prevention — unrelated issues must not share evidence.

Regression tests for the PR-number false-positive fix in git.history.

Two scenarios tested:
1. A commit that mentions only PR numbers (not issue numbers) must NOT
   contribute evidence to any issue.
2. A commit that legitimately fixes two issues via closing keywords
   MUST contribute its evidence to both issues.
"""

from __future__ import annotations

from gitrelevance.git.repository import GitRepository
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import make_issue


class TestCrossContamination:
    """Ensure unrelated issues do not share evidence via PR-number false positives."""

    def test_pr_number_commit_does_not_contaminate_issues(self) -> None:
        """A commit whose message references only PR numbers must not
        produce referencing_commits for any issue.

        Setup:
        - Repo with commits whose messages reference PR numbers only
        - Two unrelated open issues (#10 docs, #20 security) with no other links

        Expected:
        - Neither issue should have referencing_commits from those commits
        """
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme", "backend/app.py": "app"})
            .commit(
                "Merge pull request #50 and PR #34",
                files={},
            )
        )
        import git as g
        path = builder.build()
        try:
            repo_git = g.Repo(path)
            repo_git.index.remove(["backend/app.py"], working_tree=True)
            repo_git.index.commit("Cleanup: remove deprecated backend")

            repo = GitRepository(path)
            from gitrelevance.git.history import commits_referencing

            ref_10 = commits_referencing(repo, 10)
            ref_20 = commits_referencing(repo, 20)
            ref_50 = commits_referencing(repo, 50)
            ref_34 = commits_referencing(repo, 34)

            assert ref_10 == [], f"Issue #10 should have no refs, got: {[c.message for c in ref_10]}"
            assert ref_20 == [], f"Issue #20 should have no refs, got: {[c.message for c in ref_20]}"
            assert ref_50 == [], f"PR #50 should not be matched as issue, got: {[c.message for c in ref_50]}"
            assert ref_34 == [], f"PR #34 should not be matched as issue, got: {[c.message for c in ref_34]}"
        finally:
            builder.cleanup()

    def test_legitimate_multi_fix_commit_shared_evidence(self) -> None:
        """A commit that genuinely fixes two issues via closing keywords
        MUST attribute its file changes to both issues.

        Setup:
        - Repo with a commit: 'Fix #12 and #34: combined auth fix'
        - Both issue numbers should be in the commit reference index

        Expected:
        - Both issues should have referencing commits containing the fix commit
        - The same commit should be the one referencing both
        """
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit(
                "Fix #12 and #34: combined auth fix",
                files={"auth.py": "auth code", "validation.py": "validation code"},
            )
        )
        path = builder.build()
        try:
            repo = GitRepository(path)

            from gitrelevance.git.history import commits_referencing, build_commit_reference_index
            index = build_commit_reference_index(repo)
            assert 12 in index, "Issue #12 should be found in commit reference index"
            assert 34 in index, "Issue #34 should be found in commit reference index"

            refs_12 = commits_referencing(repo, 12)
            refs_34 = commits_referencing(repo, 34)
            assert len(refs_12) >= 1
            assert len(refs_34) >= 1

            # The same commit should reference both issues
            assert refs_12[0].sha == refs_34[0].sha, (
                "Both issues should be referenced by the same commit"
            )
        finally:
            builder.cleanup()

    def test_pr_numbers_in_merge_commit_not_attributed(self) -> None:
        """Regression: 'Merge pull request #50 from org/feature' must not
        create a referencing commit for issue #50.

        Setup:
        - Repo with a commit whose message is only a merge-PR header
        - Issue #50 exists

        Expected:
        - commits_referencing(repo, 50) should be empty
        """
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit(
                "Merge pull request #50 from org/feature",
                files={"feature.py": "code"},
            )
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            from gitrelevance.git.history import commits_referencing
            refs = commits_referencing(repo, 50)
            assert refs == [], (
                f"PR number #50 should not be treated as issue reference, "
                f"but got: {[c.message for c in refs]}"
            )
        finally:
            builder.cleanup()

    def test_squash_merge_pr_title_not_matched(self) -> None:
        """GitHub squash-merge titles like 'Feature (#42)' must not match
        #42 as an issue reference (parentheses block the word boundary)."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit(
                "Feature: Add auth (#42)",
                files={"auth.py": "auth"},
            )
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            from gitrelevance.git.history import commits_referencing
            refs = commits_referencing(repo, 42)
            assert refs == [], (
                f"PR title (#42) should not match as issue reference, "
                f"but got: {[c.message for c in refs]}"
            )
        finally:
            builder.cleanup()
