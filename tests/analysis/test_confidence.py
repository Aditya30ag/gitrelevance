"""Unit tests for confidence calculation and normalization."""

from __future__ import annotations

import pytest

from gitrelevance.analysis.confidence import (
    DEFAULT_CONFIDENCE,
    MAX_CONFIDENCE,
    MIN_CONFIDENCE,
    compute_confidence,
)
from gitrelevance.models import EvidenceItem


class TestConfidenceCalculation:

    def test_empty_evidence_returns_default(self) -> None:
        """Empty evidence returns default confidence (0.50)."""
        score = compute_confidence(())
        assert score == DEFAULT_CONFIDENCE

    def test_known_evidence_totals(self) -> None:
        """Test formula mapping: 0.5 + sum(weights) / (2 * 20.0)."""
        # Sum = +10 -> 0.5 + 10 / 40 = 0.75
        e1 = EvidenceItem("Item 1", weight=6, category="strong")
        e2 = EvidenceItem("Item 2", weight=4, category="medium")
        score = compute_confidence((e1, e2))
        assert score == 0.75

    def test_extreme_positive_clamping(self) -> None:
        """Extreme positive weight sum clamps to MAX_CONFIDENCE (0.98)."""
        items = tuple(EvidenceItem("Strong", weight=10, category="strong") for _ in range(5))
        # Total weight = +50 -> raw formula 0.5 + 50/40 = 1.75 -> clamped to 0.98
        score = compute_confidence(items)
        assert score == MAX_CONFIDENCE

    def test_extreme_negative_clamping(self) -> None:
        """Extreme negative weight sum clamps to MIN_CONFIDENCE (0.05)."""
        items = tuple(EvidenceItem("Obsolescence", weight=-10, category="obsolescence") for _ in range(5))
        # Total weight = -50 -> raw formula 0.5 - 50/40 = -0.75 -> clamped to 0.05
        score = compute_confidence(items)
        assert score == MIN_CONFIDENCE
