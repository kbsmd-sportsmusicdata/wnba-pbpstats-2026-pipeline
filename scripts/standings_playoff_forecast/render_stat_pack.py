"""Render the validated forecast bundle as a one-page broadcast stat-pack."""

from __future__ import annotations

import html
import os
import tempfile
from pathlib import Path
from typing import Mapping

import pandas as pd

from .render_markdown import _load_inputs, _nullable_boolean


STAT_PACK_FILENAME = "wnba_playoff_stat_pack_insert.html"
TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "analysis"
    / "standings_playoff_forecast"
    / "templates"
)


def _text(value: object, unavailable: str = "Unavailable") -> str:
    if value is None:
        return unavailable
    try:
        if pd.isna(value):
            return unavailable
    except (TypeError, ValueError):
        pass
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        character if character in "\n\t" or ord(character) >= 32 else " "
        for character in normalized
    )
    return html.escape(normalized, quote=True).replace("\n", "<br>")


def _pct(value: object) -> str:
    return "Unavailable" if pd.isna(value) else f"{float(value):.1%}"


def _number(value: object, digits: int = 1) -> str:
    return "Unavailable" if pd.isna(value) else f"{float(value):.{digits}f}"


def _integer(value: object) -> str:
    return "Unavailable" if pd.isna(value) else f"{int(value):,}"


def _date(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "Unavailable" if pd.isna(parsed) else pd.Timestamp(parsed).date().isoformat()


def _ordinal(value: int) -> str:
    suffix = "th" if 10 <= value % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _table(
    headers: tuple[str, ...],
    rows: list[tuple[object, ...]],
    *,
    class_name: str = "data-table",
) -> str:
    head = "".join(f"<th scope=\"col\">{header}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return (
        f'<div class="table-scroll"><table class="{class_name}">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _build_stat_pack(
    frames: Mapping[str, pd.DataFrame], manifest: dict, cfg: object, template: str, css: str
) -> str:
    qualifier = int(cfg.playoff_qualifiers)
    team_count = int(cfg.team_count)
    forecast = frames["forecast_summary"].sort_values(
        ["current_rank", "team_id"], kind="stable"
    )
    abbreviations = forecast.set_index("team_id")["team_abbreviation"].to_dict()
    matrix = frames["rank_probability_matrix"].copy()
    insights = frames["broadcast_insights"].sort_values(
        ["priority", "category"], kind="stable"
    )
    leverage = frames["playoff_leverage_games"].sort_values(
        ["leverage_score", "game_id"], ascending=[False, True], kind="stable"
    )

    current_field = forecast.loc[forecast["current_rank"].le(qualifier)]
    field_rows = [
        (
            _integer(row.current_rank),
            _text(row.team_abbreviation),
            f"{_integer(row.current_wins)}–{_integer(row.current_losses)}",
            _pct(row.current_win_pct),
        )
        for row in current_field.itertuples()
    ]
    field_table = _table(("Rank", "Team", "W–L", "Pct"), field_rows)

    cutline = forecast.loc[
        forecast["current_rank"].isin((qualifier, qualifier + 1))
    ].sort_values("current_rank", kind="stable")
    if len(cutline) == 2:
        inside, outside = list(cutline.itertuples())
        cutline_markup = (
            f'<p class="cutline-callout">{_ordinal(qualifier)} / {_ordinal(qualifier + 1)} cutline</p>'
            f'<p class="cutline-teams"><strong>{_text(inside.team_abbreviation)}</strong> '
            f'{_pct(inside.playoff_probability)} · <strong>{_text(outside.team_abbreviation)}</strong> '
            f'{_pct(outside.playoff_probability)}</p>'
        )
    else:
        cutline_markup = '<p class="empty-state">No distinct cutline pair.</p>'

    projected_rows = [
        (
            _integer(index),
            _text(row.team_abbreviation),
            f'<strong class="probability">{_pct(row.playoff_probability)}</strong>',
            _number(row.expected_final_rank, 2),
            f"{_number(row.wins_p10)}–{_number(row.wins_p50)}–{_number(row.wins_p90)}",
        )
        for index, row in enumerate(
            forecast.sort_values(
                ["projected_wins_mean", "team_id"], ascending=[False, True], kind="stable"
            ).itertuples(),
            start=1,
        )
    ]
    projected_table = _table(
        ("", "Team", "Playoff", "Exp rank", "P10 · P50 · P90"), projected_rows
    )

    race_low = max(1, qualifier - 3)
    race_high = min(team_count, qualifier + 3)
    race_team_ids = forecast.loc[
        forecast["current_rank"].between(race_low, race_high), "team_id"
    ].tolist()
    if not race_team_ids:
        race_team_ids = forecast["team_id"].head(min(team_count, 7)).tolist()
    pivot = matrix.pivot(index="team_id", columns="final_rank", values="probability")
    heat_headers = ("Team",) + tuple(str(rank) for rank in range(1, team_count + 1))
    heat_rows: list[tuple[object, ...]] = []
    for team_id in race_team_ids:
        cells: list[object] = [_text(abbreviations[team_id])]
        for rank in range(1, team_count + 1):
            probability = float(pivot.loc[team_id, rank])
            shade = min(95, 8 + round(probability * 87))
            cells.append(
                f'<span class="heat-cell" style="--heat:{shade}%">{probability:.1%}</span>'
            )
        heat_rows.append(tuple(cells))
    heat_table = _table(heat_headers, heat_rows, class_name="data-table heat-table")

    sos = forecast.loc[forecast["remaining_sos_rank"].notna()].sort_values(
        ["remaining_sos_rank", "team_id"], kind="stable"
    )
    sos_extremes = pd.concat([sos.head(3), sos.tail(3)]).drop_duplicates("team_id")
    sos_table = _table(
        ("Team", "SOS rank", "Remaining"),
        [
            (
                _text(row.team_abbreviation),
                _integer(row.remaining_sos_rank),
                _integer(row.remaining_games),
            )
            for row in sos_extremes.itertuples()
        ],
    ) if not sos_extremes.empty else '<p class="empty-state">Season schedule complete; no remaining SOS.</p>'

    leverage_rows = []
    for row in leverage.head(5).itertuples():
        conditional = _nullable_boolean(
            row.conditional_estimate_available,
            "playoff_leverage_games conditional_estimate_available",
        )
        swing = (
            f"{float(row.home_playoff_probability_swing):+.1%} / "
            f"{float(row.away_playoff_probability_swing):+.1%}"
            if conditional is True
            else "Conditional estimate unavailable"
        )
        leverage_rows.append(
            (
                _date(row.game_date),
                f"{_text(abbreviations[row.away_id])} at {_text(abbreviations[row.home_id])}",
                _number(row.leverage_score, 1),
                _text(row.leverage_label),
                swing,
            )
        )
    leverage_table = _table(
        ("Date", "Matchup", "Score", "Level", "Home / away playoff swing"),
        leverage_rows,
    ) if leverage_rows else '<p class="empty-state">No remaining games or conditional branches.</p>'

    nugget_markup = "".join(
        (
            '<li class="nugget">'
            f'<span class="nugget-number">{int(row.priority)}</span>'
            f'<span><strong>{_text(str(row.category).replace("_", " ").title())}:</strong> '
            f'{_text(row.quick_read_snippet)} <em>{_text(row.why_it_matters)}</em></span>'
            "</li>"
        )
        for row in insights.head(5).itertuples()
    )
    tiebreak_items = "".join(
        f"<li>{_text(str(criterion).replace('_', ' ').title())}</li>"
        for criterion in cfg.tiebreaks
    )
    source_names = ", ".join(
        _text(Path(str(source.get("path", source.get("name", "source")))).name)
        for source in manifest["source_files"]
    )
    method = (
        f"{int(manifest['simulation_count']):,} simulations · seed "
        f"{int(manifest['random_seed'])} · model {_text(manifest['model_version'])}. "
        f"Sources: {source_names}. PBPStats enrichment: "
        f"{_text(manifest['pbpstats_enrichment_status'])}. Probabilities are estimates, "
        "not mathematical clinch or elimination proof."
    )

    replacements = {
        "INLINE_CSS": css,
        "SEASON": str(int(cfg.season)),
        "CUTOFF": _text(manifest["cutoff_date"]),
        "MODEL": _text(manifest["model_version"]),
        "SIMULATIONS": f"{int(manifest['simulation_count']):,}",
        "SOURCE_FILES": source_names,
        "PBP_STATUS": _text(manifest["pbpstats_enrichment_status"]),
        "CURRENT_FIELD": field_table,
        "CUTLINE": cutline_markup,
        "PROJECTED": projected_table,
        "HEATMAP": heat_table,
        "SOS": sos_table,
        "LEVERAGE": leverage_table,
        "NUGGETS": nugget_markup,
        "TIEBREAKS": tiebreak_items,
        "FALLBACK_COUNT": f"{int(manifest['official_tiebreak_fallback_count']):,}",
        "METHOD": method,
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    unresolved = [key for key in replacements if "{{" + key + "}}" in rendered]
    if unresolved or "{{" in rendered:
        raise ValueError("stat-pack template contains unresolved placeholders")
    return rendered


def _replace_file(source: Path, target: Path) -> None:
    os.replace(source, target)


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
        _replace_file(temporary_path, final_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def render_stat_pack(processed_root: str | Path, *, cfg: object) -> Path:
    """Render a standalone 17x11 HTML insert from validated supplied outputs."""

    root = Path(processed_root).expanduser().resolve()
    frames, manifest, _payload = _load_inputs(root, cfg)
    template = (TEMPLATE_ROOT / "playoff_stat_pack_insert.html").read_text(
        encoding="utf-8"
    )
    css = (TEMPLATE_ROOT / "playoff_stat_pack_insert.css").read_text(
        encoding="utf-8"
    )
    rendered = _build_stat_pack(frames, manifest, cfg, template, css)
    output_root = Path(cfg.output_root).expanduser()
    if not output_root.is_absolute():
        raise ValueError("configured output_root must be absolute before rendering")
    final_path = (
        output_root
        / "deliverables"
        / f"season={cfg.season}"
        / "latest"
        / STAT_PACK_FILENAME
    )
    _atomic_write(rendered, final_path)
    return final_path


__all__ = ["STAT_PACK_FILENAME", "render_stat_pack"]
