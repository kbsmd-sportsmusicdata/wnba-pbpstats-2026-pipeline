"""End-to-end in-memory pipeline for the fixture-only vertical slice."""

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
    counts = {"players_considered": int(len(funnel)), "players_scored": int((funnel["funnel_status"] == "included").sum())}
    for reason, count in funnel["exclusion_reason"].value_counts().items():
        if reason:
            counts[f"excluded_{reason}"] = int(count)
    return counts


def build_analysis(config: Dict[str, Any]) -> AnalysisResult:
    sources = load_sources(config)
    metrics = build_window_metrics(sources.player_game, config)
    funnel = build_candidate_funnel(sources, metrics, config)
    included = funnel[funnel["funnel_status"] == "included"].copy()

    score_rows = []
    evidence_rows = []
    for _, candidate in included.iterrows():
        role = sources.role_definitions[candidate["role_code"]]
        fulfillment_score, fulfillment_detail = fulfillment(candidate, role)
        opportunity_score, opportunity_detail = opportunity(candidate, config)
        stability_score, stability_detail = stability(candidate, config)
        values = [fulfillment_score, opportunity_score, stability_score]
        status = "fixture_only" if all(pd.notna(value) for value in values) else "unavailable"
        record = candidate.to_dict()
        record.update({
            "role_label": role["label"],
            "fulfillment_score": round(fulfillment_score, 2),
            "opportunity_score": round(opportunity_score, 2),
            "stability_score": round(stability_score, 2),
            "score_status": status,
            "coverage_pct": 100.0 if status == "fixture_only" else 0.0,
            "formula_version": config["formula_version"],
            "analysis_mode": "fixture",
        })
        score_rows.append(record)
        evidence_rows.extend(build_evidence_rows(
            record,
            {
                "fulfillment": fulfillment_detail,
                "opportunity": opportunity_detail,
                "stability": stability_detail,
            },
            config,
        ))

    scores = pd.DataFrame(score_rows)
    if not scores.empty:
        scores = scores.sort_values(["fulfillment_score", "player_name"], ascending=[False, True]).reset_index(drop=True)
    evidence = pd.DataFrame(evidence_rows)
    counts = _funnel_counts(funnel)
    manifest = {
        "season": int(config["season"]),
        "mode": "fixture",
        "live_scoring_status": "blocked",
        "live_scoring_blockers": [
            "reviewed age/experience eligibility table",
            "reviewed player-role assignments",
        ],
        "formula_version": config["formula_version"],
        "players_scored": counts["players_scored"],
        "funnel_counts": counts,
        "source_manifest": sources.source_manifest,
    }
    return AnalysisResult(funnel=funnel, scores=scores, evidence=evidence, manifest=manifest, sources=sources)
