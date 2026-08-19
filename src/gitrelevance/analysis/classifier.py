"""Classification decision engine for correlating issue relevance."""

from __future__ import annotations

from gitrelevance.analysis.evidence import WEIGHT_FIX_LATER_REVERTED
from gitrelevance.issues.models import Issue
from gitrelevance.models import Classification, EvidenceItem

# Threshold constants for classification decisions
RESOLVED_THRESHOLD = 3
PROBABLE_THRESHOLD = 2
OBSOLETE_THRESHOLD = -3


def classify(issue: Issue, evidence: tuple[EvidenceItem, ...]) -> Classification:
    """Classify an issue's current relevance based on collected evidence items.

    Decision Order:
    1. Strong evidence >= RESOLVED_THRESHOLD and no unresolved revert evidence -> RESOLVED
    2. Strong evidence >= PROBABLE_THRESHOLD and no unresolved revert evidence -> PROBABLY_RESOLVED
    3. Obsolescence evidence <= OBSOLETE_THRESHOLD (and no strong fix) -> OBSOLETE
    4. Open issue with any evidence present -> STILL_RELEVANT
    5. Fallback -> UNKNOWN (covers no evidence or inconclusive evidence)

    Args:
        issue: The Issue being classified.
        evidence: Tuple of collected EvidenceItem instances.

    Returns:
        Classification decision enum value.
    """
    strong_score = sum(item.weight for item in evidence if item.category == "strong")
    obsolescence_score = sum(item.weight for item in evidence if item.category == "obsolescence")

    has_unresolved_revert = any(
        item.weight == WEIGHT_FIX_LATER_REVERTED or "reverted" in item.description.lower()
        for item in evidence
    )

    # 1. Resolved: Strong evidence threshold met and no fix-revert detected
    if strong_score >= RESOLVED_THRESHOLD and not has_unresolved_revert:
        return Classification.RESOLVED

    # 2. Probably Resolved: Moderate strong evidence threshold met and no fix-revert detected
    if strong_score >= PROBABLE_THRESHOLD and not has_unresolved_revert:
        return Classification.PROBABLY_RESOLVED

    # 3. Obsolete: Obsolescence evidence threshold met (e.g. deleted files without replacement)
    # Note: If a fix commit was reverted, it invalidates strong fix evidence. If the issue is closed
    # and feature code was deleted, it falls into OBSOLETE; otherwise if open, into STILL_RELEVANT.
    if obsolescence_score <= OBSOLETE_THRESHOLD and not (issue.state == "open" and has_unresolved_revert):
        return Classification.OBSOLETE

    # 4. Still Relevant: Open issue with active related code or unresolved evidence
    if issue.state == "open" and len(evidence) > 0:
        return Classification.STILL_RELEVANT

    # 5. Fallback: Closed issue without fix commits or inconclusive evidence
    return Classification.UNKNOWN
