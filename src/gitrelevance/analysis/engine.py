"""AnalysisEngine for orchestrating Git and Provider analysis."""

from __future__ import annotations

from typing import Literal

from gitrelevance.analysis.confidence import compute_confidence
from gitrelevance.analysis.current_state import analyze_current_state
from gitrelevance.analysis.evidence import collect_evidence
from gitrelevance.analysis.classifier import classify
from gitrelevance.analysis.matcher import build_all_match_sets
from gitrelevance.git.repository import GitRepository
from gitrelevance.models import AnalysisResult
from gitrelevance.providers.base import Provider


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

    def analyze(self, state: Literal["open", "closed", "all"] = "all") -> list[AnalysisResult]:
        """Analyze repository issues for relevance against local Git history.

        Args:
            state: Issue state filter ("open", "closed", or "all").

        Returns:
            List of AnalysisResult objects sorted by issue number.
        """
        issues = self.provider.get_issues(state=state)
        # Ensure stable ordering by issue number
        issues_sorted = sorted(issues, key=lambda i: i.number)

        # Build match sets in a single pass (fetching PRs once)
        match_sets = build_all_match_sets(issues_sorted, self.repo, self.provider)

        results: list[AnalysisResult] = []
        for issue in issues_sorted:
            match_set = match_sets[issue.number]
            facts = analyze_current_state(match_set, self.repo)
            evidence = collect_evidence(match_set, facts)
            confidence = compute_confidence(evidence)
            classification = classify(issue, evidence)

            results.append(
                AnalysisResult(
                    issue=issue,
                    classification=classification,
                    confidence=confidence,
                    evidence=evidence,
                )
            )

        return results
