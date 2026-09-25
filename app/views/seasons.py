import pandas as pd
import streamlit as st

import charts
from core import avg_days_out, avg_games_missed, display_table, games_lost, download_buttons, load, seasons
from nhl_injuries.reference import TEAMS

inj, _, runs = load()

st.title("Seasons")
st.caption("Injuries are assigned to a season by the date they first appeared on the report. "
           "The league year turns over on July 1, so offseason and preseason injuries count "
           "toward the upcoming season.")

rows = []
for s in seasons(inj):
    d = inj[inj["season"] == s]
    avg, n = avg_days_out(d)
    avg_g, _ = avg_games_missed(d)
    top_team = d["latest_team"].value_counts()
    rows.append({
        "Season": s, "Injuries": len(d), "Players": d["player"].nunique(),
        "Still open": int(d["is_open"].sum()), "Avg days missed": avg,
        "Games lost": games_lost(d), "Avg games missed": avg_g, "Re-injuries": int(d["is_reinjury"].sum()),
        "Most common injury": d["injury_type"].mode().iloc[0] if len(d) else "",
        "Most injuries (team)": f"{top_team.index[0]} ({top_team.iloc[0]})" if len(top_team) else "",
        "Tracked from": d["first_seen"].min(),
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", placeholder="—", column_config={
    "Avg days missed": st.column_config.NumberColumn(format="%.1f"),
    "Avg games missed": st.column_config.NumberColumn(format="%.1f"),
    "Games lost": st.column_config.NumberColumn(help="Player-games missed through injury, open injuries included"),
    "Tracked from": st.column_config.DateColumn(format="MMM D, YYYY"),
})

first = inj["first_seen"].min()
st.info(f"Tracking began {first:%B} {first.day}, {first.year}, so the {inj.loc[inj['first_seen'].idxmin(), 'season']} "
        "season only covers its final stretch. Players already on the report that day have a "
        "start date of when tracking began, not when they got hurt; they are left out of the "
        "days-out averages.", icon=":material/info:")

season = st.selectbox("Season", seasons(inj))
d = inj[inj["season"] == season]

st.subheader(f"{season}: injuries reported by month")
monthly = charts.with_category_order(
    d.assign(month=d["first_seen"].dt.to_period("M").dt.to_timestamp())
    .groupby(["month", "category"], observed=True).size().rename("injuries").reset_index())
st.altair_chart(charts.monthly_bars(monthly, "month", "injuries", color_by="category"),
                width="stretch")

left, right = st.columns(2, gap="large")
with left:
    st.subheader("By team")
    tm = (d.groupby("latest_team").size().reindex(list(TEAMS), fill_value=0)
          .rename("injuries").reset_index().rename(columns={"latest_team": "team"}))
    st.altair_chart(charts.hbar(tm, "team", "injuries", x_title="Injuries"), width="stretch")
with right:
    st.subheader("By body region")
    reg = charts.with_category_order(
        d.groupby("category", observed=True).size().rename("injuries").reset_index())
    st.altair_chart(charts.hbar(reg, "category", "injuries", x_title="Injuries",
                                sort=list(reg.sort_values("category_order")["category"])),
                    width="stretch")
    st.subheader("Longest absences")
    longest = d[~d["is_open"] & ~d["start_is_lower_bound"]].nlargest(10, "days_out")
    display_table(longest, ["player", "latest_team", "injury_type", "first_seen", "return_date",
                            "duration", "games_missed"])

with st.expander(f"All {len(d)} injuries in {season}"):
    display_table(d.sort_values("first_seen", ascending=False),
                  ["player", "position", "latest_team", "injury_type", "status", "first_seen",
                   "return_date", "duration", "games_missed", "return_check", "reinjury_match"])
    download_buttons(d, f"nhl_injuries_{season}", key="season")
