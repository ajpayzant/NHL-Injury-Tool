"""Cached data loading and the display vocabulary shared by every page."""
from __future__ import annotations

import io
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nhl_injuries import enrich, store  # noqa: E402
from nhl_injuries.reference import CATEGORY_ORDER, ET, POSITION_GROUP, TEAMS  # noqa: E402
from nhl_injuries.tracker import INJURY_COLUMNS  # noqa: E402

GITHUB_REPO = "ajpayzant/NHL-Injury-Tool"
RAW_CSV_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/data/injuries.csv"

# Column order and labels for tables and downloads.
DISPLAY = {
    "player": "Player", "position": "Pos", "age": "Age", "latest_team": "Team",
    "team": "Team When Injured", "injury_type": "Injury", "category": "Body Region",
    "status": "Latest Status", "status_category": "Status", "first_seen": "First Reported",
    "last_seen": "Last On Report", "return_date": "Off Report", "duration": "Days Missed",
    "games_missed": "Games Missed", "first_game_back": "First Game Back",
    "return_check": "Return Check", "reinjury_match": "Re-injury",
    "expected_return": "Expected Back", "season": "Season", "on_ir": "IR", "notes": "Notes",
}
DOWNLOAD = {
    "injury_id": "Injury ID", "player_id": "CBS Player ID", "nhl_id": "NHL Player ID",
    "player": "Player", "position": "Position", "birth_date": "Birth Date",
    "team": "Team When Injured", "latest_team": "Latest Team",
    "injury_type": "Injury Type", "category": "Body Region", "status": "Latest Status",
    "status_category": "Status Category", "on_ir": "On IR", "expected_return": "Expected Return",
    "first_seen": "First Reported", "last_seen": "Last On Report", "return_date": "Date of Return",
    "days_out": "Days Missed", "games_missed": "Games Missed", "first_game_back": "First Game Back",
    "return_check": "Return Check", "reinjury_match": "Re-injury", "reinjury_of": "Re-injury Of",
    "days_since_prior": "Days Since Prior Injury", "season": "Season",
    "start_is_lower_bound": "Start Is Lower Bound", "return_is_estimated": "Return Estimated",
    "notes": "Notes",
}
DATE_COLUMNS = ("first_seen", "last_seen", "return_date", "expected_return", "first_game_back")
RETURN_CHECK_HELP = (
    "Checked against NHL box scores. Played: has dressed for a game since coming off the report. "
    "Awaiting first game: his team hasn't played since. Not played since: off the report but has "
    "missed every game since. Playing while listed: still on the report but dressed for the "
    "latest game.")
REINJURY_HELP = (f"Hurt again in the same body region within {enrich.REINJURY_DAYS} days of "
                 "returning from the previous injury.")


def _mtimes() -> tuple:
    return tuple(p.stat().st_mtime if p.exists() else 0
                 for p in (store.INJURIES, store.EVENTS, store.RUNS, store.GAMES))


def _read_events() -> pd.DataFrame:
    if store.EVENTS.exists():
        return pd.read_csv(store.EVENTS, dtype=str, keep_default_na=False)
    return pd.DataFrame(columns=["at", "date", "injury_id", "player_id", "player", "team", "event", "detail"])


def _years(born: pd.Series, on: pd.Series) -> pd.Series:
    """Whole years from ``born`` to ``on`` (an age); missing where either is unknown."""
    years = on.dt.year - born.dt.year
    early = (on.dt.month < born.dt.month) | ((on.dt.month == born.dt.month) & (on.dt.day < born.dt.day))
    return (years - early.astype(int)).astype("Int64")


@st.cache_data(show_spinner=False)
def _load(_key: tuple) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inj = pd.read_csv(store.INJURIES, dtype=str, keep_default_na=False)
    for c in INJURY_COLUMNS:  # files written before a column existed
        if c not in inj:
            inj[c] = ""
    for c in (*DATE_COLUMNS, "source_updated", "birth_date"):
        inj[c] = pd.to_datetime(inj[c], errors="coerce")
    for c in ("on_ir", "start_is_lower_bound", "return_is_estimated"):
        inj[c] = inj[c].str.lower().eq("true")
    for c in ("days_out", "games_missed", "days_since_prior"):
        inj[c] = pd.to_numeric(inj[c], errors="coerce")

    today = pd.Timestamp(datetime.now(ET).date())
    inj["is_open"] = inj["return_date"].isna()
    inj["duration"] = inj["days_out"].where(~inj["is_open"], (today - inj["first_seen"]).dt.days)
    inj["team_name"] = inj["latest_team"].map(lambda t: TEAMS.get(t, (t,))[0])
    inj["position_group"] = inj["position"].map(POSITION_GROUP).fillna("Other")
    inj["is_injury"] = inj["category"].ne("Non-injury")
    inj["is_reinjury"] = inj["reinjury_match"].ne("")
    inj["category"] = pd.Categorical(inj["category"], categories=CATEGORY_ORDER, ordered=True)
    inj["age"] = _years(inj["birth_date"], pd.Series(today, index=inj.index))
    inj["age_at_injury"] = _years(inj["birth_date"], inj["first_seen"])
    # One key per person: NHL id, else CBS id, else the name (a few old imported rows).
    inj["pkey"] = inj["nhl_id"].where(
        inj["nhl_id"] != "", inj["player_id"].where(inj["player_id"] != "", "name:" + inj["player"]))

    ev = _read_events()
    ev["date"] = pd.to_datetime(ev["date"], errors="coerce")
    runs = pd.read_csv(store.RUNS, dtype=str, keep_default_na=False) if store.RUNS.exists() \
        else pd.DataFrame(columns=["run_at", "run_date", "rows", "new", "updated", "closed", "reopened"])
    runs["run_at"] = pd.to_datetime(runs["run_at"], utc=True, errors="coerce")
    return inj, ev, runs


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Injuries, events and runs. Reloads whenever the scheduled job rewrites a file."""
    return _load(_mtimes())


@st.cache_data(show_spinner=False)
def _history(_key: tuple) -> pd.DataFrame:
    rows = enrich.expected_return_history(
        pd.read_csv(store.INJURIES, dtype=str, keep_default_na=False).to_dict("records"),
        _read_events().to_dict("records"))
    hist = pd.DataFrame(rows, columns=["injury_id", "date", "status", "status_category", "on_ir",
                                       "expected_return", "date_known", "change"])
    hist["date"] = pd.to_datetime(hist["date"])
    hist["expected_return"] = pd.to_datetime(hist["expected_return"], errors="coerce")
    return hist


def history() -> pd.DataFrame:
    """Every status each injury has had, the return date it implied, and how that moved."""
    return _history(_mtimes())


@st.cache_data(show_spinner=False)
def _games(_key: tuple) -> pd.DataFrame:
    if not store.GAMES.exists():
        return pd.DataFrame(columns=["game_id", "season", "game_type", "date", "away", "home", "state"])
    g = pd.read_csv(store.GAMES, dtype=str, keep_default_na=False)
    g["date"] = pd.to_datetime(g["date"])
    return g


def games() -> pd.DataFrame:
    """NHL regular-season and playoff schedule for the tracked seasons."""
    return _games(_mtimes())


def today() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(ET).date())


def last_updated(runs: pd.DataFrame) -> str:
    if runs.empty or runs["run_at"].isna().all():
        return "never"
    t = runs["run_at"].max().tz_convert(ET)
    return t.strftime("%b %-d, %Y at %-I:%M %p ET") if sys.platform != "win32" \
        else t.strftime("%b %#d, %Y at %#I:%M %p ET")


def fmt_date(d, year: bool = True) -> str:
    """Sep 4, 2026 (no zero padding on any platform)."""
    if pd.isna(d):
        return ""
    return f"{d:%b} {d.day}, {d.year}" if year else f"{d:%b} {d.day}"


def tracking_changes_since(events: pd.DataFrame) -> str:
    """First day the pipeline logged report changes (earlier rows came from the Sheet)."""
    return fmt_date(events["date"].min()) if len(events) else "the first scrape"


def seasons(inj: pd.DataFrame) -> list[str]:
    return sorted(inj["season"].unique(), reverse=True)


def team_label(code: str) -> str:
    return f"{TEAMS[code][0]} ({code})" if code in TEAMS else code


def player_link(player: str, pkey: str) -> str:
    """Relative link to a player's page. The name comes first so the column sorts by it."""
    return f"players?name={quote(player)}&player={quote(pkey, safe='')}"


def display_table(df: pd.DataFrame, cols: list[str], **kwargs) -> None:
    """A read-only injury table with consistent labels and formats. Player and team
    cells link to their pages."""
    out = df[cols].copy()
    config = {DISPLAY[c]: st.column_config.DateColumn(DISPLAY[c], format="MMM D, YYYY")
              for c in cols if c in DATE_COLUMNS}
    if "player" in cols and "pkey" in df:
        out["player"] = [player_link(p, k) for p, k in zip(df["player"], df["pkey"])]
        config["Player"] = st.column_config.LinkColumn("Player", display_text=r"name=(.*?)&player=")
    for c in ("latest_team", "team"):
        if c in cols:
            out[c] = "teams?team=" + df[c]
            config[DISPLAY[c]] = st.column_config.LinkColumn(DISPLAY[c], display_text=r"team=(\w+)$")
    if "duration" in cols:
        config["Days Missed"] = st.column_config.NumberColumn(
            "Days Missed", help="Days on the injury report: first report to coming off it, or so far "
                                "if still listed.")
    if "games_missed" in cols:
        config["Games Missed"] = st.column_config.NumberColumn(
            "Games Missed", help="Regular-season and playoff games his team played without him, "
                                 "until he actually dressed again (NHL box scores).")
    if "return_check" in cols:
        config["Return Check"] = st.column_config.TextColumn("Return Check", help=RETURN_CHECK_HELP)
    if "reinjury_match" in cols:
        config["Re-injury"] = st.column_config.TextColumn("Re-injury", help=REINJURY_HELP)
    if "on_ir" in cols:
        config["IR"] = st.column_config.CheckboxColumn("IR")
    kwargs.setdefault("placeholder", "—")
    st.dataframe(out.rename(columns=DISPLAY), hide_index=True, width="stretch",
                 column_config=config, **kwargs)


def for_download(df: pd.DataFrame) -> pd.DataFrame:
    out = df[list(DOWNLOAD)].copy()
    for c in (*DATE_COLUMNS, "birth_date"):
        out[c] = out[c].dt.strftime("%Y-%m-%d").fillna("")
    out["category"] = out["category"].astype(str)
    return out.rename(columns=DOWNLOAD)


def history_for_download(hist: pd.DataFrame, inj: pd.DataFrame) -> pd.DataFrame:
    out = hist.merge(inj[["injury_id", "player", "latest_team", "injury_type"]], on="injury_id", how="left")
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out["expected_return"] = out["expected_return"].dt.strftime("%Y-%m-%d").fillna("")
    return out[["injury_id", "player", "latest_team", "injury_type", "date", "status",
                "status_category", "on_ir", "expected_return", "change", "date_known"]].rename(columns={
        "injury_id": "Injury ID", "player": "Player", "latest_team": "Team", "injury_type": "Injury Type",
        "date": "Date", "status": "Status", "status_category": "Status Category", "on_ir": "On IR",
        "expected_return": "Expected Return", "change": "Change", "date_known": "Date Known"})


def to_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, 1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(500)]) + 2
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(width, 45)
    return buf.getvalue()


def download_buttons(df: pd.DataFrame, stem: str, key: str) -> None:
    data = for_download(df)
    c1, c2, _ = st.columns([1, 1, 4])
    c1.download_button("Download CSV", data.to_csv(index=False).encode("utf-8"),
                       f"{stem}.csv", "text/csv", key=f"{key}_csv", icon=":material/download:")
    c2.download_button("Download Excel", to_excel({"Injuries": data}), f"{stem}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"{key}_xlsx", icon=":material/table_view:")


def avg_days_out(df: pd.DataFrame) -> tuple[float | None, int]:
    """Mean days out over returned injuries whose start date is real (not the day
    tracking began) and that are actual injuries. Returns (mean, sample size)."""
    base = df[~df["is_open"] & ~df["start_is_lower_bound"] & df["is_injury"]]
    return (float(base["days_out"].mean()) if len(base) else None), len(base)


def avg_games_missed(df: pd.DataFrame) -> tuple[float | None, int]:
    """Mean games missed over injuries where he has since played (so the count is
    final), with a real start date, that are actual injuries."""
    base = df[df["return_check"].eq("Played") & ~df["start_is_lower_bound"] & df["is_injury"]]
    return (float(base["games_missed"].mean()) if len(base) else None), len(base)


def games_lost(df: pd.DataFrame) -> int:
    """Total games missed so far, open injuries included."""
    return int(df["games_missed"].fillna(0).sum())
