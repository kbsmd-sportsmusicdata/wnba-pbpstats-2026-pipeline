"""Normalize the ESPN injury feed into a current availability report.

The raw feed carries one row per (injury, snapshot date), with ESPN's own status vocabulary
split across three columns (``status``, ``type_name``, ``detail_fantasy_status``). The analyses
downstream do not want that shape. They want a single, current answer to two questions:

* **Is this player available right now, and if not, how unavailable?** -- collapsed to one
  ordered ``availability_status`` (Out for season > Out > Day-to-day).
* **Is the absence a real injury, or roster housekeeping?** -- a knee that ends a season creates
  durable opportunity for a backup; a one-game "Coach's Decision" or a national-team call-up does
  not. ``absence_category`` keeps those apart so a consumer can weight them differently.

The feed is keyed on ESPN ``athlete_id``, a different id space from the pbpstats ``player_id`` the
analyses run on. Mapping the two is left to :func:`attach_player_ids`, which leans on the reviewed
crosswalk the role-fulfillment matrix already maintains, with a normalized-name fallback.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

import numpy as np
import pandas as pd


# WNBA is a fixed, stable set of franchises, so the ESPN-team-id -> repo-abbreviation map is
# reference data rather than something to re-derive on every run. Both keys are carried (id and
# display name) so a feed that renames a team or reissues an id is still resolved.
ESPN_TEAM_ID_TO_ABBREVIATION = {
    3: "DAL",
    5: "IND",
    6: "LAS",
    8: "MIN",
    9: "NYL",
    11: "PHX",
    14: "SEA",
    16: "WAS",
    17: "LVA",
    18: "CON",
    19: "CHI",
    20: "ATL",
    129689: "GSV",
    131935: "TOR",
    132052: "PDX",
}

TEAM_ABBREVIATION_BY_DISPLAY = {
    "Atlanta Dream": "ATL",
    "Chicago Sky": "CHI",
    "Connecticut Sun": "CON",
    "Dallas Wings": "DAL",
    "Golden State Valkyries": "GSV",
    "Indiana Fever": "IND",
    "Las Vegas Aces": "LVA",
    "Los Angeles Sparks": "LAS",
    "Minnesota Lynx": "MIN",
    "New York Liberty": "NYL",
    "Phoenix Mercury": "PHX",
    "Portland Fire": "PDX",
    "Seattle Storm": "SEA",
    "Toronto Tempo": "TOR",
    "Washington Mystics": "WAS",
}

# Ordered most-to-least severe. The rank doubles as the tie-breaker when one athlete carries
# several active injury rows in the same snapshot: the report keeps the most limiting one.
AVAILABILITY_STATUSES = ("Out for season", "Out", "Day-to-day")
_AVAILABILITY_RANK = {status: len(AVAILABILITY_STATUSES) - i for i, status in enumerate(AVAILABILITY_STATUSES)}

# ``detail_type`` values that are roster housekeeping rather than a medical absence. Everything
# else -- Knee, Ankle, Illness, Concussion, Undisclosed, ... -- is treated as an injury.
_NON_INJURY_REASONS = {
    "not injury related",
    "personal",
    "coach's decision",
    "coachs decision",
    "rest",
}

# ESPN's ``detail_fantasy_status`` is the clean season-ending flag (``OFS``), but it is sometimes
# left as ``OUT`` for a confirmed season-ender (e.g. NaLyssa Smith). The expected-return date is no
# help -- it is a ``2027-05-01`` placeholder on most late-season ``OUT`` rows -- so the fallback is
# the comment text. The pattern requires the period itself to be the season/year and rejects the
# single-game traps ("out for the season *finale*", "remainder of *the game*").
_SEASON_ENDING_RE = re.compile(
    r"(?:"
    r"(?:rest|remainder|balance) of (?:the )?(?:\d{4} )?(?:wnba )?season"
    r"|out for the (?:\d{4} )?(?:wnba )?season"
    r"|miss(?:ing|es|ed)? the (?:rest|remainder|balance) of the (?:\d{4} )?(?:wnba )?season"
    r"|will miss the (?:\d{4} )?(?:wnba )?season"
    r"|(?:done|shut down|sidelined) for the (?:rest of the )?(?:season|year)"
    r"|season[- ]ending"
    r")(?!\s+(?:finale|opener|debut|game))",
    re.IGNORECASE,
)


def mentions_season_ending(*texts: Any) -> bool:
    """True when a comment states the player is out for the rest of the season/year.

    Deliberately conservative: it matches explicit season-ending language and rejects the
    single-game phrasings that merely contain the word "season" (a "season finale", the
    "remainder of the game").
    """
    for text in texts:
        cleaned = _clean(text)
        if cleaned and _SEASON_ENDING_RE.search(cleaned):
            return True
    return False


def normalize_player_name(value: Any) -> str:
    """Accent-fold and strip a name to a stable join key (matches the RFM crosswalk builder)."""
    folded = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(character for character in folded if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", ascii_text.lower())


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def normalize_availability_status(status: Any, fantasy_status: Any) -> str:
    """Collapse ESPN's status columns to one ordered availability label.

    ``detail_fantasy_status`` carries the sharpest read -- ``OFS`` (out for season) and ``GTD``
    (game-time decision) are distinctions ``status`` alone loses -- so it is consulted first and
    ``status`` only fills the gap.
    """
    fantasy = _clean(fantasy_status).upper()
    if fantasy == "OFS":
        return "Out for season"
    if fantasy == "GTD":
        return "Day-to-day"
    raw = _clean(status).lower()
    if raw in {"day-to-day", "day to day", "questionable", "doubtful"}:
        return "Day-to-day"
    if fantasy == "OUT" or raw == "out":
        return "Out"
    # An unrecognized status is reported as Out rather than dropped: a player on the injury feed
    # is by definition not fully available, and silently discarding them would overstate a roster.
    return "Out"


def classify_absence_reason(detail_type: Any) -> str:
    """`injury` for a medical absence, `non_injury` for roster housekeeping."""
    reason = _clean(detail_type).lower()
    if not reason:
        return "unspecified"
    return "non_injury" if reason in _NON_INJURY_REASONS else "injury"


def frees_rotation_minutes(frame: pd.DataFrame) -> pd.Series:
    """Rows whose absence durably frees the player's rotation minutes.

    Any injury absence qualifies, and so does *any* player ruled out for the season regardless of
    ESPN's reason category. A player who has left the team for the year (filed personal /
    not-injury-related) vacates their minutes exactly as a season-ending injury does; only
    short-term non-injury absences -- national-team duty, a one-game coach's decision -- are
    excluded, because those minutes come back. Callers combine this with their own ``is_out``
    filter; ``is_out_for_season`` already implies ``is_out``.
    """
    index = frame.index
    category = frame["absence_category"] if "absence_category" in frame else pd.Series("", index=index)
    ofs = frame["is_out_for_season"] if "is_out_for_season" in frame else pd.Series(False, index=index)
    return category.eq("injury") | ofs.fillna(False).astype(bool)


def _map_team_abbreviation(team_id: Any, team_display_name: Any) -> str:
    try:
        abbreviation = ESPN_TEAM_ID_TO_ABBREVIATION.get(int(team_id))
    except (TypeError, ValueError):
        abbreviation = None
    if abbreviation:
        return abbreviation
    return TEAM_ABBREVIATION_BY_DISPLAY.get(_clean(team_display_name), "")


def normalize_injuries(injuries: pd.DataFrame) -> pd.DataFrame:
    """Add derived availability columns to every row of the raw feed, all snapshots kept."""
    columns = [
        "as_of_date",
        "season",
        "team_id",
        "team_display_name",
        "team_abbreviation",
        "athlete_id",
        "athlete_display_name",
        "normalized_name",
        "athlete_position",
        "availability_status",
        "availability_rank",
        "is_out",
        "is_out_for_season",
        "is_day_to_day",
        "absence_reason",
        "absence_category",
        "injury_side",
        "injury_date",
        "expected_return_date",
        "short_comment",
    ]
    if injuries is None or injuries.empty:
        return pd.DataFrame(columns=columns)

    frame = injuries.copy()
    out = pd.DataFrame(index=frame.index)
    out["as_of_date"] = frame.get("as_of_date").map(_clean) if "as_of_date" in frame else ""
    out["season"] = pd.to_numeric(frame.get("season"), errors="coerce").astype("Int64")
    out["team_id"] = pd.to_numeric(frame.get("team_id"), errors="coerce").astype("Int64")
    out["team_display_name"] = frame.get("team_display_name").map(_clean) if "team_display_name" in frame else ""
    out["team_abbreviation"] = [
        _map_team_abbreviation(team_id, display)
        for team_id, display in zip(frame.get("team_id"), frame.get("team_display_name"))
    ]
    out["athlete_id"] = pd.to_numeric(frame.get("athlete_id"), errors="coerce").astype("Int64")
    out["athlete_display_name"] = frame.get("athlete_display_name").map(_clean) if "athlete_display_name" in frame else ""
    out["normalized_name"] = out["athlete_display_name"].map(normalize_player_name)
    out["athlete_position"] = frame.get("athlete_position").map(_clean) if "athlete_position" in frame else ""

    out["availability_status"] = [
        normalize_availability_status(status, fantasy)
        for status, fantasy in zip(frame.get("status"), frame.get("detail_fantasy_status"))
    ]
    # Upgrade to season-ending when the comment says so even though ESPN left the status as OUT.
    short_comments = frame.get("short_comment")
    long_comments = frame.get("long_comment")
    season_ending = [
        mentions_season_ending(
            short_comments.iloc[i] if short_comments is not None else "",
            long_comments.iloc[i] if long_comments is not None else "",
        )
        for i in range(len(frame))
    ]
    out.loc[pd.Series(season_ending, index=out.index), "availability_status"] = "Out for season"
    out["availability_rank"] = out["availability_status"].map(_AVAILABILITY_RANK).astype("Int64")
    out["is_out_for_season"] = out["availability_status"].eq("Out for season")
    out["is_day_to_day"] = out["availability_status"].eq("Day-to-day")
    # "Out" and "Out for season" both mean unavailable in the next game; day-to-day does not.
    out["is_out"] = out["availability_status"].isin(("Out", "Out for season"))

    out["absence_reason"] = frame.get("detail_type").map(_clean) if "detail_type" in frame else ""
    out["absence_category"] = out["absence_reason"].map(classify_absence_reason)
    out["injury_side"] = frame.get("detail_side").map(_clean) if "detail_side" in frame else ""
    out["injury_date"] = frame.get("injury_date").map(_clean) if "injury_date" in frame else ""
    out["expected_return_date"] = frame.get("detail_return_date").map(_clean) if "detail_return_date" in frame else ""
    # ESPN files a next-season placeholder (2027-05-01) as the return date for indefinite/short-term
    # OUT rows; it is not a real ETA (it sits identically on season-enders and day-to-day ankles), so
    # a return date after the current season is blanked rather than published as an expected return.
    return_year = pd.to_datetime(out["expected_return_date"], errors="coerce").dt.year
    season_year = pd.to_numeric(out["season"], errors="coerce")
    out.loc[return_year.notna() & season_year.notna() & (return_year > season_year), "expected_return_date"] = ""
    out["short_comment"] = frame.get("short_comment").map(_clean) if "short_comment" in frame else ""
    return out[columns].reset_index(drop=True)


def latest_as_of(normalized: pd.DataFrame) -> Optional[str]:
    if normalized.empty or "as_of_date" not in normalized:
        return None
    values = [value for value in normalized["as_of_date"].tolist() if value]
    return max(values) if values else None


def build_current_report(injuries: pd.DataFrame, *, as_of: Optional[str] = None) -> pd.DataFrame:
    """One row per player for a single snapshot -- the current-availability view.

    ``as_of`` defaults to the most recent snapshot in the feed. When a player carries more than one
    active listing on that date (a knee and an illness, say), the most limiting status wins and,
    within a status, the more recently dated injury.
    """
    normalized = normalize_injuries(injuries)
    if normalized.empty:
        return normalized

    snapshot_date = as_of or latest_as_of(normalized)
    snapshot = normalized[normalized["as_of_date"] == snapshot_date].copy()
    if snapshot.empty:
        return snapshot

    snapshot = snapshot.sort_values(
        ["athlete_id", "availability_rank", "injury_date"],
        ascending=[True, False, False],
    )
    current = snapshot.drop_duplicates(subset=["athlete_id"], keep="first").reset_index(drop=True)
    return current


def attach_player_ids(report: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Resolve the pbpstats ``player_id`` for each ESPN athlete.

    Preference order: exact ESPN athlete-id match against the reviewed crosswalk, then a
    normalized-name match. ``player_id`` is the crosswalk's canonical id (kept as text, since some
    source-only rows use an ``espn:<id>`` sentinel); ``pbpstats_player_id`` is the same value
    coerced to the numeric key the pbpstats feeds join on, or null when there is no numeric id.
    """
    out = report.copy()
    out["player_id"] = ""
    out["player_id_match"] = "unmatched"
    if out.empty:
        out["pbpstats_player_id"] = pd.array([], dtype="Int64")
        return out
    if crosswalk is None or crosswalk.empty:
        out["pbpstats_player_id"] = pd.array([pd.NA] * len(out), dtype="Int64")
        return out

    xwalk = crosswalk.copy()
    xwalk["player_id"] = xwalk["player_id"].astype(str).str.strip()
    if "espn_athlete_id" in xwalk:
        xwalk["espn_athlete_id"] = pd.to_numeric(xwalk["espn_athlete_id"], errors="coerce").astype("Int64")
        by_id = (
            xwalk.dropna(subset=["espn_athlete_id"])
            .drop_duplicates(subset=["espn_athlete_id"], keep="first")
            .set_index("espn_athlete_id")["player_id"]
        )
    else:
        by_id = pd.Series(dtype=str)

    name_source = xwalk.get("player_name")
    if name_source is None:
        name_source = xwalk.get("espn_player_name")
    xwalk["_normalized_name"] = name_source.map(normalize_player_name) if name_source is not None else ""
    by_name = (
        xwalk[xwalk["_normalized_name"] != ""]
        .drop_duplicates(subset=["_normalized_name"], keep="first")
        .set_index("_normalized_name")["player_id"]
    )

    for position, row in enumerate(out.itertuples(index=False)):
        athlete_id = getattr(row, "athlete_id")
        matched = ""
        method = "unmatched"
        if pd.notna(athlete_id) and int(athlete_id) in by_id.index:
            matched = by_id.loc[int(athlete_id)]
            method = "espn_athlete_id"
        else:
            normalized = getattr(row, "normalized_name", "")
            if normalized and normalized in by_name.index:
                matched = by_name.loc[normalized]
                method = "normalized_name"
        out.iat[position, out.columns.get_loc("player_id")] = matched
        out.iat[position, out.columns.get_loc("player_id_match")] = method

    out["pbpstats_player_id"] = pd.to_numeric(out["player_id"], errors="coerce").astype("Int64")
    return out


def build_team_availability(current_report: pd.DataFrame) -> pd.DataFrame:
    """Team-level rollup of who is currently unavailable and why.

    Counts only, deliberately: a minutes- or usage-weighted "how much does this hurt" belongs in
    each analysis that owns those weights (functional depth, hidden value), not in the shared feed.
    """
    columns = [
        "team_abbreviation",
        "as_of_date",
        "players_listed",
        "players_out",
        "players_out_for_season",
        "players_day_to_day",
        "injury_absences",
        "non_injury_absences",
        "players_out_names",
        "out_for_season_names",
    ]
    if current_report.empty:
        return pd.DataFrame(columns=columns)

    frame = current_report.copy()
    frame["team_abbreviation"] = frame["team_abbreviation"].replace("", np.nan)
    frame = frame.dropna(subset=["team_abbreviation"])
    if frame.empty:
        return pd.DataFrame(columns=columns)

    as_of = latest_as_of(frame)
    rows = []
    for team, group in frame.groupby("team_abbreviation", sort=True):
        out_group = group[group["is_out"]]
        ofs_group = group[group["is_out_for_season"]]
        rows.append(
            {
                "team_abbreviation": team,
                "as_of_date": as_of,
                "players_listed": int(len(group)),
                "players_out": int(group["is_out"].sum()),
                "players_out_for_season": int(group["is_out_for_season"].sum()),
                "players_day_to_day": int(group["is_day_to_day"].sum()),
                "injury_absences": int((group["is_out"] & group["absence_category"].eq("injury")).sum()),
                "non_injury_absences": int((group["is_out"] & group["absence_category"].eq("non_injury")).sum()),
                "players_out_names": "; ".join(sorted(out_group["athlete_display_name"].tolist())),
                "out_for_season_names": "; ".join(sorted(ofs_group["athlete_display_name"].tolist())),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("team_abbreviation").reset_index(drop=True)
