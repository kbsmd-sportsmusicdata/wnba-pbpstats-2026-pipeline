"""Functional Depth Score: depth as a playoff variable, not a roster adjective."""

from .metrics import (
    SKILLS,
    aggregate_player_team,
    gini,
    league_skill_thresholds,
    performance_floor,
    production_distribution,
    replacement_resilience,
    role_redundancy,
    rotation_trust,
)
from .score import build_functional_depth, build_strip, components_long

__all__ = [
    "SKILLS",
    "aggregate_player_team",
    "gini",
    "league_skill_thresholds",
    "performance_floor",
    "production_distribution",
    "replacement_resilience",
    "role_redundancy",
    "rotation_trust",
    "build_functional_depth",
    "build_strip",
    "components_long",
]
