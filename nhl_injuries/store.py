"""CSV storage under ``data/``. CSV rather than parquet so every scrape is a
readable git diff and the files open directly in Excel or Google Sheets."""
from __future__ import annotations

import csv
from pathlib import Path

from .nhl import APPEARANCE_COLUMNS, GAME_COLUMNS, PLAYER_COLUMNS
from .scrape import ReportRow
from .tracker import EVENT_COLUMNS, INJURY_COLUMNS, RUN_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INJURIES = DATA / "injuries.csv"
RUNS = DATA / "runs.csv"
EVENTS = DATA / "events.csv"
SNAPSHOTS = DATA / "snapshots"
NHL = DATA / "nhl"
PLAYERS = NHL / "players.csv"
GAMES = NHL / "games.csv"
APPEARANCES = NHL / "appearances"      # one file per season: 20262027.csv

BOOL_COLUMNS = ["on_ir", "start_is_lower_bound", "return_is_estimated"]


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _to_bool(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def read_injuries(path: Path = INJURIES) -> list[dict]:
    rows = _read(path)
    for r in rows:
        for c in BOOL_COLUMNS:
            r[c] = _to_bool(r.get(c, ""))
    return rows


def write_injuries(rows: list[dict], path: Path = INJURIES) -> None:
    _write(path, rows, INJURY_COLUMNS)


def read_runs(path: Path = RUNS) -> list[dict]:
    return _read(path)


def append_run(run: dict, path: Path = RUNS) -> None:
    _write(path, read_runs(path) + [run], RUN_COLUMNS)


def read_events(path: Path = EVENTS) -> list[dict]:
    return _read(path)


def append_events(events: list[dict], path: Path = EVENTS) -> None:
    if events or not path.exists():
        _write(path, read_events(path) + events, EVENT_COLUMNS)


def write_snapshot(report: list[ReportRow], run_at: str, root: Path = SNAPSHOTS) -> Path:
    """Raw copy of each scrape, so the episode log can always be rebuilt from source."""
    stamp = run_at.replace(":", "").replace("-", "")[:13]  # 20260924T1600
    path = root / run_at[:4] / f"{stamp}Z.csv"
    _write(path, [r.as_dict() for r in report], list(ReportRow.__dataclass_fields__))
    return path


# ---------------------------------------------------------------- NHL.com cache

def read_players(path: Path = PLAYERS) -> list[dict]:
    return _read(path)


def write_players(rows: list[dict], path: Path = PLAYERS) -> None:
    _write(path, rows, PLAYER_COLUMNS)


def read_games(path: Path = GAMES) -> list[dict]:
    return _read(path)


def write_games(rows: list[dict], path: Path = GAMES) -> None:
    _write(path, rows, GAME_COLUMNS)


def read_appearances(root: Path = APPEARANCES) -> list[dict]:
    return [r for p in sorted(root.glob("*.csv")) for r in _read(p)] if root.exists() else []


def write_appearances(rows: list[dict], games: list[dict], root: Path = APPEARANCES) -> None:
    season = {g["game_id"]: g["season"] for g in games}
    by_season: dict[str, list[dict]] = {}
    for r in rows:
        by_season.setdefault(season.get(r["game_id"], r["game_id"][:4] + str(int(r["game_id"][:4]) + 1)),
                             []).append(r)
    for sid, rs in by_season.items():
        _write(root / f"{sid}.csv", sorted(rs, key=lambda r: (r["date"], r["game_id"], r["team"], r["nhl_id"])),
               APPEARANCE_COLUMNS)
