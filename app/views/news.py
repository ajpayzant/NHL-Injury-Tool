"""What's new: injuries just announced, return dates that moved, players just back
and players due back."""
from html import escape

import pandas as pd
import streamlit as st

from core import fmt_date, tracking_changes_since, history, last_updated, load, player_link, team_label, today
from nhl_injuries.reference import TEAMS

inj, events, runs = load()
now = today()

st.title("Latest Injury News")
st.caption(f"Updated {last_updated(runs)}.")

WINDOWS = {"Last 2 days": 2, "Last 3 days": 3, "Last 7 days": 7, "Last 14 days": 14}
c = st.columns([3, 2, 1.5])
window = c[0].segmented_control("Show", list(WINDOWS), default="Last 3 days", key="news_window") or "Last 3 days"
team_f = c[1].multiselect("Team", list(TEAMS), format_func=team_label, placeholder="All teams")
since = now - pd.Timedelta(days=WINDOWS[window] - 1)  # today counts as one of the days

if team_f:
    inj = inj[inj["latest_team"].isin(team_f) | inj["team"].isin(team_f)]

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

k = st.columns(4)
k[0].metric("Newly reported", len(new), border=True)
k[1].metric("Return date changed", moves["injury_id"].nunique(), border=True,
            help="Injuries whose expected return was pushed back or moved up, or that were "
                 "ruled out for the season or placed on IR.")
k[2].metric("Just returned", len(back), border=True,
            help="Came off the report or played his first game back in this window.")
k[3].metric("Due back soon", len(soon), border=True,
            help="Still on the report, expected back within 7 days or listed day-to-day, "
                 "questionable or probable.")

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
</style>""")


def n(k: int, word: str) -> str:
    return f"{k} {word}{'' if k == 1 else 's'}"


def card(r: pd.Series, lines: list[str], badges: list[tuple[str, str]]) -> str:
    team = r["latest_team"]
    logo = f"<img src='https://assets.nhle.com/logos/nhl/svg/{team}_light.svg' alt='{team}'/>" \
        if team in TEAMS else "<div style='width:34px'></div>"
    facts = [r["position"], f"{r['age']} yrs" if pd.notna(r["age"]) else "", TEAMS.get(team, (team,))[0]]
    tags = "".join(f"<span class='news-badge {cls}'>{escape(t)}</span>" for t, cls in badges)
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
