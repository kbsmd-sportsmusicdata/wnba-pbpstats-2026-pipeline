"""Processed exports and dashboard bundle for the isolated experiment."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

from .data_sources import repo_root, resolve_path
from .pipeline import build_analysis
from .render_dashboard import render_dashboard


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[Dict[str, Any]]:
    return _clean(frame.to_dict("records"))


def _json_text(value: Any) -> str:
    return json.dumps(_clean(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def _atomic_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_json_text(value), encoding="utf-8")
    temporary.replace(path)


def build_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    result = build_analysis(config)
    output_root = resolve_path(config["output_root"])
    processed = output_root / "data" / "processed"
    bundle = output_root / "deliverables" / "role_fulfillment_matrix"

    funnel_path = processed / "candidate_funnel_2026.csv"
    scores_path = processed / "role_fulfillment_matrix_2026.csv"
    evidence_path = processed / "role_fulfillment_evidence_2026.json"
    manifest_path = processed / "run_manifest_2026.json"

    _atomic_csv(result.funnel, funnel_path)
    _atomic_csv(result.scores, scores_path)
    _atomic_json(_records(result.evidence), evidence_path)

    config_for_hash = {key: value for key, value in config.items() if key != "_config_path"}
    config_hash = hashlib.sha256(_json_text(config_for_hash).encode("utf-8")).hexdigest()
    manifest = dict(result.manifest)
    manifest.update({
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "config_path": config.get("_config_path"),
        "config_hash": config_hash,
        "output_rows": {
            funnel_path.name: int(len(result.funnel)),
            scores_path.name: int(len(result.scores)),
            evidence_path.name: int(len(result.evidence)),
        },
    })
    _atomic_json(manifest, manifest_path)

    payload = {
        "meta": manifest,
        "funnel": _records(result.funnel[[
            "player_id", "player_name", "team_abbreviation", "funnel_status", "exclusion_reason"
        ]]),
        "candidates": _records(result.scores),
        "evidence": _records(result.evidence),
    }
    template_root = repo_root() / "analysis" / "role_fulfillment_matrix" / "templates"
    render_dashboard(payload, template_root, bundle)
    return manifest
