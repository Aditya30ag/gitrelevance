"""Unit tests for classification decision engine."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from gitrelevance.analysis.classifier import classify
from gitrelevance.issues.models import Issue
from gitrelevance.models import Classification, EvidenceItem


def make_issue(state: str = "open") -> Issue:
    return Issue(
        number=1,
        title="Test Issue",
        body="Body",
        state="closed" if state == "closed" else "open",
        created_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc) if state == "closed" else None,
        labels=(),
        linked_pr_numbers=(),
    )


class TestClassifier:

    def test_resolved_classification(self) -> None:
        """Strong evidence sum >= 3 and no revert -> RESOLVED."""
        issue = make_issue(state="closed")
        evidence = (
            EvidenceItem("Fix commit in HEAD", weight=3, category="strong"),
        )
        assert classify(issue, evidence) == Classification.RESOLVED

    def test_probably_resolved_classification(self) -> None:
        """Strong evidence sum == 2 and no revert -> PROBABLY_RESOLVED."""
        issue = make_issue(state="closed")
        evidence = (
            EvidenceItem("PR merged", weight=2, category="strong"),
        )
        assert classify(issue, evidence) == Classification.PROBABLY_RESOLVED

    def test_obsolete_classification(self) -> None:
        """Obsolescence evidence <= -3 -> OBSOLETE."""
        issue = make_issue(state="closed")
        evidence = (
            EvidenceItem("Files deleted", weight=-3, category="obsolescence"),
        )
        assert classify(issue, evidence) == Classification.OBSOLETE

    def test_still_relevant_classification(self) -> None:
        """Open issue with active code evidence -> STILL_RELEVANT."""
        issue = make_issue(state="open")
        evidence = (
            EvidenceItem("Files exist", weight=2, category="medium"),
        )
        assert classify(issue, evidence) == Classification.STILL_RELEVANT

    def test_unknown_classification_no_evidence(self) -> None:
        """Closed issue with no evidence -> UNKNOWN."""
        issue = make_issue(state="closed")
        assert classify(issue, ()) == Classification.UNKNOWN

    def test_unknown_classification_conflicting_evidence(self) -> None:
        """Closed issue with inconclusive/conflicting evidence -> UNKNOWN."""
        issue = make_issue(state="closed")
        evidence = (
            EvidenceItem("Files exist", weight=2, category="medium"),
        )
        assert classify(issue, evidence) == Classification.UNKNOWN
