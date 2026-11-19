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

from nhl_injuries import dfo, enrich, nhlcom, store  # noqa: E402
from nhl_injuries.reference import CATEGORY_ORDER, ET, POSITION_GROUP, TEAMS  # noqa: E402
from nhl_injuries.tracker import INJURY_COLUMNS  # noqa: E402

GITHUB_REPO = "ajpayzant/NHL-Injury-Tool"
RAW_CSV_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/data/injuries.csv"
RAW_NEWS_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/data/news.csv"

# Column order and labels for tables and downloads.
DISPLAY = {
    "player": "Player", "position": "Pos", "age": "Age", "latest_team": "Team",
    "team": "Team When Injured", "injury_type": "Injury", "category": "Body Region",
    "status": "Latest Status", "status_category": "Status", "first_seen": "First Reported",
    "last_seen": "Last On Report", "return_date": "Off Report", "duration": "Days Missed",
    "games_missed": "Games Missed", "first_game_back": "First Game Back",
    "return_check": "Return Check", "reinjury_match": "Re-injury",
    "expected_return": "Expected Back", "season": "Season", "on_ir": "IR", "notes": "Notes",
    "latest_news": "Latest News", "latest_news_at": "News Date",
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
    "notes": "Notes", "latest_news": "Latest News", "latest_news_at": "Latest News Date",
}
NEWS_DOWNLOAD = {
    "news_id": "News ID", "published_at": "Published (ET)", "date": "Date", "player": "Player",
    "nhl_id": "NHL Player ID", "position": "Position", "team_shown": "Team", "headline": "Headline",
    "context": "Background", "news_status": "News Status", "injury": "Injury", "category": "Body Region",
    "surgery": "Surgery", "timeline": "Timeline", "return_earliest": "Timeline Earliest Return",
    "return_latest": "Timeline Latest Return", "injury_id": "CBS Injury ID", "source_name": "Reporter",
    "source_url": "Source Link", "source": "Source",
}
# Badge colour per news status: bad news, uncertain, good news.
DATE_COLUMNS = ("first_seen", "last_seen", "return_date", "expected_return", "first_game_back", "latest_news_at")
RETURN_CHECK_HELP = (
    "Checked against NHL box scores. Played: has dressed for a game since coming off the report. "
    "Awaiting first game: his team hasn't played since. Not played since: off the report but has "
    "missed every game since. Playing while listed: still on the report but dressed for the "
    "latest game.")
REINJURY_HELP = (f"Hurt again in the same body region within {enrich.REINJURY_DAYS} days of "
                 "returning from the previous injury.")


def _mtimes() -> tuple:
    """Cache key for every loader: changes whenever the Action's commit lands on disk."""
    return tuple(p.stat().st_mtime if p.exists() else 0
                 for p in (store.INJURIES, store.EVENTS, store.RUNS, store.GAMES, store.NEWS))


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
def _load(key: tuple) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inj = pd.read_csv(store.INJURIES, dtype=str, keep_default_na=False)
    for c in INJURY_COLUMNS:  # files written before a column existed
        if c not in inj:
            inj[c] = ""
    for c in (*DATE_COLUMNS[:-1], "source_updated", "birth_date"):  # latest_news_at comes later
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

    # The most recent news headline (Daily Faceoff or NHL.com) about each injury.
    n = _read_news()
    latest = (n[n["injury_id"] != ""].sort_values("published_at").groupby("injury_id").tail(1)
              .set_index("injury_id"))
    inj["latest_news"] = inj["injury_id"].map(latest["headline"]).fillna("")
    inj["latest_news_at"] = pd.to_datetime(inj["injury_id"].map(latest["date"]), errors="coerce")

    ev = _read_events()
    ev["date"] = pd.to_datetime(ev["date"], errors="coerce")
    runs = pd.read_csv(store.RUNS, dtype=str, keep_default_na=False) if store.RUNS.exists() \
        else pd.DataFrame(columns=["run_at", "run_date", "rows", "new", "updated", "closed", "reopened"])
    runs["run_at"] = pd.to_datetime(runs["run_at"], utc=True, errors="coerce")
    return inj, ev, runs


def _read_news() -> pd.DataFrame:
    if store.NEWS.exists():
        n = pd.read_csv(store.NEWS, dtype=str, keep_default_na=False)
    else:
        n = pd.DataFrame(columns=dfo.NEWS_COLUMNS)
    for c in dfo.NEWS_COLUMNS:
        if c not in n:
            n[c] = ""
    return n


@st.cache_data(show_spinner=False)
def _news(key: tuple) -> pd.DataFrame:
    n = _read_news()
    for c in ("published_at", "scraped_at"):
        n[c] = pd.to_datetime(n[c], utc=True, errors="coerce").dt.tz_convert(ET)
    for c in ("date", "return_earliest", "return_latest"):
        n[c] = pd.to_datetime(n[c], errors="coerce")
    for c in store.NEWS_BOOL_COLUMNS:
        n[c] = n[c].str.lower().eq("true")
    inj = pd.read_csv(store.INJURIES, dtype=str, keep_default_na=False, usecols=["injury_id", "team"])         if store.INJURIES.exists() else pd.DataFrame(columns=["injury_id", "team"])
    # Daily Faceoff's team is the player's team when the item was scraped. For items
    # backfilled long after they were posted, the CBS injury knows the team at the time.
    cbs_team = n["injury_id"].map(inj.set_index("injury_id")["team"]).fillna("")
    timely = ~n["team_is_current"] | (n["scraped_at"] - n["published_at"] <= pd.Timedelta(days=2))
    n["team_shown"] = n["team"].where(timely | cbs_team.eq(""), cbs_team)
    n["pkey"] = n["nhl_id"].where(n["nhl_id"] != "", "dfo:" + n["dfo_player_id"])
    n["tone"] = n["news_status"].map(dfo.TONE).fillna("")
    n["source"] = n["news_id"].str.startswith(nhlcom.ID_PREFIX).map({True: "NHL.com", False: "Daily Faceoff"})
    # NHL.com often carries a note into the next day's report word for word; ``repeat_of``
    # is the date that player's same note first appeared (NaT if it's new).
    # Compared without punctuation or case: a re-run note can swap curly quotes for straight.
    said = n["headline"].str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()
    nhl = n["source"] == "NHL.com"
    first = (n[nhl].assign(said=said[nhl]).sort_values("published_at")
             .groupby(["pkey", "said"])["date"].transform("first").reindex(n.index))
    n["repeat_of"] = first.where(first < n["date"])
    # A Status Report's items share one time: keep them grouped by team, a shared
    # note's players together.
    return n.sort_values(["published_at", "team_shown", "headline", "player"],
                         ascending=[False, True, True, True], kind="stable").reset_index(drop=True)


def news() -> pd.DataFrame:
    """Injury news (Daily Faceoff items and NHL.com Status Report notes), newest first,
    with the player key, team to show, ``source`` and ``repeat_of``."""
    return _news(_mtimes())


def drop_repeats(n: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """Without NHL.com notes repeated from a report on or after ``since`` (the
    earlier copy is already in the window)."""
    return n[~(n["repeat_of"] >= since)]


def news_time(ts) -> str:
    """'4:22 PM' (ET), no zero padding on any platform."""
    return "" if pd.isna(ts) else f"{ts.hour % 12 or 12}:{ts:%M} {'AM' if ts.hour < 12 else 'PM'}"


# How serious each news status is, for "better / worse" and source cross-checks.
# "Other" (call-ups, lineup notes) has no rank and is left out of comparisons.
SEVERITY = {"Returning": 0, "Activated": 0, "Practicing": 1, "Day-to-day": 2, "Game-time decision": 2,
            "Being evaluated": 2, "Left game": 3, "Out": 3, "Week-to-week": 4, "IR": 5, "Month-to-month": 5,
            "Out indefinitely": 6, "Injured non-roster": 6, "LTIR": 6, "Out for season": 7}
LOOKBACK = pd.Timedelta(days=45)  # how far back an earlier status still counts as "was"


def status_changes(n: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """Players whose news status moved in the window: the status before the window
    (else his first item in it) against his latest item in it, one row per player,
    with ``direction`` Better / Worse / Changed."""
    rated = n[n["news_status"].isin(list(SEVERITY))].sort_values("published_at")
    recent = rated[rated["date"] >= since]
    if recent.empty:
        return recent.assign(was_status="", was_date=pd.NaT, was_headline="", direction="", updates=0)
    now = recent.groupby("pkey").tail(1).set_index("pkey")
    before = rated[(rated["date"] < since) & (rated["date"] >= since - LOOKBACK)].groupby("pkey").tail(1)
    first_in = recent.groupby("pkey").head(1)
    was = pd.concat([before, first_in[~first_in["pkey"].isin(before["pkey"])]]).set_index("pkey")
    out = now.join(was[["news_status", "date", "headline", "news_id"]].add_prefix("was_"), how="inner")
    back = ["Returning", "Activated"]  # "activated" then "will return": the same news
    out = out[(out["was_news_status"] != out["news_status"]) & (out["was_news_id"] != out["news_id"])
              & ~(out["was_news_status"].isin(back) & out["news_status"].isin(back))]
    out["updates"] = recent.groupby("pkey").size().reindex(out.index)
    delta = out["news_status"].map(SEVERITY) - out["was_news_status"].map(SEVERITY)
    out["direction"] = ["Better" if d < 0 else "Worse" if d > 0 else "Changed" for d in delta]
    return (out.rename(columns={"was_news_status": "was_status"}).reset_index()
            .sort_values("published_at", ascending=False))


def reports(n: pd.DataFrame) -> pd.DataFrame:
    """One row per NHL.com Status Report, newest first: url, date, published, notes, teams."""
    c = n[n["source"] == "NHL.com"]
    out = c.groupby("source_url").agg(date=("date", "min"), published=("published_at", "min"),
                                      updated=("updated_at", "max"), notes=("news_id", "size"),
                                      teams=("team_shown", "nunique")).reset_index()
    return out.sort_values("published", ascending=False).reset_index(drop=True)


def report_diff(n: pd.DataFrame, url: str) -> dict[str, pd.DataFrame]:
    """What one Status Report changed against the report before it:
    ``new`` (players not in the previous report), ``changed`` (in both, status moved,
    with ``was_status``), ``carried`` (in both, same status), ``dropped`` (in the
    previous report, not this one; their rows from the previous report), and ``prev``,
    the previous report's url ("" if none)."""
    reps = reports(n)
    c = n[n["source"] == "NHL.com"]
    cur = c[c["source_url"] == url]
    later = reps.loc[reps["source_url"] == url, "published"]
    older = reps[reps["published"] < later.iloc[0]] if len(later) else reps.iloc[0:0]
    prev_url = older.iloc[0]["source_url"] if len(older) else ""
    prev = c[c["source_url"] == prev_url]
    was = prev.drop_duplicates("pkey").set_index("pkey")["news_status"]
    in_prev = cur["pkey"].isin(was.index)
    both = cur[in_prev].assign(was_status=cur.loc[in_prev, "pkey"].map(was))
    moved = both["was_status"] != both["news_status"]
    return {"new": cur[~in_prev] if prev_url else cur.iloc[0:0], "changed": both[moved],
            "carried": both[~moved], "dropped": prev[~prev["pkey"].isin(cur["pkey"])], "prev": prev_url}


def cross_check(inj: pd.DataFrame, n: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """Players whose sources disagree, from news in the window: one row per player and
    issue, with the CBS status and each news source's latest status.

    - **News says back, CBS still lists him**: latest news is Returning or Activated,
      but he has an open CBS injury.
    - **News more serious than CBS**: CBS has him day-to-day (not on IR), the latest
      news says week-to-week, IR or longer.
    - **CBS more serious than news**: CBS has him out for the season or on IR, the
      latest news says day-to-day or a game-time decision.
    - **Daily Faceoff and NHL.com differ**: each has an item within 36 hours of the
      other, one good news and the other bad.
    - **Not on CBS report**: latest news is bad or uncertain, no open CBS injury."""
    rated = n[(n["date"] >= since) & n["news_status"].isin(list(SEVERITY))].sort_values("published_at")
    cols = ["pkey", "player", "team_shown", "position", "issue", "cbs", "dfo", "nhl", "headline", "source",
            "published_at", "date"]
    if rated.empty:
        return pd.DataFrame(columns=cols)
    latest = rated.groupby("pkey").tail(1).set_index("pkey")
    by_src = {s: rated[rated["source"] == s].groupby("pkey").tail(1).set_index("pkey")
              for s in ("Daily Faceoff", "NHL.com")}
    open_now = inj[inj["is_open"]].sort_values("first_seen").groupby("pkey").tail(1).set_index("pkey")
    sev = latest["news_status"].map(SEVERITY)
    listed = latest.index.isin(open_now.index)
    cbs_cat = latest.index.map(open_now["status_category"]).astype(object)
    cbs_ir = latest.index.map(open_now["on_ir"]).astype(object)
    issues = {
        "News says back, CBS still lists him": listed & latest["news_status"].isin(["Returning", "Activated"]),
        "News more serious than CBS": listed & (cbs_cat == "Day-to-day") & (cbs_ir != True) & (sev >= 4),  # noqa: E712
        "CBS more serious than news": listed & ((cbs_cat == "Out for season") | (cbs_ir == True)) & (sev == 2),  # noqa: E712
        "Not on CBS report": ~listed & latest["tone"].isin(["bad", "warn"]),
    }
    d, h = by_src["Daily Faceoff"], by_src["NHL.com"]
    both = d.index.intersection(h.index)
    gap = (d.loc[both, "published_at"] - h.loc[both, "published_at"]).abs() <= pd.Timedelta(hours=36)
    differ = [k for k in both[gap.values] if {d.at[k, "tone"], h.at[k, "tone"]} == {"good", "bad"}]
    issues["Daily Faceoff and NHL.com differ"] = latest.index.isin(differ)

    def said(src: pd.DataFrame, k: str) -> str:
        return f"{src.at[k, 'news_status']} ({fmt_date(src.at[k, 'date'], year=False)})" if k in src.index else ""

    rows = []
    for issue, mask in issues.items():
        for k in latest.index[mask]:
            r = latest.loc[k]
            cbs = "Not listed"
            if k in open_now.index:  # "IR · back ~Nov 21", not CBS's full sentence
                o = open_now.loc[k]
                cbs = "IR" if bool(o["on_ir"]) else str(o["status_category"])
                if pd.notna(o.get("expected_return", pd.NaT)):
                    cbs += f" · back ~{fmt_date(o['expected_return'], year=False)}"
            rows.append({"pkey": k, "player": r["player"], "team_shown": r["team_shown"], "position": r["position"],
                         "issue": issue, "cbs": cbs, "dfo": said(d, k), "nhl": said(h, k), "headline": r["headline"],
                         "source": r["source"], "published_at": r["published_at"], "date": r["date"]})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("published_at", ascending=False).reset_index(drop=True)


def not_on_report(inj: pd.DataFrame, n: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    """Players the news reported hurt since ``since`` who have no open CBS injury:
    the latest bad or uncertain item per player."""
    recent = n[(n["date"] >= since) & n["tone"].isin(["bad", "warn"])]
    listed = set(inj.loc[inj["is_open"], "pkey"])
    latest = n.sort_values("published_at").groupby("pkey").tail(1)
    # Only if his latest item is still bad news (not "will return Saturday").
    still = set(latest.loc[latest["tone"].isin(["bad", "warn"]), "news_id"])
    out = recent[~recent["pkey"].isin(listed) & recent["news_id"].isin(still)]
    return out.drop_duplicates("pkey")


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Injuries, events and runs. Reloads whenever the scheduled job rewrites a file."""
    return _load(_mtimes())


@st.cache_data(show_spinner=False)
def _history(key: tuple) -> pd.DataFrame:
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
def _games(key: tuple) -> pd.DataFrame:
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


def data_version() -> tuple:
    """Changes when new data arrives, so open sessions can tell they're out of date."""
    return _mtimes()


def updated_ago(runs: pd.DataFrame) -> str:
    """'4 min ago' / '2 hr ago' since the latest scrape, or '' if there's none."""
    if runs.empty or runs["run_at"].isna().all():
        return ""
    mins = int((pd.Timestamp.now(tz="UTC") - runs["run_at"].max()).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    return f"{mins // 60} hr ago" if mins < 48 * 60 else f"{mins // 1440} days ago"


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


def news_for_download(n: pd.DataFrame) -> pd.DataFrame:
    out = n[list(NEWS_DOWNLOAD)].copy()
    out["published_at"] = out["published_at"].dt.strftime("%Y-%m-%d %H:%M")
    for c in ("date", "return_earliest", "return_latest"):
        out[c] = out[c].dt.strftime("%Y-%m-%d").fillna("")
    return out.rename(columns=NEWS_DOWNLOAD)


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
