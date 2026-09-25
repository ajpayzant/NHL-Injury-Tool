import pandas as pd
import streamlit as st

import charts
from core import display_table, last_updated, load, today
from nhl_injuries.reference import TEAMS

inj, events, runs = load()
now = today()
week_ago = now - pd.Timedelta(days=7)

st.title("NHL Injury Report")
st.caption(f"Every player on the CBS Sports NHL injury report, tracked twice a day. "
           f"Last updated {last_updated(runs)}.")

current = inj[inj["is_open"]]
new_7 = inj[inj["first_seen"] > week_ago]
back_7 = inj[inj["return_date"] > week_ago]

c = st.columns(4)
c[0].metric("Open injuries", len(current), border=True,
            help="Players currently injured. Someone who drops off the report stays open until "
                 "they have missed two scrapes in a row.")
c[1].metric("Out for season / IR",
            int((current["status_category"].eq("Out for season") | current["on_ir"]).sum()),
            border=True)
c[2].metric("New in last 7 days", len(new_7), border=True)
c[3].metric("Returned in last 7 days", len(back_7), border=True)

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Current injuries by team")
    by_team = (current.groupby("latest_team").size()
               .reindex(list(TEAMS), fill_value=0).rename("injuries").reset_index()
               .rename(columns={"latest_team": "team"}))
    by_team["name"] = by_team["team"].map(lambda t: TEAMS[t][0])
    st.altair_chart(charts.hbar(by_team, "team", "injuries", x_title="Players on report",
                                tooltip=["name:N", "injuries:Q"]), width="stretch")

with right:
    st.subheader("By body region")
    reg = charts.with_category_order(
        current.groupby("category", observed=True).size().rename("injuries").reset_index())
    st.altair_chart(charts.hbar(reg, "category", "injuries", x_title="Players on report",
                                sort=list(reg.sort_values("category_order")["category"])),
                    width="stretch")

    st.subheader("By status")
    stat = current.groupby("status_category").size().rename("injuries").reset_index()
    st.altair_chart(charts.hbar(stat, "status_category", "injuries", x_title="Players on report"),
                    width="stretch")

st.subheader("What changed this week")
recent = events[(events["date"] > week_ago) & events["event"].isin(
    ["opened", "closed", "reopened", "type_changed", "team_changed"])].copy()
if recent.empty:
    st.info("No changes in the last seven days.")
else:
    label = {"opened": "New injury", "closed": "Returned", "reopened": "Back on report",
             "type_changed": "Injury updated", "team_changed": "Team changed"}
    recent["Change"] = recent["event"].map(label)
    recent = recent.sort_values("at", ascending=False)
    st.dataframe(
        recent[["date", "Change", "player", "team", "detail"]]
        .rename(columns={"date": "Date", "player": "Player", "team": "Team", "detail": "Detail"}),
        hide_index=True, width="stretch", height=min(420, 38 + 35 * len(recent)),
        column_config={"Date": st.column_config.DateColumn(format="MMM D")},
    )

st.subheader("Everyone on the report")
display_table(current.sort_values(["latest_team", "player"]),
              ["player", "position", "age", "latest_team", "injury_type", "status", "first_seen",
               "expected_return", "duration", "games_missed", "reinjury_match"])
