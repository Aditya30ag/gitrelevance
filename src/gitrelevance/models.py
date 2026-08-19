"""Shared core data models for GitRelevance analysis and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from gitrelevance.issues.models import Issue


class Classification(str, Enum):
    """Classification of issue relevance relative to current Git repository state."""

    RESOLVED = "RESOLVED"
    PROBABLY_RESOLVED = "PROBABLY_RESOLVED"
    STILL_RELEVANT = "STILL_RELEVANT"
    OBSOLETE = "OBSOLETE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """Individual piece of evidence supporting or opposing issue relevance.

    Attributes:
        description: Human-readable explanation of the evidence.
        weight: Signed integer weight indicating evidence strength (positive = resolved, negative = obsolete/unresolved).
        category: Evidence category ("strong", "medium", or "obsolescence").
        source_ref: Optional reference string (e.g. commit SHA or PR number).
    """

    description: str
    weight: int
    category: Literal["strong", "medium", "obsolescence"]
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Complete analysis result for a single issue.

    Attributes:
        issue: The issue being analyzed.
        classification: Final classification decision.
        confidence: Evidence-strength score clamped to [0.05, 0.98].
            This is a relative evidence-strength heuristic, NOT a calibrated
            statistical probability. A higher value means more and stronger
            evidence supports the classification, not that the classification
            is more likely to be correct in a Bayesian sense.
        evidence: Tuple of collected evidence items explaining the decision.
            Each item carries a human-readable description, a signed weight,
            a category, and an optional source_ref (short commit SHA or
            "PR #N") so the result is self-contained for display.
    """

    issue: Issue
    classification: Classification
    confidence: float
    evidence: tuple[EvidenceItem, ...]
