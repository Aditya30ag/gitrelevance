"""Confidence score calculation for evidence sets.

Calculates an evidence-strength heuristic score between 0.05 and 0.98.
Note: This score is a relative evidence-strength heuristic, NOT a calibrated
statistical probability.
"""

from __future__ import annotations

from gitrelevance.models import EvidenceItem

# Named constants for normalization and clamping
MAX_ABS_WEIGHT = 20.0
MIN_CONFIDENCE = 0.05
MAX_CONFIDENCE = 0.98
DEFAULT_CONFIDENCE = 0.50


def compute_confidence(evidence: tuple[EvidenceItem, ...]) -> float:
    """Compute an evidence-strength score normalized and clamped to [0.05, 0.98].

    The formula maps evidence weight sums around a baseline of 0.50:
        confidence = 0.5 + sum(weights) / (2 * MAX_ABS_WEIGHT)

    If no evidence items exist, returns the default neutral score (0.50).

    Args:
        evidence: Tuple of EvidenceItem instances.

    Returns:
        Float confidence score clamped to [MIN_CONFIDENCE, MAX_CONFIDENCE].
    """
    if not evidence:
        return DEFAULT_CONFIDENCE

    total_weight = sum(item.weight for item in evidence)
    raw_score = 0.5 + (total_weight / (2.0 * MAX_ABS_WEIGHT))

    # Clamp to [MIN_CONFIDENCE, MAX_CONFIDENCE]
    clamped_score = max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, raw_score))
    return round(clamped_score, 4)
