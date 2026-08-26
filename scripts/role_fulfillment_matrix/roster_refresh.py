"""Build a review-only RFM roster refresh from current ESPN team pages."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

import pandas as pd

from .eligibility import normalize_player_name
from .standings_adapter import normalize_team_abbreviation


class RosterRefreshError(ValueError):
    """Raised when an ESPN roster page or refresh candidate is unsafe to use."""


@dataclass(frozen=True)
class EspnRosterPage:
    team_id: str
    team_name: str
    generated_at_utc: str
    source_url: str
    page_sha256: str
    players: pd.DataFrame


@dataclass(frozen=True)
class RosterRefreshPackage:
    player_core: pd.DataFrame
    changes: pd.DataFrame
    manifest: Dict[str, Any]


@dataclass(frozen=True)
class PromotedRosterRefresh:
    player_core: pd.DataFrame
    eligibility: pd.DataFrame
    crosswalk: pd.DataFrame
    changes: pd.DataFrame
    quality: Dict[str, Any]


PLAYER_CORE_COLUMNS = [
    "season",
    "athlete_id",
    "guid",
    "uid",
    "slug",
    "type",
    "first_name",
    "last_name",
    "full_name",
    "display_name",
    "short_name",
    "height",
    "display_height",
    "weight",
    "display_weight",
    "age",
    "date_of_birth",
    "birth_city",
    "birth_state",
    "birth_country",
    "jersey",
    "position_id",
    "position_name",
    "position_abbreviation",
    "position_display_name",
    "college_id",
    "current_team_id",
    "headshot_href",
    "experience_years",
    "status_id",
    "status_name",
    "status_type",
    "draft_year",
    "draft_round",
    "draft_selection",
    "active",
]

POSITION_CONTEXT = {
    "G": ("3", "Guard"),
    "F": ("7", "Forward"),
    "C": ("9", "Center"),
}


def _identity(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _display_timestamp(value: str) -> str:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _birth_date_iso(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.strptime(text, "%m/%d/%y")
    except ValueError as exc:
        raise RosterRefreshError(f"invalid ESPN birthDate: {text}") from exc
    return parsed.strftime("%Y-%m-%dT08:00Z")


def _height_inches(value: Any) -> Any:
    match = re.fullmatch(r"\s*(\d+)\s*'\s*(\d+)\s*\"\s*", str(value or ""))
    if not match:
        return pd.NA
    return float(int(match.group(1)) * 12 + int(match.group(2)))


def _weight_pounds(value: Any) -> Any:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else pd.NA


def _slug_from_href(value: Any) -> str:
    text = str(value or "").rstrip("/")
    return text.rsplit("/", 1)[-1] if "/" in text else ""


def _normalize_page_player(player: Dict[str, Any], team_id: str) -> Dict[str, Any]:
    athlete_id = _identity(player.get("id"))
    name = str(player.get("name") or "").strip()
    last_name = str(player.get("lastName") or "").strip()
    if not athlete_id or not name or not last_name:
        raise RosterRefreshError("ESPN roster athlete is missing id, name, or lastName")
    position = str(player.get("position") or "").strip().upper()
    if position not in POSITION_CONTEXT:
        raise RosterRefreshError(
            f"unsupported ESPN position for {name}: {position or '<missing>'}"
        )
    position_id, position_name = POSITION_CONTEXT[position]
    first_name = name[: -len(last_name)].strip() if name.endswith(last_name) else name
    return {
        "season": 2026,
        "athlete_id": athlete_id,
        "guid": str(player.get("guid") or ""),
        "uid": str(player.get("uid") or ""),
        "slug": _slug_from_href(player.get("href")),
        "type": "basketball",
        "first_name": first_name,
        "last_name": last_name,
        "full_name": name,
        "display_name": name,
        "short_name": str(player.get("shortName") or ""),
        "height": _height_inches(player.get("height")),
        "display_height": str(player.get("height") or ""),
        "weight": _weight_pounds(player.get("weight")),
        "display_weight": str(player.get("weight") or ""),
        "age": player.get("age", pd.NA),
        "date_of_birth": _birth_date_iso(player.get("birthDate")),
        "birth_city": "",
        "birth_state": "",
        "birth_country": "",
        "jersey": str(player.get("jersey") or ""),
        "position_id": position_id,
        "position_name": position_name,
        "position_abbreviation": position,
        "position_display_name": position_name,
        "college_id": "",
        "current_team_id": team_id,
        "headshot_href": str(player.get("headshot") or ""),
        "experience_years": player.get("experience", pd.NA),
        "status_id": "1",
        "status_name": "Active",
        "status_type": "active",
        "draft_year": "",
        "draft_round": "",
        "draft_selection": "",
        "active": True,
    }


def parse_espn_roster_page(html: str, *, source_url: str) -> EspnRosterPage:
    """Extract the roster payload embedded in an ESPN team-roster HTML page."""
    marker = "window['__espnfitt__']="
    if marker not in html:
        raise RosterRefreshError("ESPN roster page is missing the embedded roster payload")
    try:
        payload, _ = json.JSONDecoder().raw_decode(html[html.index(marker) + len(marker) :])
        roster = payload["page"]["content"]["roster"]
        team = roster["team"]
        athletes = roster["athletes"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RosterRefreshError("ESPN roster page payload has an unsupported shape") from exc

    timestamp_match = re.search(
        r"<!--\s*ESPNFITT\s*\|.*?\|\s*([^|<>]+?GMT)\s*-->",
        html,
        flags=re.DOTALL,
    )
    if not timestamp_match:
        raise RosterRefreshError("ESPN roster page is missing its generated timestamp")
    team_id = _identity(team.get("id"))
    team_name = str(team.get("displayName") or "").strip()
    if not team_id or not team_name or not isinstance(athletes, list) or not athletes:
        raise RosterRefreshError("ESPN roster page is missing team or athlete context")

    players = pd.DataFrame([_normalize_page_player(player, team_id) for player in athletes])
    duplicate_ids = sorted(
        players.loc[players["athlete_id"].duplicated(keep=False), "athlete_id"].unique()
    )
    if duplicate_ids:
        raise RosterRefreshError(
            "ESPN roster page contains duplicate athlete IDs: " + ", ".join(duplicate_ids)
        )
    return EspnRosterPage(
        team_id=team_id,
        team_name=team_name,
        generated_at_utc=_display_timestamp(timestamp_match.group(1)),
        source_url=str(source_url),
        page_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
        players=players,
    )


def _complete_player_core(frame: pd.DataFrame) -> pd.DataFrame:
    complete = frame.copy()
    for column in PLAYER_CORE_COLUMNS:
        if column not in complete.columns:
            complete[column] = pd.NA
    complete = complete[PLAYER_CORE_COLUMNS]
    complete["athlete_id"] = complete["athlete_id"].map(_identity)
    complete["current_team_id"] = complete["current_team_id"].map(_identity)
    complete["active"] = complete["active"].map(_as_bool)
    return complete


def _change(
    change_type: str,
    athlete_id: str,
    player_name: str,
    old_value: Any,
    new_value: Any,
) -> Dict[str, Any]:
    return {
        "change_type": change_type,
        "athlete_id": athlete_id,
        "player_name": player_name,
        "old_value": "" if pd.isna(old_value) else str(old_value),
        "new_value": "" if pd.isna(new_value) else str(new_value),
        "review_status": "pending",
    }


def build_roster_refresh_candidate(
    base_player_core: pd.DataFrame,
    player_core_addenda: Sequence[pd.DataFrame],
    roster_pages: Sequence[EspnRosterPage],
    *,
    source_as_of: str,
    cutoff_date: str,
) -> RosterRefreshPackage:
    """Overlay current ESPN membership onto the historical player-core universe."""
    source_date = pd.to_datetime(source_as_of, errors="coerce")
    cutoff = pd.to_datetime(cutoff_date, errors="coerce")
    if pd.isna(source_date) or pd.isna(cutoff):
        raise RosterRefreshError("source_as_of and cutoff_date must be valid dates")
    if source_date.normalize() < cutoff.normalize():
        raise RosterRefreshError("roster source is older than the standings cutoff")
    if not roster_pages:
        raise RosterRefreshError("at least one ESPN roster page is required")

    base = _complete_player_core(base_player_core)
    parts = [base]
    for addendum in player_core_addenda:
        parts.append(_complete_player_core(addendum))
    historical = pd.DataFrame.from_records(
        [record for part in parts for record in part.to_dict(orient="records")],
        columns=PLAYER_CORE_COLUMNS,
    )
    if historical["athlete_id"].eq("").any():
        raise RosterRefreshError("historical player core contains missing athlete_id values")
    duplicate_historical = sorted(
        historical.loc[
            historical["athlete_id"].duplicated(keep=False), "athlete_id"
        ].unique()
    )
    if duplicate_historical:
        raise RosterRefreshError(
            "base player core and addenda contain duplicate athlete IDs: "
            + ", ".join(duplicate_historical)
        )

    current_parts = []
    source_urls = []
    generated_at_values = []
    team_ids = []
    for page in roster_pages:
        players = page.players.copy()
        players["_source_url"] = page.source_url
        current_parts.append(players)
        source_urls.append(page.source_url)
        generated_at_values.append(page.generated_at_utc)
        team_ids.append(page.team_id)
    if len(set(team_ids)) != len(team_ids):
        raise RosterRefreshError("duplicate team roster pages were supplied")
    current = pd.concat(current_parts, ignore_index=True)
    duplicated_current = sorted(
        current.loc[current["athlete_id"].duplicated(keep=False), "athlete_id"].unique()
    )
    if duplicated_current:
        raise RosterRefreshError(
            "athletes listed on multiple current roster pages: "
            + ", ".join(duplicated_current)
        )

    historical_ids = set(historical["athlete_id"])
    current_ids = set(current["athlete_id"])
    candidate = historical.set_index("athlete_id", drop=False).copy()
    changes = []

    for _, active_row in current.iterrows():
        athlete_id = active_row["athlete_id"]
        is_new = athlete_id not in historical_ids
        if is_new:
            candidate.loc[athlete_id] = [
                active_row.get(column, pd.NA) for column in PLAYER_CORE_COLUMNS
            ]
            changes.append(
                _change("added_active", athlete_id, active_row["full_name"], "", "active")
            )
        previous = candidate.loc[athlete_id].copy()
        for column in PLAYER_CORE_COLUMNS:
            value = active_row.get(column, pd.NA)
            if not pd.isna(value) and str(value).strip() != "":
                candidate.at[athlete_id, column] = value
        candidate.at[athlete_id, "active"] = True
        candidate.at[athlete_id, "status_id"] = "1"
        candidate.at[athlete_id, "status_name"] = "Active"
        candidate.at[athlete_id, "status_type"] = "active"
        if not is_new:
            if not _as_bool(previous["active"]):
                changes.append(
                    _change("activated", athlete_id, active_row["full_name"], False, True)
                )
            if _identity(previous["current_team_id"]) != active_row["current_team_id"]:
                changes.append(
                    _change(
                        "team_changed",
                        athlete_id,
                        active_row["full_name"],
                        _identity(previous["current_team_id"]),
                        active_row["current_team_id"],
                    )
                )
            old_position = str(previous["position_abbreviation"] or "").strip()
            if old_position != active_row["position_abbreviation"]:
                changes.append(
                    _change(
                        "position_changed",
                        athlete_id,
                        active_row["full_name"],
                        old_position,
                        active_row["position_abbreviation"],
                    )
                )

    removed = historical[
        historical["active"].map(_as_bool) & ~historical["athlete_id"].isin(current_ids)
    ]
    for _, previous in removed.iterrows():
        athlete_id = previous["athlete_id"]
        candidate.at[athlete_id, "active"] = False
        candidate.at[athlete_id, "status_id"] = pd.NA
        candidate.at[athlete_id, "status_name"] = "Pending roster review"
        candidate.at[athlete_id, "status_type"] = "pending-roster-review"
        changes.append(
            _change(
                "removed_from_active_page",
                athlete_id,
                previous["full_name"],
                "active",
                "pending-roster-review",
            )
        )

    candidate = candidate[PLAYER_CORE_COLUMNS].reset_index(drop=True)
    candidate["athlete_id"] = candidate["athlete_id"].map(_identity)
    candidate["active"] = candidate["active"].map(_as_bool)
    candidate = candidate.sort_values(
        ["full_name", "athlete_id"], na_position="last"
    ).reset_index(drop=True)
    changes_frame = pd.DataFrame(
        changes,
        columns=[
            "change_type",
            "athlete_id",
            "player_name",
            "old_value",
            "new_value",
            "review_status",
        ],
    ).sort_values(["change_type", "player_name", "athlete_id"]).reset_index(drop=True)

    new_active_count = int((changes_frame["change_type"] == "added_active").sum())
    removed_count = int(
        (changes_frame["change_type"] == "removed_from_active_page").sum()
    )
    blockers = []
    if new_active_count:
        blockers.append("new active identities require eligibility review")
    if removed_count:
        blockers.append("players removed from the active roster page require status review")
    if not changes_frame.empty:
        blockers.append("all material roster changes require explicit approval before promotion")

    manifest = {
        "source_system": "ESPN team roster pages",
        "source_as_of": source_date.date().isoformat(),
        "standings_cutoff": cutoff.date().isoformat(),
        "page_generated_at_utc_min": min(generated_at_values),
        "page_generated_at_utc_max": max(generated_at_values),
        "source_urls": sorted(source_urls),
        "team_pages": len(roster_pages),
        "historical_base_rows": int(len(base_player_core)),
        "historical_addendum_rows": int(sum(len(frame) for frame in player_core_addenda)),
        "candidate_rows": int(len(candidate)),
        "current_active_players": int(len(current)),
        "new_active_identities": new_active_count,
        "removed_from_active_page": removed_count,
        "material_changes": int(len(changes_frame)),
        "promotion_ready": not blockers,
        "blockers": blockers,
    }
    return RosterRefreshPackage(
        player_core=candidate,
        changes=changes_frame,
        manifest=manifest,
    )


def _age_at_cutoff(date_of_birth: Any, cutoff: pd.Timestamp) -> int:
    birth = pd.to_datetime(date_of_birth, errors="coerce", utc=True)
    if pd.isna(birth):
        raise RosterRefreshError(f"invalid date_of_birth in promoted roster: {date_of_birth}")
    birthday_passed = (cutoff.month, cutoff.day) >= (birth.month, birth.day)
    return cutoff.year - birth.year - (0 if birthday_passed else 1)


def promote_roster_refresh_candidate(
    pending_player_core: pd.DataFrame,
    pending_changes: pd.DataFrame,
    existing_eligibility: pd.DataFrame,
    existing_crosswalk: pd.DataFrame,
    standings: pd.DataFrame,
    *,
    departure_decisions: Dict[str, Dict[str, Any]],
    source_path: str,
    source_sha256: str,
    source_as_of: str,
    cutoff_date: str,
    reviewed_by: str,
    reviewed_at: str,
) -> PromotedRosterRefresh:
    """Resolve approved departures and add reviewed ESPN-only eligibility rows."""
    if not re.fullmatch(r"[0-9a-f]{64}", str(source_sha256).lower()):
        raise RosterRefreshError("source_sha256 must be a 64-character hexadecimal digest")
    source_date = pd.to_datetime(source_as_of, errors="coerce")
    cutoff = pd.to_datetime(cutoff_date, errors="coerce")
    review_date = pd.to_datetime(reviewed_at, errors="coerce")
    if pd.isna(source_date) or pd.isna(cutoff) or pd.isna(review_date):
        raise RosterRefreshError(
            "source_as_of, cutoff_date, and reviewed_at must be valid dates"
        )
    if not str(reviewed_by).strip():
        raise RosterRefreshError("reviewed_by is required")

    core = _complete_player_core(pending_player_core)
    if core["athlete_id"].duplicated().any():
        raise RosterRefreshError("pending player core contains duplicate athlete IDs")
    core = core.set_index("athlete_id", drop=False)
    unresolved_ids = set(
        core.loc[core["status_type"].eq("pending-roster-review"), "athlete_id"]
    )
    decision_ids = {_identity(value) for value in departure_decisions}
    if unresolved_ids != decision_ids:
        missing = sorted(unresolved_ids - decision_ids)
        unexpected = sorted(decision_ids - unresolved_ids)
        raise RosterRefreshError(
            f"departure decisions do not match unresolved roster rows; "
            f"missing={missing}, unexpected={unexpected}"
        )
    status_context = {
        "inactive": ("2", "Inactive"),
        "free-agent": ("9", "Free Agent"),
    }
    for raw_id, decision in departure_decisions.items():
        athlete_id = _identity(raw_id)
        status_type = str(decision.get("status_type") or "").strip().lower()
        if status_type not in status_context or _as_bool(decision.get("active")):
            raise RosterRefreshError(
                f"departure decision for {athlete_id} must be inactive or free-agent"
            )
        status_id, status_name = status_context[status_type]
        current_team_id = _identity(decision.get("current_team_id"))
        if status_type == "inactive" and not current_team_id:
            raise RosterRefreshError(
                f"inactive departure decision for {athlete_id} requires current_team_id"
            )
        if status_type == "free-agent" and current_team_id:
            raise RosterRefreshError(
                f"free-agent departure decision for {athlete_id} cannot retain team affiliation"
            )
        core.at[athlete_id, "active"] = False
        core.at[athlete_id, "status_id"] = status_id
        core.at[athlete_id, "status_name"] = status_name
        core.at[athlete_id, "status_type"] = status_type
        core.at[athlete_id, "current_team_id"] = current_team_id

    changes = pending_changes.copy()
    required_change_columns = {
        "change_type",
        "athlete_id",
        "player_name",
        "old_value",
        "new_value",
        "review_status",
    }
    missing_change_columns = sorted(required_change_columns - set(changes.columns))
    if missing_change_columns:
        raise RosterRefreshError(
            "pending changes missing columns: " + ", ".join(missing_change_columns)
        )
    changes["athlete_id"] = changes["athlete_id"].map(_identity)
    changes["review_status"] = "reviewed"
    for athlete_id, decision in departure_decisions.items():
        mask = (
            changes["athlete_id"].eq(_identity(athlete_id))
            & changes["change_type"].eq("removed_from_active_page")
        )
        changes.loc[mask, "new_value"] = str(decision["status_type"])

    team_required = {"team_id", "team_abbreviation"}
    if not team_required.issubset(standings.columns):
        raise RosterRefreshError("standings missing team_id or team_abbreviation")
    team_map = {
        _identity(row.team_id): normalize_team_abbreviation(row.team_abbreviation)
        for row in standings.itertuples(index=False)
    }

    eligibility = existing_eligibility.copy()
    crosswalk = existing_crosswalk.copy()
    eligibility["player_id"] = eligibility["player_id"].astype(str)
    eligibility["espn_athlete_id"] = eligibility["espn_athlete_id"].map(_identity)
    crosswalk["player_id"] = crosswalk["player_id"].fillna("").astype(str)
    crosswalk["espn_athlete_id"] = crosswalk["espn_athlete_id"].map(_identity)
    added_ids = sorted(
        set(
            changes.loc[changes["change_type"].eq("added_active"), "athlete_id"]
        )
        - set(eligibility["espn_athlete_id"])
    )
    new_eligibility = []
    new_crosswalk = []
    for athlete_id in added_ids:
        row = core.loc[athlete_id]
        team_id = _identity(row["current_team_id"])
        if team_id not in team_map:
            raise RosterRefreshError(
                f"new active player {row['full_name']} has no standings team mapping"
            )
        experience = pd.to_numeric(row["experience_years"], errors="coerce")
        if pd.isna(experience) or experience < 0 or experience % 1:
            raise RosterRefreshError(
                f"new active player {row['full_name']} has invalid experience_years"
            )
        experience = int(experience)
        player_id = f"espn:{athlete_id}"
        player_name = str(row["full_name"]).strip()
        source_url = (
            "https://www.espn.com/wnba/player/bio/_/id/"
            f"{athlete_id}/{row['slug']}"
        )
        new_eligibility.append(
            {
                "player_id": player_id,
                "player_name": player_name,
                "espn_athlete_id": athlete_id,
                "espn_player_name": player_name,
                "team_abbreviation": team_map[team_id],
                "eligibility_type": "experience_le_3",
                "date_of_birth": row["date_of_birth"],
                "age_on_cutoff": _age_at_cutoff(row["date_of_birth"], cutoff),
                "experience_years": experience,
                "eligible_flag": experience <= 3,
                "active": True,
                "status_type": "active",
                "review_status": "reviewed",
                "reviewed_by": str(reviewed_by).strip(),
                "reviewed_at": review_date.date().isoformat(),
                "source_system": "ESPN",
                "source_url": source_url,
                "source_snapshot_path": str(source_path),
                "source_snapshot_sha256": str(source_sha256).lower(),
                "source_as_of": source_date.date().isoformat(),
                "identity_match_method": "espn_roster_identity_no_pbpstats_record",
            }
        )
        new_crosswalk.append(
            {
                "normalized_name": normalize_player_name(player_name),
                "player_id": player_id,
                "pbpstats_player_name": "",
                "team_abbreviation": team_map[team_id],
                "latest_game_date": "",
                "espn_athlete_id": athlete_id,
                "espn_player_name": player_name,
                "experience_years": experience,
                "source_url": source_url,
                "match_status": "source_only",
                "match_method": "espn_roster_identity_reviewed",
                "exclusion_reason": "no_pbpstats_game_record",
            }
        )

    if new_eligibility:
        eligibility = pd.concat(
            [eligibility, pd.DataFrame(new_eligibility, columns=eligibility.columns)],
            ignore_index=True,
        )
        crosswalk = pd.concat(
            [crosswalk, pd.DataFrame(new_crosswalk, columns=crosswalk.columns)],
            ignore_index=True,
        )
    if eligibility["player_id"].duplicated().any() or eligibility[
        "espn_athlete_id"
    ].duplicated().any():
        raise RosterRefreshError("promoted eligibility contains duplicate identities")
    if crosswalk["normalized_name"].duplicated().any():
        raise RosterRefreshError("promoted crosswalk contains duplicate normalized names")

    core = core[PLAYER_CORE_COLUMNS].reset_index(drop=True).sort_values(
        ["full_name", "athlete_id"]
    ).reset_index(drop=True)
    eligibility = eligibility.sort_values(["player_name", "player_id"]).reset_index(drop=True)
    crosswalk = crosswalk.sort_values(
        ["match_status", "normalized_name", "espn_athlete_id"]
    ).reset_index(drop=True)
    return PromotedRosterRefresh(
        player_core=core,
        eligibility=eligibility,
        crosswalk=crosswalk,
        changes=changes.sort_values(
            ["change_type", "player_name", "athlete_id"]
        ).reset_index(drop=True),
        quality={
            "player_core_rows": int(len(core)),
            "active_players": int(core["active"].map(_as_bool).sum()),
            "inactive_players": int(core["status_type"].eq("inactive").sum()),
            "free_agents": int(core["status_type"].eq("free-agent").sum()),
            "new_eligibility_rows": int(len(new_eligibility)),
            "eligibility_rows": int(len(eligibility)),
            "crosswalk_rows": int(len(crosswalk)),
            "unresolved_departures": int(
                core["status_type"].eq("pending-roster-review").sum()
            ),
        },
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_records(frame: pd.DataFrame) -> list[Dict[str, Any]]:
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict(orient="records")


def _review_report(package: RosterRefreshPackage, pages: Sequence[EspnRosterPage]) -> str:
    manifest = package.manifest
    lines = [
        "# Role Fulfillment Matrix — Base Roster Refresh Review",
        "",
        "Review status: **pending**",
        "",
        f"Source as of: **{manifest['source_as_of']}**",
        f"Standings cutoff: **{manifest['standings_cutoff']}**",
        f"ESPN team pages: **{manifest['team_pages']}**",
        f"Current active roster entries: **{manifest['current_active_players']}**",
        f"Candidate identity rows: **{manifest['candidate_rows']}**",
        "",
        "## Refresh method",
        "",
        "The candidate overlays the current ESPN team-roster pages onto the historical player-core "
        "identity universe. Existing free-agent and inactive identities are retained. A player who "
        "was active in the prior input but is absent from every current ESPN team page is made "
        "inactive in the candidate with `pending-roster-review`; absence alone is not treated as "
        "proof of free-agent or inactive-rostered status.",
        "",
        "## Material changes",
        "",
        "| Change | Player | ESPN ID | Prior | Candidate | Review |",
        "|---|---|---:|---|---|---|",
    ]
    if package.changes.empty:
        lines.append("| None | — | — | — | — | — |")
    else:
        for row in package.changes.itertuples(index=False):
            lines.append(
                f"| {row.change_type} | {row.player_name} | {row.athlete_id} | "
                f"{row.old_value or '—'} | {row.new_value or '—'} | {row.review_status} |"
            )
    lines.extend(["", "## Promotion blockers", ""])
    if manifest["blockers"]:
        lines.extend(f"- {blocker}" for blocker in manifest["blockers"])
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Source pages",
            "",
            "| Team | Team ID | Players | Generated at (UTC) | Source | Page SHA256 |",
            "|---|---:|---:|---|---|---|",
        ]
    )
    for page in sorted(pages, key=lambda value: value.team_name):
        lines.append(
            f"| {page.team_name} | {page.team_id} | {len(page.players)} | "
            f"{page.generated_at_utc} | [ESPN roster]({page.source_url}) | "
            f"`{page.page_sha256}` |"
        )
    lines.extend(
        [
            "",
            "## Required review decisions",
            "",
            "1. Review every new active identity before extending eligibility coverage.",
            "2. Classify each prior active player absent from the current pages as inactive-rostered, "
            "free-agent, or another sourced status.",
            "3. Approve affiliation and position changes before replacing the live base snapshot.",
            "4. After approval, rebuild the base input, retire only redundant addenda, and rerun the "
            "freshness and coverage gates with scheduling still disabled.",
            "",
        ]
    )
    return "\n".join(lines)


def write_roster_refresh_package(
    package: RosterRefreshPackage,
    pages: Sequence[EspnRosterPage],
    output_directory: Path,
    *,
    snapshot_date: str,
) -> Dict[str, Path]:
    """Write one review package whose manifest pins every generated artifact."""
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "player_core_pending": output_directory
        / f"player_core_{snapshot_date}.pending.csv",
        "changes": output_directory / f"roster_refresh_changes_{snapshot_date}.csv",
        "source_snapshot": output_directory / f"espn_roster_pages_{snapshot_date}.json",
        "review_report": output_directory / f"roster_refresh_review_{snapshot_date}.md",
        "manifest": output_directory / f"roster_refresh_manifest_{snapshot_date}.json",
    }

    package.player_core.to_csv(paths["player_core_pending"], index=False)
    package.changes.to_csv(paths["changes"], index=False)
    source_snapshot = {
        "source_system": "ESPN team roster pages",
        "source_as_of": package.manifest["source_as_of"],
        "standings_cutoff": package.manifest["standings_cutoff"],
        "teams": [
            {
                "team_id": page.team_id,
                "team_name": page.team_name,
                "generated_at_utc": page.generated_at_utc,
                "source_url": page.source_url,
                "page_sha256": page.page_sha256,
                "players": _json_records(page.players),
            }
            for page in sorted(pages, key=lambda value: value.team_name)
        ],
    }
    paths["source_snapshot"].write_text(
        json.dumps(source_snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["review_report"].write_text(_review_report(package, pages), encoding="utf-8")

    manifest = dict(package.manifest)
    manifest["review_status"] = "pending"
    manifest["artifacts"] = {
        key: {
            "path": path.name,
            "sha256": _sha256_file(path),
        }
        for key, path in paths.items()
        if key != "manifest"
    }
    paths["manifest"].write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths
