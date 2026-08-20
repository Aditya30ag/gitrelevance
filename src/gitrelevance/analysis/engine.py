"""AnalysisEngine for orchestrating Git and Provider analysis."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator, Literal

from gitrelevance.analysis.confidence import compute_confidence
from gitrelevance.analysis.current_state import analyze_current_state
from gitrelevance.analysis.evidence import collect_evidence
from gitrelevance.analysis.classifier import classify
from gitrelevance.analysis.matcher import MatchSet, build_all_match_sets
from gitrelevance.git.history import build_commit_reference_index
from gitrelevance.git.repository import GitRepository
from gitrelevance.models import AnalysisResult
from gitrelevance.providers.base import Provider

logger = logging.getLogger(__name__)

# Default number of worker threads for parallel per-issue analysis.
# Conservative to avoid overwhelming git subprocess and GitHub API.
DEFAULT_MAX_WORKERS = 8


class AnalysisEngine:
    """Orchestrates end-to-end analysis of issues against Git repository state.

    Attributes:
        repo: Local Git repository wrapper.
        provider: Issue tracker provider instance.
    """

    def __init__(self, repo: GitRepository, provider: Provider) -> None:
        """Initialize the AnalysisEngine.

        Args:
            repo: GitRepository instance.
            provider: Provider instance implementing the Provider protocol.
        """
        self.repo = repo
        self.provider = provider

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_single_issue(
        issue,  # Issue (avoiding import for circular reasons in staticmethod)
        match_set: MatchSet,
        repo: GitRepository,
    ) -> AnalysisResult:
        """Compute the AnalysisResult for a single issue (CPU/git-bound).

        This is the per-issue hot path factored out so it can be called from
        a worker thread.
        """
        facts = analyze_current_state(match_set, repo)
        evidence = collect_evidence(match_set, facts)
        confidence = compute_confidence(evidence)
        classification = classify(issue, evidence)
        return AnalysisResult(
            issue=issue,
            classification=classification,
            confidence=confidence,
            evidence=evidence,
        )

    def _prepare(
        self, state: Literal["open", "closed", "all"]
    ) -> tuple[list, dict[int, MatchSet], float]:
        """Fetch issues & PRs and build match sets (I/O-bound phase).

        Also ensures the commit-reference index is built once up-front so
        every subsequent per-issue lookup is a dict hit.

        Returns:
            (issues_sorted, match_sets, elapsed_seconds)
        """
        t0 = time.perf_counter()

        logger.info("Fetching issues (state=%s)...", state)
        issues = self.provider.get_issues(state=state)
        issues_sorted = sorted(issues, key=lambda i: i.number)
        logger.info("Found %d issues to analyze.", len(issues_sorted))

        logger.info("Fetching pull requests and building correlation match sets...")
        match_sets = build_all_match_sets(issues_sorted, self.repo, self.provider)
        logger.info("Correlation match sets built for %d issues.", len(match_sets))

        # Build the commit-reference index once so per-issue lookups are instant
        logger.info("Building commit-reference index...")
        build_commit_reference_index(self.repo)

        elapsed = time.perf_counter() - t0
        logger.info("Preparation (issues + PRs + match sets) took %.2fs.", elapsed)
        return issues_sorted, match_sets, elapsed

    # ------------------------------------------------------------------
    # Streaming generator (Goal 1 + Goal 2)
    # ------------------------------------------------------------------

    def analyze_streaming(
        self,
        state: Literal["open", "closed", "all"] = "all",
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> Iterator[AnalysisResult]:
        """Yield AnalysisResult objects as each issue finishes processing.

        Issues are analysed concurrently via a thread pool (git subprocess
        calls release the GIL). Results are yielded in completion order
        (not issue-number order) for minimum latency.

        Args:
            state: Issue state filter.
            max_workers: Maximum concurrent worker threads.

        Yields:
            AnalysisResult for each issue, as soon as it is ready.
        """
        issues_sorted, match_sets, _prep_elapsed = self._prepare(state)
        total = len(issues_sorted)

        if total == 0:
            logger.info("No issues to analyze.")
            return

        logger.info(
            "Analyzing %d issues in parallel (max_workers=%d)...",
            total,
            max_workers,
        )
        t_analysis = time.perf_counter()

        def _process(issue):
            return self._analyze_single_issue(issue, match_sets[issue.number], self.repo)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_issue = {
                executor.submit(_process, issue): issue for issue in issues_sorted
            }
            completed = 0
            for future in as_completed(future_to_issue):
                result = future.result()  # propagates exceptions
                completed += 1
                logger.debug(
                    "Completed issue #%d (%d/%d)",
                    result.issue.number,
                    completed,
                    total,
                )
                yield result

        elapsed_analysis = time.perf_counter() - t_analysis
        logger.info(
            "Analysis completed for %d issues in %.2fs.",
            total,
            elapsed_analysis,
        )

    # ------------------------------------------------------------------
    # Legacy batch API (backward-compatible)
    # ------------------------------------------------------------------

    def analyze(self, state: Literal["open", "closed", "all"] = "all") -> list[AnalysisResult]:
        """Analyze repository issues for relevance against local Git history.

        Collects all results from the streaming generator and returns them
        sorted by issue number for backward compatibility.

        Args:
            state: Issue state filter ("open", "closed", or "all").

        Returns:
            List of AnalysisResult objects sorted by issue number.
        """
        results = list(self.analyze_streaming(state=state))
        results.sort(key=lambda r: r.issue.number)
        return results
