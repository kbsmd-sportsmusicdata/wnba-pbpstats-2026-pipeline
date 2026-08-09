"""Typed configuration contracts for the standings forecast."""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SeasonConfig:
    season: int
    league: str
    season_type: str
    simulation_count: int
    recent_window_games: int
    historical_context_enabled: bool
    historical_context_min_prior_seasons: int
    team_count: int
    regular_season_games_per_team: int
    playoff_qualifiers: int
    seeding_scope: str
    tiebreaks: tuple[str, ...]
    multi_team_restart_after_elimination: bool
    sportsdataverse_data_root: str
    pbpstats_data_root: str
    source_files: Mapping[str, str]
    output_root: str
    normalized_team_game_root: str


@dataclass(frozen=True)
class ForecastModelConfig:
    model_version: str
    season_net_rating_weight: float
    recent_net_rating_weight: float
    home_court_points: float
    rest_day_points: float
    max_rest_day_adjustment: int
    back_to_back_penalty_points: float
    minimum_sigma: float
    maximum_sigma: float
    explanatory_strength: Mapping[str, float]
    pbpstats_enrichment_enabled: bool
    pbpstats_enrichment_required: bool
