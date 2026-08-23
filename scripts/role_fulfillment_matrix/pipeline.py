"""End-to-end in-memory pipeline for fixture and approved live dry runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd

from .data_sources import LoadedSources, load_sources
from .evidence import build_evidence_rows
from .funnel import build_candidate_funnel
from .metrics import build_window_metrics
from .scoring import fulfillment, opportunity, stability


@dataclass
class AnalysisResult:
    funnel: pd.DataFrame
    scores: pd.DataFrame
    evidence: pd.DataFrame
    manifest: Dict[str, Any]
    sources: LoadedSources


def _funnel_counts(funnel: pd.DataFrame) -> Dict[str, int]:
    counts = {
        "players_considered": int(len(funnel)),
        "candidates_included": int((funnel["funnel_status"] == "included").sum()),
    }
    for reason, count in funnel["exclusion_reason"].value_counts().items():
        if reason:
            counts[f"excluded_{reason}"] = int(count)
    return counts


def build_analysis(config: Dict[str, Any]) -> AnalysisResult:
    sources = load_sources(config)
    effective_config = sources.effective_config
    mode = effective_config["mode"]
    scored_status = "fixture_only" if mode == "fixture" else "dry_run_scored"
    metrics = build_window_metrics(sources.player_game, effective_config)
    funnel = build_candidate_funnel(sources, metrics, effective_config)
    included = funnel[funnel["funnel_status"] == "included"].copy()

    score_rows = []
    evidence_rows = []
    minimum_assignment_confidence = float(
        effective_config.get("minimums", {}).get("assignment_confidence_score", 0.0)
    )
    for _, candidate in included.iterrows():
        role = sources.role_definitions[candidate["role_code"]]
        if bool(candidate.get("inactive_rostered")):
            fulfillment_score = opportunity_score = stability_score = float("nan")
            fulfillment_detail = opportunity_detail = stability_detail = []
            status = "inactive_suppressed"
        elif not bool(candidate.get("score_eligible")):
            fulfillment_score = opportunity_score = stability_score = float("nan")
            fulfillment_detail = opportunity_detail = stability_detail = []
            status = "season_context_only"
        elif float(candidate.get("assignment_confidence", 0.0)) < minimum_assignment_confidence:
            fulfillment_score = opportunity_score = stability_score = float("nan")
            fulfillment_detail = opportunity_detail = stability_detail = []
            status = "assignment_confidence_insufficient"
        else:
            fulfillment_score, fulfillment_detail = fulfillment(candidate, role)
            opportunity_score, opportunity_detail = opportunity(candidate, effective_config)
            stability_score, stability_detail = stability(candidate, effective_config)
            values = [fulfillment_score, opportunity_score, stability_score]
            if all(pd.notna(value) for value in values):
                status = scored_status
            elif pd.isna(fulfillment_score) and all(
                pd.notna(value) for value in (opportunity_score, stability_score)
            ):
                status = "insufficient_role_evidence"
            else:
                status = "unavailable"
        score_values = [fulfillment_score, opportunity_score, stability_score]
        record = candidate.to_dict()
        record.update({
            "role_label": role["label"],
            "fulfillment_score": round(fulfillment_score, 2),
            "opportunity_score": round(opportunity_score, 2),
            "stability_score": round(stability_score, 2),
            "score_status": status,
            "coverage_pct": round(
                100.0 * sum(pd.notna(value) for value in score_values) / len(score_values),
                2,
            ),
            "formula_version": effective_config["formula_version"],
            "analysis_mode": mode,
        })
        score_rows.append(record)
        if status in {scored_status, "insufficient_role_evidence", "unavailable"}:
            evidence_rows.extend(build_evidence_rows(
                record,
                {
                    "fulfillment": fulfillment_detail,
                    "opportunity": opportunity_detail,
                    "stability": stability_detail,
                },
                effective_config,
            ))

    scores = pd.DataFrame(score_rows)
    if not scores.empty:
        scores = scores.sort_values(["fulfillment_score", "player_name"], ascending=[False, True]).reset_index(drop=True)
    evidence = pd.DataFrame(evidence_rows)
    counts = _funnel_counts(funnel)
    players_scored = int((scores.get("score_status") == scored_status).sum()) if not scores.empty else 0
    counts["players_scored"] = players_scored
    dry_run_gate_blockers = []
    missing_eligibility = counts.get("excluded_eligibility_not_reviewed", 0)
    missing_roles = counts.get("excluded_role_assignment_not_reviewed", 0)
    assignment_mismatches = counts.get("excluded_role_assignment_team_mismatch", 0)
    if mode == "live_dry_run" and missing_eligibility:
        dry_run_gate_blockers.append(
            f"current contender roster players without reviewed eligibility: {missing_eligibility}"
        )
    if mode == "live_dry_run" and missing_roles:
        dry_run_gate_blockers.append(
            f"current contender candidates without reviewed role assignments: {missing_roles}"
        )
    if mode == "live_dry_run" and assignment_mismatches:
        dry_run_gate_blockers.append(
            f"current contender candidates with stale team-role assignments: {assignment_mismatches}"
        )
    manifest = {
        "season": int(effective_config["season"]),
        "mode": mode,
        "live_scoring_status": "blocked" if mode == "fixture" else "dry_run_only",
        "live_scoring_blockers": (
            ["deliberate live adapter wiring and end-to-end dry run"]
            if mode == "fixture"
            else ["final reviewer approval and explicit live-output enablement"]
        ),
        "live_output_enabled": bool(effective_config.get("live_output_enabled", False)),
        "formula_version": effective_config["formula_version"],
        "analysis_cutoff_date": effective_config.get("analysis_cutoff_date"),
        "windows": effective_config.get("windows"),
        "adapter_audit": sources.adapter_audit,
        "dry_run_gate_status": (
            "blocked" if dry_run_gate_blockers else "review_ready"
        ) if mode == "live_dry_run" else "not_applicable",
        "dry_run_gate_blockers": dry_run_gate_blockers,
        "players_scored": players_scored,
        "funnel_counts": counts,
        "source_manifest": sources.source_manifest,
    }
    return AnalysisResult(funnel=funnel, scores=scores, evidence=evidence, manifest=manifest, sources=sources)
