"""Inputs for the WNBA 2026 injury / availability report.

Two sources, both already in the repo:

* the raw ESPN injury feed (``data/raw/injuries/injuries_2026.parquet``) -- one row per
  (injury, snapshot date), keyed on ESPN ``athlete_id``;
* the reviewed identity crosswalk the role-fulfillment matrix maintains
  (``analysis/role_fulfillment_matrix/config/player_eligibility_2026.csv``) -- the bridge from
  ESPN ``athlete_id`` to the pbpstats ``player_id`` every other analysis runs on.

The crosswalk is optional: without it the report still builds and simply leaves ``player_id``
unresolved, so the availability view never becomes a hard dependency of a downstream run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


SEASON = 2026


@dataclass
class LoadedSources:
    injuries: pd.DataFrame
    crosswalk: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_manifest: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def hash_config(config: Dict[str, Any]) -> str:
    business_config = {k: v for k, v in config.items() if k != "_config_path"}
    return hashlib.sha256(stable_json_dumps(business_config).encode("utf-8")).hexdigest()


def load_config(config_path: Path) -> Dict[str, Any]:
    with Path(config_path).open(encoding="utf-8") as f:
        config = json.load(f)
    config["_config_path"] = str(config_path)
    return config


def path_from_config(value: str | Path, root: Optional[Path] = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (root or repo_root()) / path


def apply_runtime_overrides(
    config: Dict[str, Any],
    *,
    injuries_path: Optional[str] = None,
    crosswalk_path: Optional[str] = None,
    output_root: Optional[str] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    if injuries_path:
        updated["injuries_path"] = injuries_path
    if crosswalk_path:
        updated["crosswalk_path"] = crosswalk_path
    if output_root:
        updated["output_root"] = output_root
    return updated


def resolve_output_root(config: Dict[str, Any]) -> Path:
    return path_from_config(config.get("output_root", "analysis/injuries"))


def ensure_output_dirs(output_root: Path) -> Dict[str, Path]:
    paths = {"processed": output_root / "data" / "processed"}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _file_record(path: Optional[Path], df: pd.DataFrame) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "path": str(path) if path else None,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "status": "resolved" if path is not None else "missing",
    }
    if path and path.exists():
        stat = path.stat()
        record["modified_at_utc"] = (
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat()
        )
        record["size_bytes"] = stat.st_size
    return record


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def load_sources(config: Dict[str, Any]) -> LoadedSources:
    injuries_path = path_from_config(config.get("injuries_path", "data/raw/injuries/injuries_2026.parquet"))
    crosswalk_path = path_from_config(
        config.get("crosswalk_path", "analysis/role_fulfillment_matrix/config/player_eligibility_2026.csv")
    )

    manifest: Dict[str, Dict[str, Any]] = {}
    injuries = _read(injuries_path)
    manifest["injuries"] = _file_record(injuries_path if injuries_path.exists() else None, injuries)
    crosswalk = _read(crosswalk_path)
    manifest["crosswalk"] = _file_record(crosswalk_path if crosswalk_path.exists() else None, crosswalk)

    return LoadedSources(injuries=injuries, crosswalk=crosswalk, source_manifest=manifest)


def write_github_step_summary(markdown: str) -> None:
    import os

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")
