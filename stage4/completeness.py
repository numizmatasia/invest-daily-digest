from __future__ import annotations

from typing import Iterable

from stage4.models import CoverageAssessment, CoverageStatus


def assess_coverage(*, mandatory_sources: Iterable[str], source_results: Iterable[dict]) -> CoverageAssessment:
    mandatory = {str(item).strip() for item in mandatory_sources if str(item).strip()}
    if not mandatory:
        return CoverageAssessment(
            status=CoverageStatus.INSUFFICIENT,
            runtime_status="RUNTIME_BLOCKED",
            warnings=("MANDATORY_SOURCE_SET_UNAPPROVED",),
        )
    results = {str(item.get("name", "")).strip(): bool(item.get("ok")) for item in source_results}
    missing_or_failed = sorted(name for name in mandatory if not results.get(name, False))
    if missing_or_failed:
        return CoverageAssessment(
            status=CoverageStatus.INSUFFICIENT,
            runtime_status="RUNTIME_BLOCKED",
            warnings=tuple(f"MANDATORY_SOURCE_UNAVAILABLE:{name}" for name in missing_or_failed),
        )
    optional_failed = sorted(name for name, ok in results.items() if name not in mandatory and not ok)
    if optional_failed:
        return CoverageAssessment(
            status=CoverageStatus.DEGRADED,
            runtime_status="RUNTIME_DEGRADED",
            warnings=tuple(f"OPTIONAL_SOURCE_FAILED:{name}" for name in optional_failed),
        )
    return CoverageAssessment(status=CoverageStatus.FULL, runtime_status="RUNTIME_OK", warnings=())
