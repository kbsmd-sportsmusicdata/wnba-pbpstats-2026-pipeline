"""Independent Fulfillment, Opportunity, and Stability scores."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

import numpy as np
import pandas as pd


def normalize(value: float, floor: float, target: float, direction: str = "higher") -> float:
    if value is None or not np.isfinite(value):
        return float("nan")
    if direction == "higher":
        raw = (value - floor) / (target - floor)
    elif direction == "lower":
        raw = (floor - value) / (floor - target)
    else:
        raise ValueError(f"unsupported direction: {direction}")
    return float(np.clip(raw * 100.0, 0.0, 100.0))


def weighted_score(parts: Iterable[Tuple[float, float]]) -> float:
    values = list(parts)
    if not values or any(not np.isfinite(value) for value, _ in values):
        return float("nan")
    total_weight = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / total_weight


def fulfillment(row: pd.Series, role: Dict[str, Any]) -> Tuple[float, list[Dict[str, Any]]]:
    parts = []
    detail = []
    for metric in role["metrics"]:
        value = row.get(f"recent_{metric['code']}")
        component = normalize(value, metric["floor"], metric["target"], metric["direction"])
        parts.append((component, float(metric["weight"])))
        detail.append({**metric, "value": value, "component_score": component})
    return weighted_score(parts), detail


def opportunity(row: pd.Series, config: Dict[str, Any]) -> Tuple[float, list[Dict[str, Any]]]:
    delta = row.get("recent_possession_share") - row.get("baseline_possession_share")
    values = {
        "minutes_per_game": row.get("recent_minutes_per_game"),
        "possession_share": row.get("recent_possession_share"),
        "possession_share_delta": delta,
    }
    parts = []
    detail = []
    for code, rule in config["opportunity"].items():
        component = normalize(values[code], rule["floor"], rule["target"], "higher")
        parts.append((component, float(rule["weight"])))
        detail.append({"code": code, "value": values[code], "component_score": component, **rule})
    return weighted_score(parts), detail


def stability(row: pd.Series, config: Dict[str, Any]) -> Tuple[float, list[Dict[str, Any]]]:
    rules = config["stability"]
    weights = rules["weights"]
    raw_values = {
        "games": float(row.get("recent_games", np.nan)),
        "possessions": float(row.get("recent_off_poss", np.nan)),
        "consistency": float(row.get("recent_possession_share_sd", np.nan)),
        "assignment_confidence": float(row.get("assignment_confidence", np.nan)),
    }
    components = {
        "games": min(raw_values["games"] / float(rules["recent_games_target"]), 1.0) * 100,
        "possessions": min(raw_values["possessions"] / float(rules["recent_off_poss_target"]), 1.0) * 100,
        "consistency": normalize(
            raw_values["consistency"],
            float(rules["possession_share_sd_ceiling"]),
            0.0,
            "lower",
        ),
        "assignment_confidence": raw_values["assignment_confidence"] * 100,
    }
    parts = [(value, float(weights[code])) for code, value in components.items()]
    detail = [
        {
            "code": code,
            "value": raw_values[code],
            "component_score": component,
            "weight": weights[code],
        }
        for code, component in components.items()
    ]
    return weighted_score(parts), detail
