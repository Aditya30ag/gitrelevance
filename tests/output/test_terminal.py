"""Unit tests for terminal output rendering."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from rich.console import Console

from gitrelevance.issues.models import Issue
from gitrelevance.models import AnalysisResult, Classification, EvidenceItem
from gitrelevance.output.terminal import TerminalRenderer


def make_sample_issue(number: int = 21, title: str = "Login crashes after token expiration") -> Issue:
    return Issue(
        number=number,
        title=title,
        body="Description",
        state="closed",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        labels=(),
        linked_pr_numbers=(),
    )


def test_terminal_renderer_content() -> None:
    """Terminal renderer outputs all required elements and headers."""
    issue = make_sample_issue()
    evidence = (
        EvidenceItem(description="Fix commit is present in HEAD history", weight=3, category="strong", source_ref="a81f23c"),
        EvidenceItem(description="All related files exist at HEAD", weight=2, category="medium", source_ref=None),
        EvidenceItem(description="No revert of fix commit detected", weight=1, category="medium", source_ref="a81f23c"),
    )
    result = AnalysisResult(
        issue=issue,
        classification=Classification.RESOLVED,
        confidence=0.96,
        evidence=evidence,
    )

    repo_info = {
        "owner": "octocat",
        "repo": "Hello-World",
        "branch": "main",
        "short_sha": "a81f23c",
    }

    buf = io.StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    renderer = TerminalRenderer(console=console)
    renderer.render([result], repo_info)

    output = buf.getvalue()

    # Repository header assertions
    assert "GitRelevance" in output
    assert "Repository: github.com/octocat/Hello-World" in output
    assert "Branch: main" in output
    assert "HEAD: a81f23c" in output
    assert "Analyzing 1 issue..." in output

    # Classification & Issue assertions
    assert "RESOLVED" in output
    assert "#21 Login crashes after token expiration" in output
    assert "Confidence: 96%" in output

    # Evidence item assertions
    assert "Fix commit is present in HEAD history (a81f23c)" in output
    assert "All related files exist at HEAD" in output
    assert "No revert of fix commit detected (a81f23c)" in output

    # Disclaimer assertion
    assert "not a statistical probability" in output


def test_terminal_renderer_grouping_order() -> None:
    """Renderer groups items in the canonical display order."""
    i1 = make_sample_issue(number=1, title="Unknown issue")
    i2 = make_sample_issue(number=2, title="Resolved issue")
    i3 = make_sample_issue(number=3, title="Obsolete issue")

    r1 = AnalysisResult(issue=i1, classification=Classification.UNKNOWN, confidence=0.50, evidence=())
    r2 = AnalysisResult(issue=i2, classification=Classification.RESOLVED, confidence=0.90, evidence=())
    r3 = AnalysisResult(issue=i3, classification=Classification.OBSOLETE, confidence=0.20, evidence=())

    buf = io.StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    renderer = TerminalRenderer(console=console)
    # Pass out of order
    renderer.render([r1, r3, r2], {"owner": "o", "repo": "r", "branch": "m", "short_sha": "1234567"})

    output = buf.getvalue()
    pos_resolved = output.find("RESOLVED")
    pos_obsolete = output.find("OBSOLETE")
    pos_unknown = output.find("UNKNOWN")

    assert pos_resolved != -1 and pos_obsolete != -1 and pos_unknown != -1
    assert pos_resolved < pos_obsolete < pos_unknown
