"""Render a validated forecast bundle as a deterministic broadcaster brief."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .broadcast_insights import INSIGHT_COLUMNS
from .historical_context import HISTORICAL_CONTEXT_COLUMNS
from .leverage import LEVERAGE_COLUMNS
from .outputs import CSV_FILENAMES, PAYLOAD_KEYS
from .team_game_layer import normalize_id


BRIEF_FILENAME = "wnba_broadcast_forecast_brief.md"
MAX_CHECKPOINT_GAMES = 5
CURRENT_STANDINGS_METHOD = (
    "Current standings reconstructed from completed regular-season schedule + "
    "team-box results."
)
CURRENT_500_METHOD = (
    "Current .500+ records are descriptive. Official final tiebreak simulations "
    "recompute the .500+ opponent set from each simulated final season."
)
SECTION_ORDER = (
    "Data cutoff and source status",
    "Current playoff picture",
    "Main findings",
    "Top-4 / home-court race",
    "Playoff cutline",
    "High-leverage games",
    "Useful broadcast checkpoints",
    "Tiebreak watch",
    "Historical context",
    "Method / caveats",
)

REQUIRED_MANIFEST_FIELDS = {
    "season",
    "cutoff_date",
    "simulation_count",
    "conditional_simulation_count",
    "random_seed",
    "model_version",
    "season_config_sha256",
    "model_config_sha256",
    "source_files",
    "pbpstats_enrichment_status",
    "history_seasons_used",
    "official_tiebreak_fallback_count",
    "external_standings_qa",
    "git_sha",
    "git_sha_status",
}

EXTERNAL_STANDINGS_QA_STATUSES = {
    "matched",
    "mismatch",
    "unavailable",
    "unparseable",
}

REQUIRED_COLUMNS = {
    "current_standings": {
        "team_id",
        "team_abbreviation",
        "current_rank",
        "games_played",
        "wins",
        "losses",
        "win_pct",
        "point_differential",
        "games_back",
        "home_record",
        "road_record",
        "last10_record",
        "current_streak_label",
        "conference_record",
        "record_vs_current_500_plus",
    },
    "head_to_head": {
        "team_id",
        "opponent_id",
        "games_played",
        "wins",
        "losses",
        "win_pct",
        "point_differential",
    },
    "team_strength": {
        "team_id",
        "season_net_rating",
        "recent_net_rating",
        "composite_strength",
        "pbpstats_snapshot_available",
        "pbpstats_snapshot_safe_for_cutoff",
    },
    "remaining_schedule": {
        "game_id",
        "game_date",
        "home_id",
        "away_id",
    },
    "matchup_probabilities": {
        "game_id",
        "game_date",
        "home_id",
        "away_id",
        "home_win_probability",
        "away_win_probability",
        "expected_home_margin",
    },
    "forecast_summary": {
        "season",
        "cutoff_date",
        "team_id",
        "team_abbreviation",
        "current_rank",
        "current_gp",
        "current_wins",
        "current_losses",
        "current_win_pct",
        "current_point_diff",
        "projected_wins_mean",
        "wins_p10",
        "wins_p50",
        "wins_p90",
        "expected_final_rank",
        "playoff_probability",
        "top4_probability",
        "home_court_probability",
        "out_probability",
        "remaining_sos_rank",
        "remaining_games",
        "clinched_playoffs",
        "eliminated_from_playoffs",
        "status_note",
    },
    "rank_probability_matrix": {
        "season",
        "cutoff_date",
        "team_id",
        "team_abbreviation",
        "final_rank",
        "probability",
        "playoff_rank",
    },
    "playoff_leverage_games": set(LEVERAGE_COLUMNS),
    "historical_context": set(HISTORICAL_CONTEXT_COLUMNS),
    "broadcast_insights": set(INSIGHT_COLUMNS),
}

PROBABILITY_COLUMNS = {
    "matchup_probabilities": ("home_win_probability", "away_win_probability"),
    "forecast_summary": (
        "playoff_probability",
        "top4_probability",
        "home_court_probability",
        "out_probability",
    ),
    "rank_probability_matrix": ("probability",),
}

BOOLEAN_FLAG_COLUMNS = (
    "conditional_estimate_available",
    "direct_h2h_tiebreak_flag",
    "cutline_matchup_flag",
    "top4_matchup_flag",
)

CONDITIONAL_PROBABILITY_GROUPS = (
    (
        "home_playoff_probability_if_home_win",
        "home_playoff_probability_if_home_loss",
        "home_playoff_probability_swing",
    ),
    (
        "away_playoff_probability_if_home_win",
        "away_playoff_probability_if_home_loss",
        "away_playoff_probability_swing",
    ),
    (
        "home_top4_probability_if_home_win",
        "home_top4_probability_if_home_loss",
        "home_top4_probability_swing",
    ),
    (
        "away_top4_probability_if_home_win",
        "away_top4_probability_if_home_loss",
        "away_top4_probability_swing",
    ),
)

CONDITIONAL_RANK_GROUPS = (
    (
        "home_expected_rank_if_home_win",
        "home_expected_rank_if_home_loss",
        "home_expected_rank_swing",
    ),
    (
        "away_expected_rank_if_home_win",
        "away_expected_rank_if_home_loss",
        "away_expected_rank_swing",
    ),
)

CONDITIONAL_VALUE_COLUMNS = tuple(
    column
    for group in (*CONDITIONAL_PROBABILITY_GROUPS, *CONDITIONAL_RANK_GROUPS)
    for column in group
)

TIEBREAK_LABELS = {
    "head_to_head_win_pct": "Head-to-head record",
    "record_vs_final_500_plus": "Winning percentage against teams finishing .500 or better",
    "head_to_head_point_diff": "Head-to-head point differential",
    "overall_point_diff": "Overall point differential",
}


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def _normalize_ids(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if column == "game_id" or column.endswith("_id"):
            result[column] = result[column].map(normalize_id)
    return result


def _validate_numeric(frame: pd.DataFrame, name: str) -> None:
    for column in frame.columns:
        if not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        present = pd.to_numeric(frame[column], errors="coerce").dropna()
        if not np.isfinite(present.to_numpy(dtype=float)).all():
            raise ValueError(f"{name} contains non-finite numeric values")


def _validate_probability_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    name: str,
    *,
    allow_missing: bool = False,
) -> None:
    for column in columns:
        if column not in frame.columns:
            continue
        supplied = frame[column]
        numeric = pd.to_numeric(supplied, errors="coerce")
        invalid_conversion = supplied.notna() & numeric.isna()
        present = numeric.dropna()
        if (
            invalid_conversion.any()
            or (not allow_missing and numeric.isna().any())
            or not np.isfinite(present.to_numpy(dtype=float)).all()
            or not present.between(0, 1).all()
        ):
            raise ValueError(f"{name} probabilities must be finite and within [0, 1]")


def _nullable_boolean(value: object, label: str) -> bool | None:
    if value is None or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"{label} must use the strict nullable Boolean domain")


def _validate_status_proof(forecast: pd.DataFrame) -> None:
    for index, row in forecast.iterrows():
        clinched = _nullable_boolean(
            row["clinched_playoffs"], "forecast_summary clinched_playoffs"
        )
        eliminated = _nullable_boolean(
            row["eliminated_from_playoffs"],
            "forecast_summary eliminated_from_playoffs",
        )
        if clinched is True and eliminated is True:
            raise ValueError(
                "forecast_summary clinched_playoffs and eliminated_from_playoffs "
                "cannot both be true"
            )
        note = str(row.get("status_note", "")).strip().lower()
        if clinched is True and ("eliminat" in note or note == "not_evaluated"):
            raise ValueError("forecast_summary status_note contradicts clinched proof")
        if eliminated is True and ("clinch" in note or note == "not_evaluated"):
            raise ValueError("forecast_summary status_note contradicts eliminated proof")
        forecast.at[index, "clinched_playoffs"] = clinched
        forecast.at[index, "eliminated_from_playoffs"] = eliminated


def _validate_conditional_state(
    leverage: pd.DataFrame, *, simulation_count: int, team_count: int
) -> None:
    for column in BOOLEAN_FLAG_COLUMNS:
        leverage[column] = leverage[column].map(
            lambda value, label=column: _nullable_boolean(
                value, f"playoff_leverage_games {label}"
            )
        )
        if leverage[column].isna().any():
            raise ValueError(
                f"playoff_leverage_games {column} must use a non-null Boolean"
            )

    for _, row in leverage.iterrows():
        home_wins = int(row["home_win_branch_n"])
        home_losses = int(row["home_loss_branch_n"])
        if home_wins + home_losses != simulation_count:
            raise ValueError(
                "playoff_leverage_games branch counts must sum to simulation_count"
            )
        available = bool(row["conditional_estimate_available"])
        raw_supplied = pd.Series(
            [row[column] for column in CONDITIONAL_VALUE_COLUMNS], dtype=object
        )
        supplied = pd.to_numeric(raw_supplied, errors="coerce")
        if available:
            if home_wins <= 0 or home_losses <= 0:
                raise ValueError(
                    "available conditional estimates require both branches to be positive"
                )
            if supplied.isna().any() or not np.isfinite(
                supplied.to_numpy(dtype=float)
            ).all():
                raise ValueError(
                    "available conditional values must all be finite and populated"
                )
            for win_column, loss_column, swing_column in CONDITIONAL_PROBABILITY_GROUPS:
                win_value = float(row[win_column])
                loss_value = float(row[loss_column])
                swing_value = float(row[swing_column])
                if not 0 <= win_value <= 1 or not 0 <= loss_value <= 1:
                    raise ValueError(
                        "conditional probabilities must be within [0, 1]"
                    )
                if not math.isclose(
                    swing_value,
                    win_value - loss_value,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    raise ValueError(
                        "conditional swing must equal home-win minus home-loss rate"
                    )
            for win_column, loss_column, swing_column in CONDITIONAL_RANK_GROUPS:
                win_value = float(row[win_column])
                loss_value = float(row[loss_column])
                swing_value = float(row[swing_column])
                if not 1 <= win_value <= team_count or not 1 <= loss_value <= team_count:
                    raise ValueError("conditional expected ranks must be configured ranks")
                if not math.isclose(
                    swing_value,
                    loss_value - win_value,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    raise ValueError(
                        "conditional swing must equal home-loss minus home-win expected rank"
                    )
        else:
            if home_wins > 0 and home_losses > 0:
                raise ValueError(
                    "unavailable conditional estimates require an empty branch"
                )
            if raw_supplied.notna().any():
                raise ValueError(
                    "unavailable conditional values must all be null"
                )


def _load_inputs(
    processed_root: Path, cfg: object
) -> tuple[dict[str, pd.DataFrame], dict, dict]:
    if not processed_root.is_dir():
        raise FileNotFoundError(
            f"processed forecast root does not exist: {processed_root}"
        )
    required_files = (*CSV_FILENAMES.values(), "forecast_payload.json", "run_manifest.json")
    missing = sorted(
        filename for filename in required_files if not (processed_root / filename).is_file()
    )
    if missing:
        raise FileNotFoundError(
            "processed forecast bundle is missing: " + ", ".join(missing)
        )

    frames = {
        name: _normalize_ids(pd.read_csv(processed_root / filename))
        for name, filename in CSV_FILENAMES.items()
    }
    for name, required in REQUIRED_COLUMNS.items():
        _require_columns(frames[name], required, name)
        _validate_numeric(frames[name], name)
    for rank in range(1, int(cfg.team_count) + 1):
        _require_columns(
            frames["forecast_summary"],
            {f"rank_{rank}_probability"},
            "forecast_summary",
        )
        _validate_probability_columns(
            frames["forecast_summary"],
            (f"rank_{rank}_probability",),
            "forecast_summary",
        )
    for name, columns in PROBABILITY_COLUMNS.items():
        _validate_probability_columns(
            frames[name],
            columns,
            name,
            allow_missing=name == "playoff_leverage_games",
        )

    manifest = json.loads((processed_root / "run_manifest.json").read_text(encoding="utf-8"))
    payload = json.loads((processed_root / "forecast_payload.json").read_text(encoding="utf-8"))
    missing_manifest = sorted(REQUIRED_MANIFEST_FIELDS.difference(manifest))
    if missing_manifest:
        raise ValueError(
            "run_manifest is missing required fields: " + ", ".join(missing_manifest)
        )
    if set(payload) != PAYLOAD_KEYS:
        raise ValueError("forecast_payload has unknown or missing top-level keys")
    if payload.get("metadata") != manifest:
        raise ValueError("forecast_payload metadata must match run_manifest")
    _external_standings_qa_summary(manifest)
    if int(manifest["season"]) != int(cfg.season):
        raise ValueError("run_manifest season does not match configured season")
    if not isinstance(manifest["source_files"], list) or not manifest["source_files"]:
        raise ValueError("run_manifest source_files must be a nonempty list")
    if (
        isinstance(manifest["simulation_count"], bool)
        or not isinstance(manifest["simulation_count"], int)
        or manifest["simulation_count"] <= 0
        or isinstance(manifest["random_seed"], bool)
        or not isinstance(manifest["random_seed"], int)
        or manifest["random_seed"] < 0
        or not str(manifest["model_version"]).strip()
    ):
        raise ValueError("run_manifest simulation/model metadata is invalid")
    manifest_cutoff = pd.to_datetime(manifest["cutoff_date"], errors="coerce")
    if pd.isna(manifest_cutoff):
        raise ValueError("run_manifest cutoff_date is invalid")

    current = frames["current_standings"]
    forecast = frames["forecast_summary"]
    for name, frame in (("current_standings", current), ("forecast_summary", forecast)):
        if frame["team_id"].isna().any() or frame["team_id"].eq("").any():
            raise ValueError(f"{name} contains blank team_id")
    team_ids = set(current["team_id"])
    if len(current) != int(cfg.team_count) or current["team_id"].duplicated().any():
        raise ValueError("current_standings team universe must match configured season")
    if set(forecast["team_id"]) != team_ids or forecast["team_id"].duplicated().any():
        raise ValueError("forecast_summary team universe must match current_standings")
    _validate_status_proof(forecast)
    ranks = pd.to_numeric(forecast["current_rank"], errors="coerce")
    if sorted(ranks.tolist()) != list(range(1, int(cfg.team_count) + 1)):
        raise ValueError("forecast_summary current_rank must be a complete permutation")

    insights = frames["broadcast_insights"]
    priorities = pd.to_numeric(insights["priority"], errors="coerce")
    if (
        len(insights) != 10
        or priorities.isna().any()
        or priorities.tolist() != list(range(1, 11))
    ):
        raise ValueError("broadcast_insights priorities must be exactly 1 through 10")
    if insights[INSIGHT_COLUMNS].isna().any().any():
        raise ValueError("broadcast_insights required fields must not be missing")
    if insights[INSIGHT_COLUMNS[1:]].apply(
        lambda column: column.astype(str).str.strip().eq("").any()
    ).any():
        raise ValueError("broadcast_insights required fields must not be blank")

    remaining = frames["remaining_schedule"]
    matchups = frames["matchup_probabilities"]
    leverage = frames["playoff_leverage_games"]
    for name, frame in (
        ("remaining_schedule", remaining),
        ("matchup_probabilities", matchups),
        ("playoff_leverage_games", leverage),
    ):
        if frame["game_id"].duplicated().any():
            raise ValueError(f"{name} contains duplicate game_id")
        if frame["game_id"].isna().any() or frame["game_id"].eq("").any():
            raise ValueError(f"{name} contains blank game_id")
        participants = set(frame["home_id"]) | set(frame["away_id"])
        if not participants.issubset(team_ids) or frame["home_id"].eq(frame["away_id"]).any():
            raise ValueError(f"{name} contains invalid participants")
        dates = pd.to_datetime(frame["game_date"], errors="coerce")
        if dates.isna().any():
            raise ValueError(f"{name} contains invalid game_date")
    remaining_ids = set(remaining["game_id"])
    if set(matchups["game_id"]) != remaining_ids or set(leverage["game_id"]) != remaining_ids:
        raise ValueError(
            "remaining, matchup, and leverage game relationships must match"
        )
    complements = matchups[["home_win_probability", "away_win_probability"]].sum(axis=1)
    if not np.allclose(complements, 1.0, rtol=0.0, atol=1e-12):
        raise ValueError("matchup probabilities must sum to one")
    scores = pd.to_numeric(leverage["leverage_score"], errors="coerce")
    branch_counts = leverage[["home_win_branch_n", "home_loss_branch_n"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if (
        scores.isna().any()
        or not scores.between(0, 100).all()
        or branch_counts.isna().any().any()
        or not np.isfinite(branch_counts.to_numpy(dtype=float)).all()
        or branch_counts.lt(0).any().any()
        or branch_counts.mod(1).ne(0).any().any()
    ):
        raise ValueError("playoff_leverage_games score/branch values are invalid")
    _validate_conditional_state(
        leverage,
        simulation_count=int(manifest["simulation_count"]),
        team_count=int(cfg.team_count),
    )

    for name in ("forecast_summary", "rank_probability_matrix"):
        seasons = pd.to_numeric(frames[name]["season"], errors="coerce")
        cutoffs = pd.to_datetime(frames[name]["cutoff_date"], errors="coerce")
        if (
            seasons.isna().any()
            or not seasons.eq(int(cfg.season)).all()
            or cutoffs.isna().any()
            or not cutoffs.dt.normalize().eq(pd.Timestamp(manifest_cutoff).normalize()).all()
        ):
            raise ValueError(f"{name} season/cutoff must match run_manifest")

    return frames, manifest, payload


def _clean_text(value: object) -> str:
    if value is None:
        return "Unavailable"
    try:
        if pd.isna(value):
            return "Unavailable"
    except (TypeError, ValueError):
        pass
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(character if character in "\n\t" or ord(character) >= 32 else " " for character in text)
    return text.replace("\n", "<br>").replace("\t", " ")


def _cell(value: object) -> str:
    return _clean_text(value).replace("\\", "\\\\").replace("|", r"\|")


def _probability(value: object) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    return f"{float(value):.1%}"


def _signed_probability(value: object) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    return f"{float(value):+.1%}"


def _number(value: object, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    return f"{float(value):.{digits}f}"


def _integer(value: object) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    return f"{int(value):,}"


def _date(value: object) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    parsed = pd.to_datetime(value, errors="coerce")
    return "Unavailable" if pd.isna(parsed) else pd.Timestamp(parsed).date().isoformat()


def _boolean(value: object) -> bool:
    parsed = _nullable_boolean(value, "validated Boolean")
    return parsed is True


def _table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return lines


def _status(row: pd.Series) -> str:
    if _boolean(row.get("clinched_playoffs")):
        return "Mathematically clinched"
    if _boolean(row.get("eliminated_from_playoffs")):
        return "Mathematically eliminated"
    note = _clean_text(row.get("status_note"))
    proof_language = "clinch" in note.lower() or "eliminat" in note.lower()
    if (
        row.get("clinched_playoffs") is None
        or pd.isna(row.get("clinched_playoffs"))
        or row.get("eliminated_from_playoffs") is None
        or pd.isna(row.get("eliminated_from_playoffs"))
    ):
        if (
            note.lower() != "not_evaluated"
            and note != "Unavailable"
            and not proof_language
        ):
            return note.replace("_", " ").capitalize()
        return "Status not evaluated"
    if note.lower() == "not_evaluated" or note == "Unavailable":
        return "Status not evaluated"
    if proof_language:
        return "Status not evaluated"
    return note.replace("_", " ").capitalize()


def _history_status(history: pd.DataFrame) -> str:
    if history.empty:
        return "unavailable"
    statuses = history["availability_status"].astype(str)
    available = statuses.eq("available").any()
    unavailable = statuses.ne("available").any()
    if available and unavailable:
        return "partial"
    return "available" if available else "unavailable"


def _source_summary(source: Mapping[str, object]) -> str:
    path = Path(str(source.get("path", "Unavailable")))
    return (
        f"{_clean_text(source.get('name', 'source'))}: {path.name} "
        f"(SHA-256 `{_clean_text(source.get('sha256'))}`, "
        f"{_integer(source.get('size_bytes'))} bytes)"
    )


def _external_standings_qa_summary(manifest: Mapping[str, object]) -> str:
    """Format only supplied external-standings QA evidence for renderers."""

    qa = manifest.get("external_standings_qa")
    if not isinstance(qa, Mapping):
        raise ValueError("run_manifest external_standings_qa must be an object")
    status = qa.get("status")
    if status not in EXTERNAL_STANDINGS_QA_STATUSES:
        raise ValueError("run_manifest external_standings_qa status is invalid")
    compared = qa.get("compared_team_count")
    mismatch_ids = qa.get("mismatch_team_ids")
    if (
        isinstance(compared, bool)
        or not isinstance(compared, int)
        or compared < 0
        or not isinstance(mismatch_ids, list)
    ):
        raise ValueError("run_manifest external_standings_qa counts are invalid")
    if status in {"unavailable", "unparseable"}:
        if compared != 0 or mismatch_ids:
            raise ValueError(
                "unavailable or unparseable external standings QA cannot contain comparisons"
            )
        return f"{status} (non-blocking; no external team comparison)"
    if status == "matched" and mismatch_ids:
        raise ValueError("matched external standings QA cannot contain mismatches")
    if status == "mismatch" and not mismatch_ids:
        raise ValueError("mismatch external standings QA must name mismatched teams")
    teams = "team" if compared == 1 else "teams"
    return f"{status} ({compared} {teams} compared; {len(mismatch_ids)} mismatched)"


def _build_markdown(
    frames: Mapping[str, pd.DataFrame], manifest: dict, cfg: object
) -> str:
    current = frames["current_standings"]
    current_by_team = current.set_index("team_id")
    forecast = frames["forecast_summary"].sort_values(
        ["current_rank", "team_id"], kind="stable"
    )
    abbreviations = current.set_index("team_id")["team_abbreviation"].to_dict()
    insights = frames["broadcast_insights"].sort_values(
        ["priority", "category"], kind="stable"
    )
    leverage = frames["playoff_leverage_games"].sort_values(
        ["leverage_score", "game_id"],
        ascending=[False, True],
        kind="stable",
    )
    matchups = frames["matchup_probabilities"].set_index("game_id")
    history = frames["historical_context"]
    history_state = _history_status(history)
    history_seasons = manifest.get("history_seasons_used", [])
    history_season_text = ", ".join(map(str, history_seasons)) or "none"

    lines = [
        f"# WNBA {int(cfg.season)} Standings & Playoff Forecast — Broadcast Brief",
        "",
        (
            f"**Run status:** cutoff **{_clean_text(manifest['cutoff_date'])}**; "
            f"{int(manifest['simulation_count']):,} simulations; seed "
            f"{int(manifest['random_seed'])}; model "
            f"`{_clean_text(manifest['model_version'])}`; PBP enrichment "
            f"**{_clean_text(manifest['pbpstats_enrichment_status'])}**; history "
            f"**{history_state}** ({history_season_text}); "
            f"{int(manifest['official_tiebreak_fallback_count']):,} stable-ID fallback events."
        ),
        "",
        f"## {SECTION_ORDER[0]}",
        "",
        (
            f"This {int(cfg.season)} snapshot is frozen through "
            f"**{_clean_text(manifest['cutoff_date'])}**. History status: "
            f"**{history_state}**; seasons used: **{history_season_text}**."
        ),
        "",
        f"- PBPStats enrichment: **{_clean_text(manifest['pbpstats_enrichment_status'])}**.",
        (
            "- External standings QA: **"
            f"{_clean_text(_external_standings_qa_summary(manifest))}**."
        ),
        f"- Model/config evidence: season `{manifest['season_config_sha256']}`; model `{manifest['model_config_sha256']}`.",
        f"- Git provenance: {_clean_text(manifest.get('git_sha') or manifest.get('git_sha_status'))}.",
        "- Source provenance:",
    ]
    lines.extend(f"  - {_source_summary(source)}" for source in manifest["source_files"])

    lines.extend(["", f"## {SECTION_ORDER[1]}", ""])
    lines.extend([CURRENT_STANDINGS_METHOD, ""])
    picture_rows = []
    for row in forecast.to_dict("records"):
        context = current_by_team.loc[row["team_id"]]
        picture_rows.append(
            (
                _integer(row["current_rank"]),
                row["team_abbreviation"],
                f"{_integer(row['current_wins'])}-{_integer(row['current_losses'])}",
                _probability(row["current_win_pct"]),
                _number(context["games_back"], 2),
                _clean_text(context["home_record"]),
                _clean_text(context["road_record"]),
                _clean_text(context["last10_record"]),
                _clean_text(context["current_streak_label"]),
                _clean_text(context["conference_record"]),
                _clean_text(context["record_vs_current_500_plus"]),
                _number(row["current_point_diff"]),
                _probability(row["playoff_probability"]),
                _number(row["expected_final_rank"], 2),
                _status(pd.Series(row)),
            )
        )
    lines.extend(
        _table(
            (
                "Rank",
                "Team",
                "Record",
                "Win %",
                "GB",
                "Home",
                "Road",
                "Last 10",
                "Streak",
                "Conference",
                "Current .500+",
                "Point diff",
                "Playoff %",
                "Expected rank",
                "Status",
            ),
            picture_rows,
        )
    )

    lines.extend(["", f"## {SECTION_ORDER[2]}", ""])
    for row in insights.to_dict("records"):
        # Prefixing the supplied snippet keeps even a leading '#' within a list
        # item, while preserving the literal quick-read string once.
        lines.extend(
            [
                f"{int(row['priority'])}. **{_clean_text(row['category']).replace('_', ' ').title()} — {_clean_text(row['team_or_race'])}:** {_clean_text(row['quick_read_snippet'])}",
                f"   - Data point: {_cell(row['data_point'])}",
                f"   - Why it matters: {_cell(row['why_it_matters'])}",
                f"   - Trigger/checkpoint: {_clean_text(row['pregame_trigger'])} / {_clean_text(row['halftime_checkpoint'])} / {_clean_text(row['fourth_quarter_checkpoint'])}",
                f"   - Source fields: `{_clean_text(row['source_fields'])}`",
            ]
        )

    top_limit = min(4, int(cfg.playoff_qualifiers))
    lines.extend(["", f"## {SECTION_ORDER[3]}", ""])
    top_rows = forecast.sort_values(
        ["home_court_probability", "team_id"],
        ascending=[False, True],
        kind="stable",
    ).head(max(top_limit + 2, top_limit))
    lines.append(
        f"Configured home-court boundary: top **{top_limit}** of the league-wide field."
    )
    lines.append("")
    lines.extend(
        _table(
            ("Team", "Current rank", "Top-4 / home-court %", "Expected rank", "Wins P10–P90"),
            [
                (
                    row.team_abbreviation,
                    _integer(row.current_rank),
                    _probability(row.home_court_probability),
                    _number(row.expected_final_rank, 2),
                    f"{_number(row.wins_p10)}–{_number(row.wins_p90)}",
                )
                for row in top_rows.itertuples()
            ],
        )
    )

    qualifier = int(cfg.playoff_qualifiers)
    lines.extend(["", f"## {SECTION_ORDER[4]}", ""])
    cutline = forecast.loc[forecast["current_rank"].isin((qualifier, qualifier + 1))]
    if len(cutline) < 2:
        lines.append("The configured field has no distinct in/out cutline pair.")
    else:
        lines.append(
            f"The configured playoff boundary is current rank **{qualifier}** versus **{qualifier + 1}**."
        )
        lines.append("")
        lines.extend(
            _table(
                ("Side", "Team", "Record", "Playoff %", "OUT %", "Expected rank", "Remaining SOS rank"),
                [
                    (
                        "IN" if int(row.current_rank) == qualifier else "OUT",
                        row.team_abbreviation,
                        f"{_integer(row.current_wins)}-{_integer(row.current_losses)}",
                        _probability(row.playoff_probability),
                        _probability(row.out_probability),
                        _number(row.expected_final_rank, 2),
                        _integer(row.remaining_sos_rank),
                    )
                    for row in cutline.itertuples()
                ],
            )
        )

    lines.extend(["", f"## {SECTION_ORDER[5]}", ""])
    if leverage.empty:
        lines.append("No remaining games are present in the validated bundle.")
    else:
        game_rows = []
        for row in leverage.itertuples():
            matchup = matchups.loc[row.game_id]
            branch = (
                f"available ({int(row.home_win_branch_n):,}/{int(row.home_loss_branch_n):,})"
                if _boolean(row.conditional_estimate_available)
                else "unavailable"
            )
            game_rows.append(
                (
                    _date(row.game_date),
                    f"{abbreviations[row.away_id]} at {abbreviations[row.home_id]}",
                    _probability(matchup.home_win_probability),
                    _number(row.leverage_score, 1),
                    row.leverage_label,
                    branch,
                    "yes" if _boolean(row.direct_h2h_tiebreak_flag) else "no",
                )
            )
        lines.extend(
            _table(
                ("Date", "Matchup", "Home win %", "Score", "Label", "Conditional branches W/L", "Direct H2H"),
                game_rows,
            )
        )

    lines.extend(["", f"## {SECTION_ORDER[6]}", ""])
    if leverage.empty:
        lines.append("No key games remain; checkpoints are not applicable.")
    else:
        game_story = insights.loc[insights["category"].eq("high_leverage_game")]
        story = game_story.iloc[0] if not game_story.empty else insights.iloc[0]
        for row in leverage.head(MAX_CHECKPOINT_GAMES).itertuples():
            home = abbreviations[row.home_id]
            away = abbreviations[row.away_id]
            lines.extend(
                [
                    f"### {_date(row.game_date)} — {_clean_text(away)} at {_clean_text(home)}",
                    "",
                    (
                        f"- **Pregame:** {_clean_text(story['pregame_trigger'])} "
                        f"Supplied home playoff swing: {_signed_probability(row.home_playoff_probability_swing)}; "
                        f"away swing: {_signed_probability(row.away_playoff_probability_swing)}."
                    ),
                    f"- **Halftime:** {_clean_text(story['halftime_checkpoint'])}",
                    f"- **Entering Q4:** {_clean_text(story['fourth_quarter_checkpoint'])}",
                    (
                        f"- **Postgame:** Rerun and update {_clean_text(home)} and {_clean_text(away)} "
                        "playoff probability, expected rank, and direct H2H/official tiebreak context; "
                        "do not state a mathematical status without supplied proof."
                    ),
                    "",
                ]
            )

    lines.extend([f"## {SECTION_ORDER[7]}", ""])
    lines.append("Official configured criteria, in order:")
    lines.append("")
    for index, criterion in enumerate(cfg.tiebreaks, start=1):
        lines.append(f"{index}. {_clean_text(TIEBREAK_LABELS.get(criterion, criterion))}.")
    flagged = leverage.loc[leverage["direct_h2h_tiebreak_flag"].map(_boolean)]
    if flagged.empty:
        lines.append("\n- Direct-H2H watch: no remaining game is flagged in this bundle.")
    else:
        flagged_games = ", ".join(
            f"{abbreviations[row.away_id]} at {abbreviations[row.home_id]} ({row.game_id})"
            for row in flagged.itertuples()
        )
        lines.append(f"\n- Direct-H2H watch: {_clean_text(flagged_games)}.")
    lines.append(
        f"- Fallback audit: **{int(manifest['official_tiebreak_fallback_count']):,} stable-ID fallback events** — unresolved tied subgroups across simulation rankings after the official criteria remained tied. Stable normalized team ID is an implementation fallback, not an official WNBA tiebreak rule."
    )

    lines.extend(["", f"## {SECTION_ORDER[8]}", ""])
    lines.append(f"History status: **{history_state}**.")
    if history.empty or not history["availability_status"].eq("available").any():
        lines.append("No historical benchmark is available for this run; no comparison is inferred.")
    else:
        lines.append("")
        history_rows = []
        for row in history.sort_values(
            ["availability_status", "season", "metric"],
            na_position="last",
            kind="stable",
        ).to_dict("records"):
            history_rows.append(
                (
                    row["availability_status"],
                    row["season"],
                    row["context_level"],
                    row["metric"],
                    _number(row["value"]),
                    _integer(row["sample_size"]),
                    _integer(row["season_count"]),
                )
            )
        lines.extend(
            _table(
                ("Status", "Season", "Level", "Metric", "Value", "Sample", "Seasons"),
                history_rows,
            )
        )
        if history_state == "partial":
            unavailable_statuses = sorted(
                set(history.loc[history["availability_status"].ne("available"), "availability_status"].astype(str))
            )
            lines.append(
                "\nUnavailable/partial source statuses retained: "
                + ", ".join(_clean_text(value) for value in unavailable_statuses)
                + "."
            )

    lines.extend(
        [
            "",
            f"## {SECTION_ORDER[9]}",
            "",
            (
                f"The top {qualifier} of {int(cfg.team_count)} teams qualify league-wide. "
                f"Probabilities are simulation estimates from the validated processed bundle "
                f"({int(manifest['simulation_count']):,} runs, seed {int(manifest['random_seed'])}, "
                f"model `{_clean_text(manifest['model_version'])}`). They are source-snapshot "
                "dependent and are not mathematical clinch or elimination proof."
            ),
            "",
            CURRENT_STANDINGS_METHOD,
            "",
            CURRENT_500_METHOD,
            "",
            "The brief selects and formats supplied standings, probabilities, conditional swings, leverage labels, and insight text. It does not rerank teams, resimulate games, or calculate a second forecast. Official tiebreak criteria appear above; stable-ID fallback is disclosed separately.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(text: str, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{final_path.name}.", suffix=".tmp", dir=final_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, final_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def render_markdown(processed_root: str | Path, *, cfg: object) -> Path:
    """Render the validated Task 11 bundle without forecasting calculations."""

    root = Path(processed_root).expanduser().resolve()
    frames, manifest, _payload = _load_inputs(root, cfg)
    markdown = _build_markdown(frames, manifest, cfg)
    output_root = Path(cfg.output_root).expanduser()
    if not output_root.is_absolute():
        raise ValueError("configured output_root must be absolute before rendering")
    final_path = (
        output_root
        / "deliverables"
        / f"season={cfg.season}"
        / "latest"
        / BRIEF_FILENAME
    )
    _atomic_write(markdown, final_path)
    return final_path


__all__ = [
    "BRIEF_FILENAME",
    "CURRENT_500_METHOD",
    "CURRENT_STANDINGS_METHOD",
    "SECTION_ORDER",
    "render_markdown",
]
