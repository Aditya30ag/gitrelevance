"""Unit tests for JSON output serialization."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from gitrelevance.issues.models import Issue
from gitrelevance.models import AnalysisResult, Classification, EvidenceItem
from gitrelevance.output.json import to_json


def test_to_json_roundtrip_and_structure() -> None:
    """JSON output serializes correctly and roundtrips with expected keys."""
    issue = Issue(
        number=42,
        title="Fix authentication bug",
        body="Bug description",
        state="closed",
        created_at=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        closed_at=datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc),
        labels=("bug", "auth"),
        linked_pr_numbers=(99,),
    )
    evidence = (
        EvidenceItem(description="Fix commit is present in HEAD history", weight=3, category="strong", source_ref="deadbeef"),
        EvidenceItem(description="All related files exist at HEAD", weight=2, category="medium", source_ref=None),
    )
    result = AnalysisResult(
        issue=issue,
        classification=Classification.RESOLVED,
        confidence=0.85,
        evidence=evidence,
    )

    repo_info = {
        "branch": "main",
        "owner": "testorg",
        "remote_url": "https://github.com/testorg/testrepo.git",
        "repo": "testrepo",
        "short_sha": "deadbee",
    }

    json_str = to_json([result], repo_info)
    data = json.loads(json_str)

    # Top-level keys
    assert "repository" in data
    assert "results" in data
    assert "total_issues" in data
    assert "disclaimer" in data

    assert data["total_issues"] == 1
    assert data["repository"]["owner"] == "testorg"
    assert data["repository"]["repo"] == "testrepo"
    assert data["repository"]["branch"] == "main"

    # Result keys
    res_data = data["results"][0]
    assert res_data["classification"] == "RESOLVED"
    assert res_data["confidence"] == 0.85
    assert res_data["confidence_percentage"] == 85

    # Issue details
    assert res_data["issue"]["number"] == 42
    assert res_data["issue"]["title"] == "Fix authentication bug"
    assert res_data["issue"]["state"] == "closed"
    assert res_data["issue"]["labels"] == ["bug", "auth"]
    assert res_data["issue"]["linked_pr_numbers"] == [99]
    assert res_data["issue"]["created_at"] == "2024-01-15T10:30:00+00:00"
    assert res_data["issue"]["closed_at"] == "2024-01-16T12:00:00+00:00"

    # Evidence details
    assert len(res_data["evidence"]) == 2
    assert res_data["evidence"][0]["category"] == "strong"
    assert res_data["evidence"][0]["weight"] == 3
    assert res_data["evidence"][0]["source_ref"] == "deadbeef"
    assert res_data["evidence"][1]["source_ref"] is None
