"""JSON serialization for analysis results."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from gitrelevance.models import AnalysisResult, EvidenceItem


def _format_datetime(dt: datetime | None) -> str | None:
    """Format datetime to ISO 8601 string if present."""
    return dt.isoformat() if dt is not None else None


def _evidence_item_to_dict(item: EvidenceItem) -> dict[str, Any]:
    """Convert an EvidenceItem to a JSON-serializable dictionary."""
    return {
        "category": item.category,
        "description": item.description,
        "source_ref": item.source_ref,
        "weight": item.weight,
    }


def _analysis_result_to_dict(result: AnalysisResult) -> dict[str, Any]:
    """Convert an AnalysisResult to a JSON-serializable dictionary."""
    return {
        "classification": result.classification.value,
        "confidence": result.confidence,
        "confidence_percentage": int(round(result.confidence * 100)),
        "evidence": [_evidence_item_to_dict(e) for e in result.evidence],
        "issue": {
            "closed_at": _format_datetime(result.issue.closed_at),
            "created_at": _format_datetime(result.issue.created_at),
            "labels": list(result.issue.labels),
            "linked_pr_numbers": list(result.issue.linked_pr_numbers),
            "number": result.issue.number,
            "state": result.issue.state,
            "title": result.issue.title,
        },
    }


def to_json(
    results: list[AnalysisResult],
    repo_info: Mapping[str, Any] | Any,
) -> str:
    """Serialize the full analysis results and repo info to a JSON string.

    Args:
        results: List of AnalysisResult objects.
        repo_info: Mapping or object containing repository metadata.

    Returns:
        JSON string with stable key ordering and 2-space indentation.
    """
    if isinstance(repo_info, Mapping):
        repo_dict = {
            "branch": repo_info.get("branch"),
            "owner": repo_info.get("owner"),
            "remote_url": repo_info.get("remote_url"),
            "repo": repo_info.get("repo", repo_info.get("name")),
            "short_sha": str(repo_info.get("short_sha", repo_info.get("head_sha", "")))[:7],
        }
    else:
        repo_dict = {
            "branch": getattr(repo_info, "branch", None),
            "owner": getattr(repo_info, "owner", None),
            "remote_url": getattr(repo_info, "remote_url", None),
            "repo": getattr(repo_info, "repo", getattr(repo_info, "name", None)),
            "short_sha": str(getattr(repo_info, "short_sha", getattr(repo_info, "head_sha", "")))[:7],
        }

    payload = {
        "disclaimer": "Confidence is a heuristic evidence-strength score, not a statistical probability.",
        "repository": repo_dict,
        "results": [_analysis_result_to_dict(r) for r in results],
        "total_issues": len(results),
    }

    return json.dumps(payload, indent=2, sort_keys=True)
