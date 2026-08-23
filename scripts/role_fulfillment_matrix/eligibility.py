"""Build a review-stage experience eligibility table and identity crosswalk."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict

import pandas as pd


class EligibilityBuildError(ValueError):
    """Raised when source data cannot support a complete deterministic build."""


@dataclass(frozen=True)
class EligibilityPackage:
    eligibility: pd.DataFrame
    crosswalk: pd.DataFrame
    manifest: Dict[str, Any]


PLAYER_CORE_REQUIRED = {
    "athlete_id",
    "slug",
    "full_name",
    "date_of_birth",
    "experience_years",
    "active",
    "status_type",
}
PLAYER_GAME_REQUIRED = {
    "game_date",
    "game_id",
    "player_id",
    "player_name",
    "team_abbreviation",
}


def normalize_player_name(value: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(character for character in folded if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", ascii_text.lower())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_columns(frame: pd.DataFrame, required: set[str], source_name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise EligibilityBuildError(
            f"{source_name} is missing required columns: {', '.join(missing)}"
        )
    if frame.empty:
        raise EligibilityBuildError(f"{source_name} is empty")


def _duplicate_values(frame: pd.DataFrame, column: str) -> list[str]:
    duplicated = frame.loc[frame[column].duplicated(keep=False), column]
    return sorted(set(duplicated.astype(str)))


def _age_on_cutoff(date_of_birth: pd.Timestamp, cutoff: date) -> int:
    birthday_passed = (cutoff.month, cutoff.day) >= (date_of_birth.month, date_of_birth.day)
    return cutoff.year - date_of_birth.year - (0 if birthday_passed else 1)


def _validate_sha256(value: str) -> str:
    normalized = str(value).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise EligibilityBuildError("source_sha256 must be a 64-character hexadecimal digest")
    return normalized


def build_eligibility_package(
    player_core: pd.DataFrame,
    player_game: pd.DataFrame,
    *,
    cutoff_date: str,
    source_as_of: str,
    source_path: str,
    source_sha256: str,
    experience_max: int = 3,
) -> EligibilityPackage:
    """Return pending eligibility rows plus a complete ESPN/PBPStats crosswalk."""
    _require_columns(player_core, PLAYER_CORE_REQUIRED, "player_core")
    _require_columns(player_game, PLAYER_GAME_REQUIRED, "player_game")
    if experience_max < 0:
        raise EligibilityBuildError("experience_max must be non-negative")
    source_digest = _validate_sha256(source_sha256)

    cutoff = pd.to_datetime(cutoff_date, errors="coerce")
    as_of = pd.to_datetime(source_as_of, errors="coerce")
    if pd.isna(cutoff):
        raise EligibilityBuildError("cutoff_date is invalid")
    if pd.isna(as_of):
        raise EligibilityBuildError("source_as_of is invalid")
    cutoff_value = cutoff.date()

    core = player_core.copy()
    core["athlete_id"] = core["athlete_id"].astype("string").str.strip()
    core["espn_player_name"] = core["full_name"].astype("string").str.strip()
    core["normalized_name"] = core["espn_player_name"].map(normalize_player_name)
    if (core["athlete_id"].isna() | core["athlete_id"].eq("")).any():
        raise EligibilityBuildError("player_core contains missing athlete_id values")
    duplicate_ids = _duplicate_values(core, "athlete_id")
    if duplicate_ids:
        raise EligibilityBuildError(f"player_core contains duplicate athlete_id values: {duplicate_ids}")
    if core["normalized_name"].eq("").any():
        raise EligibilityBuildError("player_core contains missing full_name values")
    duplicate_names = _duplicate_values(core, "normalized_name")
    if duplicate_names:
        raise EligibilityBuildError(
            "player_core contains duplicate normalized player names: " + ", ".join(duplicate_names)
        )

    core["experience_years"] = pd.to_numeric(core["experience_years"], errors="coerce")
    if core["experience_years"].isna().any() or (core["experience_years"] < 0).any():
        raise EligibilityBuildError("experience_years contains missing or invalid values")
    if (core["experience_years"] % 1 != 0).any():
        raise EligibilityBuildError("experience_years must contain whole numbers")
    core["experience_years"] = core["experience_years"].astype(int)

    core["date_of_birth_parsed"] = pd.to_datetime(
        core["date_of_birth"], errors="coerce", utc=True
    )
    if core["date_of_birth_parsed"].isna().any():
        raise EligibilityBuildError("date_of_birth contains missing or invalid values")

    games = player_game.copy()
    games["game_date"] = pd.to_datetime(games["game_date"], errors="coerce")
    if games["game_date"].isna().any():
        raise EligibilityBuildError("player_game contains invalid game_date values")
    games = games[games["game_date"].dt.date <= cutoff_value].copy()
    if games.empty:
        raise EligibilityBuildError("player_game has no rows on or before cutoff_date")
    games["player_id"] = games["player_id"].astype("string").str.strip()
    games["pbpstats_player_name"] = games["player_name"].astype("string").str.strip()
    games["normalized_name"] = games["pbpstats_player_name"].map(normalize_player_name)
    if games["player_id"].isna().any() or games["player_id"].eq("").any():
        raise EligibilityBuildError("player_game contains missing player_id values")

    identities_per_id = games.groupby("player_id")["normalized_name"].nunique()
    if (identities_per_id != 1).any():
        bad = sorted(identities_per_id[identities_per_id != 1].index.astype(str))
        raise EligibilityBuildError(f"player_id maps to multiple player names: {bad}")
    latest = (
        games.sort_values(["game_date", "game_id"])
        .drop_duplicates("player_id", keep="last")
        [[
            "player_id",
            "pbpstats_player_name",
            "normalized_name",
            "team_abbreviation",
            "game_date",
        ]]
        .rename(columns={"game_date": "latest_game_date"})
    )
    duplicate_pbp_names = _duplicate_values(latest, "normalized_name")
    if duplicate_pbp_names:
        raise EligibilityBuildError(
            "player_game contains duplicate normalized player names: "
            + ", ".join(duplicate_pbp_names)
        )

    matched = latest.merge(core, on="normalized_name", how="left", validate="one_to_one")
    missing = matched[matched["athlete_id"].isna()]["pbpstats_player_name"].tolist()
    if missing:
        raise EligibilityBuildError(
            "missing player-core matches for PBPStats players: " + ", ".join(sorted(missing))
        )

    matched["age_on_cutoff"] = matched["date_of_birth_parsed"].map(
        lambda value: _age_on_cutoff(value, cutoff_value)
    )
    matched["eligible_flag"] = matched["experience_years"] <= experience_max
    matched["eligibility_type"] = f"experience_le_{experience_max}"
    matched["review_status"] = "pending"
    matched["reviewed_by"] = pd.NA
    matched["reviewed_at"] = pd.NA
    matched["source_system"] = "ESPN"
    matched["source_url"] = matched.apply(
        lambda row: (
            "https://www.espn.com/wnba/player/bio/_/id/"
            f"{row['athlete_id']}/{row['slug']}"
        ),
        axis=1,
    )
    matched["source_snapshot_path"] = str(source_path)
    matched["source_snapshot_sha256"] = source_digest
    matched["source_as_of"] = as_of.date().isoformat()
    matched["identity_match_method"] = "normalized_full_name_exact"

    eligibility_columns = [
        "player_id",
        "pbpstats_player_name",
        "athlete_id",
        "espn_player_name",
        "team_abbreviation",
        "eligibility_type",
        "date_of_birth",
        "age_on_cutoff",
        "experience_years",
        "eligible_flag",
        "active",
        "status_type",
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "source_system",
        "source_url",
        "source_snapshot_path",
        "source_snapshot_sha256",
        "source_as_of",
        "identity_match_method",
    ]
    eligibility = matched[eligibility_columns].rename(columns={
        "pbpstats_player_name": "player_name",
        "athlete_id": "espn_athlete_id",
    })
    eligibility = eligibility.sort_values("player_name").reset_index(drop=True)

    matched_crosswalk = matched[[
        "normalized_name",
        "player_id",
        "pbpstats_player_name",
        "team_abbreviation",
        "latest_game_date",
        "athlete_id",
        "espn_player_name",
        "experience_years",
        "source_url",
    ]].copy()
    matched_crosswalk["match_status"] = "matched"
    matched_crosswalk["match_method"] = "normalized_full_name_exact"
    matched_crosswalk["exclusion_reason"] = ""

    source_only = core[~core["normalized_name"].isin(latest["normalized_name"])].copy()
    source_only_crosswalk = pd.DataFrame({
        "normalized_name": source_only["normalized_name"],
        "player_id": pd.NA,
        "pbpstats_player_name": pd.NA,
        "team_abbreviation": pd.NA,
        "latest_game_date": pd.NaT,
        "athlete_id": source_only["athlete_id"],
        "espn_player_name": source_only["espn_player_name"],
        "experience_years": source_only["experience_years"],
        "source_url": source_only.apply(
            lambda row: (
                "https://www.espn.com/wnba/player/bio/_/id/"
                f"{row['athlete_id']}/{row['slug']}"
            ),
            axis=1,
        ),
        "match_status": "source_only",
        "match_method": "normalized_full_name_exact",
        "exclusion_reason": "no_pbpstats_game_record",
    })
    crosswalk = pd.DataFrame(
        matched_crosswalk.to_dict("records") + source_only_crosswalk.to_dict("records")
    )
    crosswalk = crosswalk.rename(columns={"athlete_id": "espn_athlete_id"})
    crosswalk["latest_game_date"] = pd.to_datetime(
        crosswalk["latest_game_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    crosswalk = crosswalk.sort_values(
        ["match_status", "espn_player_name"], ascending=[True, True]
    ).reset_index(drop=True)

    pbpstats_players = int(len(latest))
    matched_players = int(len(matched))
    manifest = {
        "season": int(pd.to_numeric(player_core.get("season"), errors="coerce").dropna().iloc[0])
        if "season" in player_core and not player_core["season"].dropna().empty
        else None,
        "cutoff_date": cutoff_value.isoformat(),
        "source_as_of": as_of.date().isoformat(),
        "eligibility_rule": {
            "field": "experience_years",
            "operator": "<=",
            "threshold": int(experience_max),
            "eligibility_type": f"experience_le_{experience_max}",
        },
        "source": {
            "system": "ESPN",
            "path": str(source_path),
            "sha256": source_digest,
            "rows": int(len(core)),
        },
        "pbpstats_players": pbpstats_players,
        "matched_players": matched_players,
        "source_only_players": int(len(source_only)),
        "coverage_pct": round(100.0 * matched_players / pbpstats_players, 6),
        "eligible_players": int(eligibility["eligible_flag"].sum()),
        "ineligible_players": int((~eligibility["eligible_flag"]).sum()),
        "review_status": "pending",
        "live_scoring_status": "blocked",
    }
    return EligibilityPackage(eligibility=eligibility, crosswalk=crosswalk, manifest=manifest)


def write_eligibility_package(package: EligibilityPackage, output_dir: Path) -> Dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    eligibility_path = output / "player_eligibility_2026.pending.csv"
    crosswalk_path = output / "player_identity_crosswalk_2026.csv"
    manifest_path = output / "eligibility_build_manifest_2026.json"

    package.eligibility.to_csv(eligibility_path, index=False)
    package.crosswalk.to_csv(crosswalk_path, index=False)
    manifest = dict(package.manifest)
    manifest["outputs"] = {
        "eligibility": {
            "path": str(eligibility_path),
            "rows": int(len(package.eligibility)),
            "sha256": sha256_file(eligibility_path),
        },
        "crosswalk": {
            "path": str(crosswalk_path),
            "rows": int(len(package.crosswalk)),
            "sha256": sha256_file(crosswalk_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "eligibility_path": str(eligibility_path),
        "crosswalk_path": str(crosswalk_path),
        "manifest_path": str(manifest_path),
    }
