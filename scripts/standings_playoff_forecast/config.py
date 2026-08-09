"""Load validated forecast configuration from repository-relative files."""

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .contracts import ForecastModelConfig, SeasonConfig


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = REPOSITORY_ROOT / "analysis" / "standings_playoff_forecast" / "config"
MANDATORY_SOURCE_FILES = ("schedule", "team_box", "standings", "pbp_team_features")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def load_season_config(season: int) -> SeasonConfig:
    default_config = _load_json(CONFIG_ROOT / "seasons" / "default.json")
    season_config = _load_json(CONFIG_ROOT / "seasons" / f"{season}.json")
    config = {**default_config, **season_config}
    source_files = config["source_files"]

    if config["team_count"] <= config["playoff_qualifiers"]:
        raise ValueError("team_count must exceed playoff_qualifiers")
    if config["regular_season_games_per_team"] <= 0:
        raise ValueError("regular_season_games_per_team must be positive")
    if not config["tiebreaks"]:
        raise ValueError("tiebreaks must not be empty")
    if any(not source_files.get(name) for name in MANDATORY_SOURCE_FILES):
        raise ValueError("all mandatory source filenames must be configured")

    historical_context = config["historical_context"]
    return SeasonConfig(
        season=config["season"],
        league=config["league"],
        season_type=config["season_type"],
        simulation_count=config["simulation_count"],
        recent_window_games=config["recent_window_games"],
        historical_context_enabled=historical_context["enabled"],
        historical_context_min_prior_seasons=historical_context["min_prior_seasons"],
        team_count=config["team_count"],
        regular_season_games_per_team=config["regular_season_games_per_team"],
        playoff_qualifiers=config["playoff_qualifiers"],
        seeding_scope=config["seeding_scope"],
        tiebreaks=tuple(config["tiebreaks"]),
        multi_team_restart_after_elimination=config["multi_team_restart_after_elimination"],
        sportsdataverse_data_root=config["sportsdataverse_data_root"],
        pbpstats_data_root=config["pbpstats_data_root"],
        source_files=MappingProxyType(dict(source_files)),
        output_root=config["output_root"],
        normalized_team_game_root=config["normalized_team_game_root"],
    )


def load_model_config() -> ForecastModelConfig:
    config = _load_json(CONFIG_ROOT / "forecast_model.json")
    return ForecastModelConfig(
        model_version=config["model_version"],
        season_net_rating_weight=config["predictive_rating"]["season_net_rating_weight"],
        recent_net_rating_weight=config["predictive_rating"]["recent_net_rating_weight"],
        home_court_points=config["context_adjustments"]["home_court_points"],
        rest_day_points=config["context_adjustments"]["rest_day_points"],
        max_rest_day_adjustment=config["context_adjustments"]["max_rest_day_adjustment"],
        back_to_back_penalty_points=config["context_adjustments"]["back_to_back_penalty_points"],
        minimum_sigma=config["margin_model"]["minimum_sigma"],
        maximum_sigma=config["margin_model"]["maximum_sigma"],
        explanatory_strength=MappingProxyType(dict(config["explanatory_strength"])),
        pbpstats_enrichment_enabled=config["pbpstats_enrichment"]["enabled"],
        pbpstats_enrichment_required=config["pbpstats_enrichment"]["required"],
    )
