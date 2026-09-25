import pandas as pd
import streamlit as st

import charts
from core import (REINJURY_HELP, RETURN_CHECK_HELP, display_table, download_buttons, fmt_date,
                  history, load, today, tracking_changes_since)
from nhl_injuries.reference import TEAMS

inj, events, _ = load()

st.title("Players")

latest = inj.sort_values("last_seen").groupby("pkey").tail(1).set_index("pkey")
labels = (latest["player"] + " · " + latest["position"] + " · " + latest["latest_team"]).sort_values()

wanted = st.query_params.get("player")
keys = list(labels.index)
if wanted and wanted not in keys:  # older links used the CBS id
    hit = inj.loc[inj["player_id"] == wanted, "pkey"]
    wanted = hit.iloc[0] if len(hit) else None
pkey = st.selectbox("Player", keys, format_func=labels.get,
                    index=keys.index(wanted) if wanted in keys else None,
                    placeholder="Type a player's name…")
if pkey is None:
    st.caption("Most injuries on record:")
    top = (inj.groupby("pkey").agg(player=("player", "last"), team=("latest_team", "last"),
                                   injuries=("injury_id", "size"), days=("days_out", "sum"),
                                   games=("games_missed", "sum"))
           .sort_values(["injuries", "games", "days"], ascending=False).head(15))
    st.dataframe(top.rename(columns={"player": "Player", "team": "Team", "injuries": "Injuries",
                                     "days": "Days missed (returned)", "games": "Games missed"}),
                 hide_index=True, width="stretch")
    st.stop()
st.query_params["player"] = pkey
st.query_params.pop("name", None)

eps = inj[inj["pkey"] == pkey].sort_values("first_seen", ascending=False)
me = latest.loc[pkey]
open_now = eps[eps["is_open"]]
team_name = TEAMS.get(me["latest_team"], (me["latest_team"],))[0]

# Header: name, age, position, team.
facts = [f"Age {me['age']}" if pd.notna(me["age"]) else None, me["position"] or None, team_name]
links = []
if me["nhl_id"]:
    links.append(f"<a href='https://www.nhl.com/player/{me['nhl_id']}' target='_blank'>NHL.com</a>")
if me["player_id"]:
    links.append(f"<a href='https://www.cbssports.com/nhl/players/{me['player_id']}/' target='_blank'>CBS</a>")
headshot = (f"<img src='https://assets.nhle.com/mugs/nhl/latest/{me['nhl_id']}.png' width='72' height='72' "
            f"style='border-radius:50%;background:#f1f0ec;object-fit:cover' alt='' "
            f"onerror=\"this.style.display='none'\"/>" if me["nhl_id"] else "")
logo = (f"<img src='https://assets.nhle.com/logos/nhl/svg/{me['latest_team']}_light.svg' width='40' alt=''/>"
        if me["latest_team"] in TEAMS else "")
st.markdown(
    f"<div style='display:flex;align-items:center;gap:14px;margin:.25rem 0 1rem'>{headshot}"
    f"<div><div style='font-size:1.6rem;font-weight:600;display:flex;align-items:center;gap:8px'>"
    f"{me['player']}{logo}</div>"
    f"<div style='color:#52514e'>{' · '.join(f for f in facts if f)}"
    + (f" · {' · '.join(links)}" if links else "") + "</div>"
    + (f"<div style='color:#8a8984;font-size:.85rem'>Born {fmt_date(me['birth_date'])}</div>"
       if pd.notna(me["birth_date"]) else "") + "</div></div>",
    unsafe_allow_html=True)

k = st.columns(4)
k[0].metric("Status", open_now.iloc[0]["status_category"] if len(open_now) else "Healthy", border=True)
k[1].metric("Injuries on record", len(eps), border=True)
k[2].metric("Days missed", int(eps["duration"].fillna(0).sum()), border=True,
            help="Days on the injury report, current injury included.")
k[3].metric("Games missed", int(eps["games_missed"].fillna(0).sum()), border=True,
            help="Team games he didn't dress for while injured, from NHL box scores.")

if len(open_now):
    o = open_now.iloc[0]
    back = f" Expected back {fmt_date(o['expected_return'])}." if pd.notna(o["expected_return"]) else ""
    games = f", {int(o['games_missed'])} games" if pd.notna(o["games_missed"]) else ""
    st.warning(f"**Currently on the report:** {o['injury_type']} — {o['status']} "
               f"(first reported {fmt_date(o['first_seen'])}, {int(o['duration'])} days{games}).{back}",
               icon=":material/personal_injury:")
    if o["return_check"] == "Playing while listed":
        st.info("He dressed for his team's latest game while still on the report.",
                icon=":material/sports_hockey:")
for _, r in eps[eps["is_reinjury"]].iterrows():
    prior = inj[inj["injury_id"] == r["reinjury_of"]]
    what = f"{prior.iloc[0]['injury_type']} ({fmt_date(prior.iloc[0]['first_seen'])})" if len(prior) else "a prior injury"
    st.error(f"**Re-injury — {r['reinjury_match'].lower()}:** {r['injury_type']} on {fmt_date(r['first_seen'])}, "
             f"{int(r['days_since_prior'])} days after returning from {what}.",
             icon=":material/replay:")

st.subheader("Injury timeline")
tl = eps.copy()
tl["end"] = tl["return_date"].fillna(today())
tl["end_label"] = tl["return_date"].map(fmt_date).replace("", "Still out")
# One row per episode; the date keeps two same-type injuries from sharing a row.
tl["label"] = tl["injury_type"] + " · " + tl["first_seen"].map(fmt_date)
tl["category"] = tl["category"].astype(str)
st.altair_chart(charts.timeline(tl), width="stretch")

st.subheader("History")
display_table(eps, ["injury_type", "category", "team", "status", "first_seen", "return_date",
                    "first_game_back", "duration", "games_missed", "return_check", "reinjury_match",
                    "season", "notes"])
download_buttons(eps, f"{me['player'].lower().replace(' ', '_')}_injuries", key="player")
st.caption(f"**Return check:** {RETURN_CHECK_HELP}  \n**Re-injury:** {REINJURY_HELP}")

st.subheader("Expected-return history")
hist = history()
hist = hist[hist["injury_id"].isin(eps["injury_id"])]
choices = list(eps["injury_id"])
names = dict(zip(eps["injury_id"], eps["injury_type"] + " · " + eps["first_seen"].map(fmt_date)
                 + eps["is_open"].map({True: " (current)", False: ""})))
pick = st.selectbox("Injury", choices, format_func=names.get, key="hist_injury",
                    label_visibility="collapsed") if len(choices) > 1 else choices[0]
h = hist[hist["injury_id"] == pick].sort_values("date")
ep = eps[eps["injury_id"] == pick].iloc[0]
dated = h.dropna(subset=["expected_return"])
if len(dated):
    st.altair_chart(charts.return_history(dated, ep["return_date"], ep["first_game_back"], end=today()), width="stretch")
else:
    st.caption("No status on this injury gave a return date (e.g. day-to-day or out indefinitely).")
if not h["date_known"].all():
    st.caption(f"This injury predates change tracking ({tracking_changes_since(events)}), so its first row is the status "
               "it had when tracking began, not the original report.")
st.dataframe(
    h.sort_values("date", ascending=False)[["date", "status", "expected_return", "change"]].rename(
        columns={"date": "Date", "status": "Status", "expected_return": "Expected Back", "change": "Change"}),
    hide_index=True, width="stretch", placeholder="—",
    column_config={"Date": st.column_config.DateColumn(format="MMM D, YYYY"),
                   "Expected Back": st.column_config.DateColumn(format="MMM D, YYYY")})

ids = set(eps["injury_id"])
log = events[events["injury_id"].isin(ids)].sort_values("at", ascending=False)
if not log.empty:
    with st.expander(f"Report changes ({len(log)})"):
        st.dataframe(log[["date", "event", "detail"]].rename(
            columns={"date": "Date", "event": "Change", "detail": "Detail"}),
            hide_index=True, width="stretch",
            column_config={"Date": st.column_config.DateColumn(format="MMM D, YYYY")})
