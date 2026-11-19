"""What's new, one tab per source: all injury news together, Daily Faceoff (who changed
status), the NHL.com Status Report (each report against the one before), the CBS report's
changes (injuries just announced, return dates that moved, players back or due back) and a
cross-check of where the three disagree."""
from html import escape

import pandas as pd
import streamlit as st

from core import (cross_check, drop_repeats, fmt_date, history, last_updated, load, news, news_time,
                  not_on_report, player_link, report_diff, reports, status_changes, team_label, today,
                  tracking_changes_since)
from nhl_injuries.reference import TEAMS

inj, events, runs = load()
feed = news()
now = today()

st.title("Latest Injury News")
st.caption(f"Updated {last_updated(runs)}.")

WINDOWS = {"Last 2 days": 2, "Last 3 days": 3, "Last 7 days": 7, "Last 14 days": 14}
c = st.columns([3, 2])
window = c[0].segmented_control("Show", list(WINDOWS), default="Last 3 days", key="news_window") or "Last 3 days"
team_f = c[1].multiselect("Team", list(TEAMS), format_func=team_label, placeholder="All teams")
since = now - pd.Timedelta(days=WINDOWS[window] - 1)  # today counts as one of the days

all_inj, all_feed = inj, feed
if team_f:
    inj = inj[inj["latest_team"].isin(team_f) | inj["team"].isin(team_f)]
    feed = feed[feed["team_shown"].isin(team_f) | feed["team"].isin(team_f)]


def for_teams(df: pd.DataFrame, col: str = "team_shown") -> pd.DataFrame:
    return df[df[col].isin(team_f)] if team_f else df


recent_news = drop_repeats(feed[feed["date"] >= since], since)
dfo_news = recent_news[recent_news["source"] == "Daily Faceoff"]
nhl_news = recent_news[recent_news["source"] == "NHL.com"]
missing = not_on_report(all_inj, feed, since)
# Status changes and cross-checks look at every source's full history, then the team filter.
changes = for_teams(status_changes(all_feed[all_feed["source"] == "Daily Faceoff"], since))
checks = for_teams(cross_check(all_inj, all_feed, since))
all_reports = reports(all_feed)
window_reports = all_reports[all_reports["date"] >= since]


new = inj[inj["first_seen"] >= since].sort_values(["first_seen", "latest_team", "player"],
                                                  ascending=[False, True, True])
# Came off the report, or played his first game back, in the window.
back = inj[(inj["return_date"] >= since) | (inj["first_game_back"] >= since)].copy()
back["back_on"] = back[["return_date", "first_game_back"]].max(axis=1)
back = back.sort_values("back_on", ascending=False)

hist = history().sort_values(["injury_id", "date"])
# The return date the previous status implied, for "was / now" comparisons.
hist["was"] = hist.groupby("injury_id")["expected_return"].transform(lambda s: s.ffill().shift())
moves = hist[hist["date_known"] & (hist["date"] >= since)
             & hist["change"].str.match(r"Pushed back|Moved up|Ruled out|Placed on IR")]
moves = moves.merge(inj, on="injury_id", suffixes=("", "_inj")).sort_values("date", ascending=False)

soon_by = now + pd.Timedelta(days=7)
open_now = inj[inj["is_open"]]
soon = open_now[open_now["expected_return"].between(now - pd.Timedelta(days=3), soon_by)
                | open_now["status_category"].isin(["Day-to-day", "Questionable", "Probable"])
                | open_now["return_check"].eq("Playing while listed")].copy()
soon["sort"] = soon["expected_return"].fillna(now)
soon = soon.sort_values(["sort", "latest_team"])


k = st.columns(5)
k[0].metric("Daily Faceoff items", len(dfo_news), border=True,
            help="Beat-reporter injury news on Daily Faceoff in this window.")
k[1].metric("NHL.com notes", len(nhl_news), border=True,
            help=f"Notes in {len(window_reports)} NHL.com Status Report(s) in this window, not counting notes "
                 "repeated word for word from an earlier report.")
k[2].metric("Status changes", len(changes), border=True,
            help="Players whose Daily Faceoff status moved in this window (e.g. Out to Returning).")
k[3].metric("New on CBS report", len(new), border=True, help="New on the CBS injury report.")
k[4].metric("Sources disagree", checks["pkey"].nunique(), border=True,
            help="Players where CBS, Daily Faceoff and NHL.com don't agree. See the Cross-check tab.")

st.html("""<style>
.news-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;margin:.25rem 0 1rem}
.news-card{border:1px solid #e8e7e3;border-radius:10px;padding:10px 12px;display:flex;gap:10px;background:#fff}
.news-card img{width:34px;height:34px;flex:none}
.news-card .nm{font-weight:600;font-size:.98rem}
.news-card .nm a{color:inherit;text-decoration:none}
.news-card .nm a:hover{text-decoration:underline}
.news-card .sub{color:#8a8984;font-size:.8rem}
.news-card .inj{margin-top:4px;font-size:.88rem}
.news-card .st{color:#52514e;font-size:.82rem}
.news-badge{display:inline-block;font-size:.72rem;font-weight:600;border-radius:4px;padding:1px 6px;margin:4px 4px 0 0;
  border:1px solid #c9c8c2;color:#52514e;background:#f7f6f3}
.news-badge.warn{border-color:#eda100;background:#fff6dd;color:#6b4a00}
.news-badge.bad{border-color:#d03b3b;background:#fdecec;color:#8a1f1f}
.news-day{font-weight:600;color:#52514e;margin:.6rem 0 .1rem}
.news-badge.src-nhl{border-color:#1f4e9c;background:#e8f0fc;color:#163a78}
.news-badge.good{border-color:#2e8b57;background:#e9f6ee;color:#1d5c39}
.news-card .dfo{margin-top:4px;color:#52514e;font-size:.8rem;font-style:italic}
.feed-item{display:flex;gap:12px;padding:10px 4px;border-bottom:1px solid #eeede9}
.feed-item .tm{flex:none;width:62px;color:#8a8984;font-size:.8rem;padding-top:3px}
.feed-item img{width:30px;height:30px;flex:none}
.feed-item .nm{font-weight:600}
.feed-item .nm a{color:inherit;text-decoration:none}
.feed-item .nm a:hover{text-decoration:underline}
.feed-item .nm .sub{color:#8a8984;font-weight:400;font-size:.8rem;margin-left:4px}
.feed-item .hl{margin-top:2px}
.feed-item .ctx{color:#6b6a66;font-size:.85rem;margin-top:3px}
.feed-item .src{color:#8a8984;font-size:.78rem;margin-top:4px}
.feed-item .src a{color:#8a8984}
</style>""")

st.html("""<style>
.team-head{display:flex;align-items:center;gap:8px;font-weight:600;color:#33322f;margin:1rem 0 .1rem;
  padding-bottom:4px;border-bottom:2px solid #e8e7e3}
.team-head img{width:26px;height:26px}
.team-head .ct{color:#8a8984;font-weight:400;font-size:.85rem}
.rep-meta{color:#52514e;font-size:.9rem;margin:.1rem 0 .6rem}
</style>""")


def n(k: int, word: str) -> str:
    return f"{k} {word}{'' if k == 1 else 's'}"


def card(r: pd.Series, lines: list[str], badges: list[tuple[str, str]]) -> str:
    team = r["latest_team"]
    logo = f"<img src='https://assets.nhle.com/logos/nhl/svg/{team}_light.svg' alt='{team}'/>" \
        if team in TEAMS else "<div style='width:34px'></div>"
    facts = [r["position"], f"{r['age']} yrs" if pd.notna(r["age"]) else "", TEAMS.get(team, (team,))[0]]
    tags = "".join(f"<span class='news-badge {cls}'>{escape(t)}</span>" for t, cls in badges)
    if r.get("latest_news"):
        lines = lines + [f"<div class='dfo'>“{escape(r['latest_news'])}” "
                         f"({fmt_date(r['latest_news_at'], year=False)})</div>"]
    body = "".join(lines)
    return (f"<div class='news-card'>{logo}<div><div class='nm'>"
            f"<a href='{player_link(r['player'], r['pkey'])}' target='_self'>{escape(r['player'])}</a></div>"
            f"<div class='sub'>{escape(' · '.join(f for f in facts if f))}</div>{body}"
            f"{'<div>' + tags + '</div>' if tags else ''}</div></div>")


def flags(r: pd.Series) -> list[tuple[str, str]]:
    out = []
    if r["status_category"] == "Out for season":
        out.append(("Out for season", "bad"))
    elif r["on_ir"]:
        out.append(("IR", "warn"))
    if r["is_reinjury"]:
        out.append((f"Re-injury · {int(r['days_since_prior'])}d after return", "bad"))
    return out


cbs_status = all_inj.set_index("injury_id")["status"]


def badge(text: str, cls: str = "") -> str:
    return f"<span class='news-badge {cls}'>{escape(text)}</span>"


def timeline_text(r: pd.Series) -> str:
    if not r["timeline"]:
        return ""
    if pd.notna(r["return_latest"]) and r["return_latest"] != r["return_earliest"]:
        when = f"{fmt_date(r['return_earliest'], year=False)} – {fmt_date(r['return_latest'], year=False)}"
    elif pd.notna(r["return_earliest"]):
        when = ("after " if r["timeline"].startswith("at least") else "") + fmt_date(r["return_earliest"], year=False)
    else:
        when = ""
    return f"Timeline: {r['timeline']}" + (f" (≈ {when})" if when else "")


def logo_img(team: str, size: int) -> str:
    return (f"<img src='https://assets.nhle.com/logos/nhl/svg/{team}_light.svg' alt='{team}'/>"
            if team in TEAMS else f"<div style='width:{size}px'></div>")


def feed_item(r: pd.Series, missing_ids: set[str], show_source: bool = True) -> str:
    team = r["team_shown"]
    tags = [badge("NHL.com", "src-nhl")] if show_source and r["source"] == "NHL.com" else []
    tags += [badge(r["news_status"], r["tone"])] if r["news_status"] != "Other" else []
    if r["surgery"]:
        tags.append(badge("Surgery", "bad"))
    if pd.notna(r["repeat_of"]):  # its first copy is older than the window
        tags.append(badge(f"Repeated from {fmt_date(r['repeat_of'], year=False)}"))
    if r["news_id"] in missing_ids:
        tags.append(badge("Not on CBS report", "warn"))
    src = [f"via <a href='{escape(r['source_url'])}' target='_blank'>{escape(r['source_name'] or 'source')}</a>"
           if r["source_url"] else escape(r["source_name"])]
    context = r["context"]
    if r["source"] == "NHL.com" and len(context) > 360:  # the report's paragraphs run long
        context = context[:context.rfind(" ", 0, 340)] + " …"
    if timeline_text(r):
        src.append(escape(timeline_text(r)))
    if r["injury_id"] in cbs_status.index:
        src.append("CBS: " + escape(cbs_status[r["injury_id"]]))
    sub = " · ".join(x for x in (r["position"], team) if x)
    return (f"<div class='feed-item'><div class='tm'>{news_time(r['published_at'])}</div>{logo_img(team, 30)}<div>"
            f"<div class='nm'><a href='{player_link(r['player'], r['pkey'])}' target='_self'>"
            f"{escape(r['player'])}</a><span class='sub'>{escape(sub)}</span> {''.join(tags)}</div>"
            f"<div class='hl'>{escape(r['headline'])}</div>"
            + (f"<div class='ctx'>{escape(context)}</div>" if context else "")
            + f"<div class='src'>{' · '.join(x for x in src if x)}</div></div></div>")



def render_feed(items: pd.DataFrame, key: str, show_source: bool = True,
                empty: str = "No injury news in this window.") -> None:
    """News items grouped by day, with a bad / uncertain / good filter."""
    TONES = {"All": None, "Bad news": ["bad"], "Uncertain": ["warn"], "Good news": ["good"]}
    tone = st.segmented_control("News type", list(TONES), default="All", key=key) or "All"
    shown = items if TONES[tone] is None else items[items["tone"].isin(TONES[tone])]
    if shown.empty:
        st.info(empty if tone == "All" else f"No {tone.lower()} in this window.")
    missing_ids = set(missing["news_id"])
    for day, grp in shown.groupby("date", sort=False):
        st.html(f"<div class='news-day'>{day_label(day)} "
                f"<span style='color:#8a8984;font-weight:400'>· {n(len(grp), 'item')}</span></div>"
                + "".join(feed_item(r, missing_ids, show_source) for _, r in grp.iterrows()))


def day_label(day: pd.Timestamp) -> str:
    label = "Today" if day == now else "Yesterday" if day == now - pd.Timedelta(days=1) else ""
    return f"{label + ' · ' if label else ''}{day:%A}, {fmt_date(day)}"


def linked(df: pd.DataFrame) -> list[str]:
    return [player_link(p, k) for p, k in zip(df["player"], df["pkey"])]


PLAYER_COL = st.column_config.LinkColumn("Player", display_text=r"name=(.*?)&player=")

tab_all, tab_dfo, tab_nhl, tab_cbs, tab_x = st.tabs([
    f"All news ({len(recent_news)})", f"Daily Faceoff ({len(dfo_news)})", f"NHL.com Status Report ({len(nhl_news)})",
    "CBS report changes", f"Cross-check ({checks['pkey'].nunique()})"])

with tab_all:
    st.caption("Injury news from [Daily Faceoff](https://www.dailyfaceoff.com/hockey-player-news/injuries), "
               "usually minutes after the beat reporter posts it, and the notes in NHL.com's daily "
               "[Status Report](https://www.nhl.com/news/topic/injuries) (marked NHL.com), which add "
               "coach quotes and timelines. Status, timeline and surgery tags are read from the headline.")
    if not missing.empty:
        cards = []
        for _, r in missing.iterrows():
            team = r["team_shown"]
            facts = " · ".join(x for x in (r["position"], TEAMS.get(team, (team,))[0],
                                           fmt_date(r["date"], year=False)) if x)
            cards.append(
                f"<div class='news-card'>{logo_img(team, 34)}<div><div class='nm'>"
                f"<a href='{player_link(r['player'], r['pkey'])}' target='_self'>{escape(r['player'])}</a></div>"
                f"<div class='sub'>{escape(facts)}</div>"
                f"<div class='st'>{escape(r['headline'])}</div><div>{badge(r['news_status'], r['tone'])}</div>"
                f"</div></div>")
        st.markdown(f"**Not on the CBS report yet ({len(missing)})**", help=(
            "Reported hurt or uncertain by Daily Faceoff or NHL.com in this window, with no open CBS injury. "
            "CBS often catches up by its next scrape."))
        st.html(f"<div class='news-grid'>{''.join(cards)}</div>")
    render_feed(recent_news, "news_tone")

with tab_dfo:
    st.subheader("Status changes")
    st.caption("Players whose Daily Faceoff status moved in this window: the status he had before it (or his "
               "first item in it) against his latest. Better or Worse is by how serious the status is "
               "(returning, practicing, day-to-day or game-time decision, out, week-to-week, IR, season).")
    if changes.empty:
        st.info("No Daily Faceoff status changes in this window.")
    else:
        DIRS = {"All": None, "Worse": "Worse", "Better": "Better"}
        pick = st.segmented_control("Direction", list(DIRS), default="All", key="dfo_dir") or "All"
        shown = changes if DIRS[pick] is None else changes[changes["direction"] == DIRS[pick]]
        out = shown.assign(player=linked(shown), arrow=shown["direction"].map(
            {"Better": "▲ Better", "Worse": "▼ Worse", "Changed": "• Changed"}))
        st.dataframe(
            out[["date", "player", "team_shown", "was_status", "was_date", "news_status", "arrow", "updates",
                 "headline"]].rename(columns={
                "date": "Latest", "player": "Player", "team_shown": "Team", "was_status": "Was",
                "was_date": "Was as of", "news_status": "Now", "arrow": "Direction",
                "updates": "Items in window", "headline": "Latest headline"}),
            hide_index=True, width="stretch", placeholder="—", height=min(38 + 35 * len(out), 423),
            column_config={"Player": PLAYER_COL, "Latest": st.column_config.DateColumn(format="MMM D"),
                           "Was as of": st.column_config.DateColumn(format="MMM D"),
                           "Latest headline": st.column_config.TextColumn(width="large")})
    st.subheader("Daily Faceoff feed")
    render_feed(dfo_news, "dfo_tone", show_source=False, empty="No Daily Faceoff news in this window.")

with tab_nhl:
    if all_reports.empty:
        st.info("No NHL.com Status Reports stored yet.")
    else:
        options = list(window_reports["source_url"]) or list(all_reports["source_url"][:1])
        meta = all_reports.set_index("source_url")
        labels = {f"{fmt_date(meta.at[u, 'date'])} · {meta.at[u, 'notes']} notes, {meta.at[u, 'teams']} teams": u
                  for u in options}
        url = labels[st.selectbox("Report", list(labels), key="nhl_report")]
        r0 = meta.loc[url]
        edited = pd.to_datetime(r0["updated"], utc=True).tz_convert(r0["published"].tz)
        st.html(f"<div class='rep-meta'>Published {fmt_date(r0['published'])} at {news_time(r0['published'])} ET"
                + (f" · last edited {fmt_date(edited, year=False)} {news_time(edited)}"
                   if edited - r0["published"] > pd.Timedelta(minutes=10) else "")
                + f" · <a href='{escape(url)}' target='_blank'>read on NHL.com</a></div>")
        diff = report_diff(all_feed, url)
        parts = {k: for_teams(v) for k, v in diff.items() if k != "prev"}
        if diff["prev"]:
            prev = meta.loc[diff["prev"]]
            st.subheader(f"Changes since the {fmt_date(prev['date'], year=False)} report")
            m = st.columns(4)
            m[0].metric("New in this report", len(parts["new"]), border=True,
                        help="Players in this report who weren't in the previous one.")
            m[1].metric("Status changed", len(parts["changed"]), border=True,
                        help="In both reports, with a different status.")
            m[2].metric("Same status", len(parts["carried"]), border=True,
                        help="In both reports, same status (often the same note carried over).")
            m[3].metric("Dropped", len(parts["dropped"]), border=True,
                        help="In the previous report but not this one. NHL.com drops players once the story "
                             "is over or there's nothing new, so this isn't proof he's back.")
            table = pd.concat([
                parts["changed"].assign(change="Status changed"),
                parts["new"].assign(change="New", was_status=""),
                parts["dropped"].assign(change="Dropped", was_status=parts["dropped"]["news_status"],
                                        news_status="")])
            if table.empty:
                st.caption("No changes for the selected teams.")
            else:
                table = table.assign(player=linked(table))
                st.dataframe(
                    table[["change", "player", "team_shown", "was_status", "news_status", "headline"]].rename(
                        columns={"change": "Change", "player": "Player", "team_shown": "Team", "was_status": "Was",
                                 "news_status": "Now", "headline": "Note"}),
                    hide_index=True, width="stretch", placeholder="—", height=min(38 + 35 * len(table), 388),
                    column_config={"Player": PLAYER_COL, "Was": st.column_config.TextColumn(width="medium"),
                                   "Now": st.column_config.TextColumn(width="medium"),
                                   "Note": st.column_config.TextColumn(width="large")})
        else:
            st.caption("This is the first stored report, so there's nothing to compare it with.")
        st.subheader("Notes by team")
        notes = for_teams(all_feed[all_feed["source_url"] == url])
        if notes.empty:
            st.info("This report has no notes for the selected teams.")
        missing_ids = set(missing["news_id"])
        for team, grp in notes.groupby("team_shown", sort=True):
            st.html(f"<div class='team-head'>{logo_img(team, 26)}{escape(TEAMS.get(team, (team,))[0])}"
                    f"<span class='ct'>· {n(len(grp), 'note')}</span></div>"
                    + "".join(feed_item(r, missing_ids, show_source=False) for _, r in grp.iterrows()))

with tab_x:
    st.caption("Where the sources don't agree, from news in this window. CBS updates its report on its own "
               "schedule, so most of these are CBS catching up, but a long gap is worth a look.")
    if checks.empty:
        st.success("All three sources agree on everyone with news in this window.")
    else:
        ISSUES = {
            "News says back, CBS still lists him": "Daily Faceoff or NHL.com says he's returning or activated; "
                                                   "CBS still has him on the report.",
            "CBS more serious than news": "CBS has him on IR or out for the season; the latest news says "
                                          "day-to-day or a game-time decision.",
            "News more serious than CBS": "CBS has him day-to-day; the latest news says week-to-week, IR or longer.",
            "Daily Faceoff and NHL.com differ": "Within 36 hours of each other, one says good news and the other bad.",
            "Not on CBS report": "The latest news says he's hurt or uncertain; CBS doesn't list him.",
        }
        found = [i for i in ISSUES if (checks["issue"] == i).any()]
        pick = st.segmented_control("Issue", ["All", *found], default="All", key="x_issue") or "All"
        shown = checks if pick == "All" else checks[checks["issue"] == pick]
        if pick != "All":
            st.caption(ISSUES[pick])
        out = shown.assign(player=linked(shown))
        st.dataframe(
            out[["date", "player", "team_shown", "issue", "cbs", "dfo", "nhl", "headline"]].rename(columns={
                "date": "Latest news", "player": "Player", "team_shown": "Team", "issue": "Disagreement",
                "cbs": "CBS report", "dfo": "Daily Faceoff", "nhl": "NHL.com", "headline": "Latest headline"}),
            hide_index=True, width="stretch", placeholder="—", height=min(38 + 35 * len(out), 458),
            column_config={"Player": PLAYER_COL, "Latest news": st.column_config.DateColumn(format="MMM D"),
                           "CBS report": st.column_config.TextColumn(help="His open CBS injury: status, IR, expected return."),
                           "Latest headline": st.column_config.TextColumn(width="large")})
        with st.expander("What each disagreement means"):
            st.markdown("\n".join(f"- **{k}.** {v}" for k, v in ISSUES.items()))

with tab_cbs:
    k = st.columns(4)
    k[0].metric("Newly reported", len(new), border=True, help="New on the CBS injury report.")
    k[1].metric("Return date changed", moves["injury_id"].nunique(), border=True,
                help="Injuries whose expected return was pushed back or moved up, or that were "
                     "ruled out for the season or placed on IR.")
    k[2].metric("Just returned", len(back), border=True,
                help="Came off the report or played his first game back in this window.")
    k[3].metric("Due back soon", len(soon), border=True,
                help="Still on the report, expected back within 7 days or listed day-to-day, "
                     "questionable or probable.")

    st.subheader("Newly reported")
    if new.empty:
        st.info("No new injuries in this window.")
    else:
        for day, grp in new.groupby("first_seen", sort=False):
            cards = []
            for _, r in grp.iterrows():
                lines = [f"<div class='inj'>{escape(r['injury_type'])}</div>",
                         f"<div class='st'>{escape(r['status'])}</div>"]
                badges = flags(r)
                if not r["is_open"]:
                    badges.insert(0, (f"Off report {fmt_date(r['return_date'], year=False)}", ""))
                cards.append(card(r, lines, badges))
            label = "Today" if day == now else "Yesterday" if day == now - pd.Timedelta(days=1) else ""
            st.html(f"<div class='news-day'>{label + ' · ' if label else ''}{day:%A}, {fmt_date(day)}</div>"
                    f"<div class='news-grid'>{''.join(cards)}</div>")

    st.subheader("Return timeline changes")
    if moves.empty:
        st.info(f"No expected-return changes in this window. Changes are tracked from {tracking_changes_since(events)}.")
    else:
        out = moves[["date", "player", "pkey", "latest_team", "injury_type", "change", "was", "expected_return",
                     "status"]].copy()
        out["player"] = [player_link(p, k) for p, k in zip(out["player"], out["pkey"])]
        st.dataframe(
            out.drop(columns="pkey").rename(columns={
                "date": "Date", "player": "Player", "latest_team": "Team", "injury_type": "Injury",
                "change": "Change", "was": "Was expected", "expected_return": "Now expected",
                "status": "New status"}),
            hide_index=True, width="stretch", placeholder="—",
            column_config={"Date": st.column_config.DateColumn(format="MMM D"),
                           "Player": st.column_config.LinkColumn(display_text=r"name=(.*?)&player="),
                           "Was expected": st.column_config.DateColumn(format="MMM D, YYYY"),
                           "Now expected": st.column_config.DateColumn(format="MMM D, YYYY")})

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Just returned")
        if back.empty:
            st.info("Nobody came off the report in this window.")
        else:
            cards = []
            for _, r in back.iterrows():
                if r["return_check"] == "Played":
                    line = f"First game back {fmt_date(r['first_game_back'], year=False)}"
                elif r["return_check"] == "Not played since":
                    line = f"Off report {fmt_date(r['return_date'], year=False)}, hasn't played since"
                else:
                    line = f"Off report {fmt_date(r['return_date'], year=False)}"
                missed = [n(int(r['duration']), "day")] if pd.notna(r["duration"]) else []
                if pd.notna(r["games_missed"]):
                    missed.append(n(int(r['games_missed']), "game"))
                lines = [f"<div class='inj'>{escape(r['injury_type'])}</div>",
                         f"<div class='st'>{escape(line)}</div>",
                         f"<div class='st'>Missed {' · '.join(missed)}</div>" if missed else ""]
                badges = [("Last listed out for season", "") if b[0] == "Out for season" else b
                          for b in flags(r) if b[0] != "IR"]
                if r["return_check"] == "Not played since":
                    badges.insert(0, ("Not played since", "warn"))
                if r["return_check"] == "Awaiting first game":
                    badges.insert(0, ("Awaiting first game", ""))
                cards.append(card(r, lines, badges))
            st.html(f"<div class='news-grid'>{''.join(cards)}</div>")
    with right:
        st.subheader("Due back soon")
        if soon.empty:
            st.info("Nobody is expected back in the next week.")
        else:
            cards = []
            for _, r in soon.iterrows():
                if r["return_check"] == "Playing while listed":
                    when = "Dressed for the latest game while listed"
                elif pd.notna(r["expected_return"]):
                    days = (r["expected_return"] - now).days
                    when = (f"Expected back {fmt_date(r['expected_return'], year=False)}"
                            + (" (today)" if days == 0 else f" (in {n(days, 'day')})" if days > 0 else " (overdue)"))
                else:
                    when = r["status_category"]
                lines = [f"<div class='inj'>{escape(r['injury_type'])}</div>",
                         f"<div class='st'>{escape(when)}</div>",
                         f"<div class='st'>Out {n(int(r['duration']), 'day')}"
                         + (f" · {n(int(r['games_missed']), 'game')}" if pd.notna(r["games_missed"]) else "") + "</div>"]
                cards.append(card(r, lines, flags(r)))
            st.html(f"<div class='news-grid'>{''.join(cards)}</div>")
