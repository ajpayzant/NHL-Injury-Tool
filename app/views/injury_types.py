import pandas as pd
import streamlit as st

import charts
from core import display_table, download_buttons, load, seasons
from nhl_injuries.reference import CATEGORY_ORDER, POSITIONS

inj, _, _ = load()

st.title("Injury Types")
st.caption("How often each injury shows up and how long players are out. Durations use returned "
           "injuries with a known start date only.")

c = st.columns([1.3, 1.3, 3])
season = c[0].selectbox("Season", ["All seasons"] + seasons(inj))
level = c[1].segmented_control("Group by", ["Injury type", "Body region"], default="Injury type")
scope = inj if season == "All seasons" else inj[inj["season"] == season]
key = "injury_type" if level == "Injury type" else "category"

dur = scope[~scope["is_open"] & ~scope["start_is_lower_bound"]]
summary = (scope.groupby(key, observed=True)
           .agg(injuries=("injury_id", "size"), open=("is_open", "sum"),
                players=("player", "nunique"))
           .join(dur.groupby(key, observed=True)["days_out"]
                 .agg(avg_days="mean", median_days="median", returned="size"))
           .join(scope[scope["return_check"].eq("Played") & ~scope["start_is_lower_bound"]]
                 .groupby(key, observed=True)["games_missed"].mean().rename("avg_games"))
           .join(scope.groupby(key, observed=True)["is_reinjury"].mean().rename("reinjury_rate"))
           .reset_index())
summary["returned"] = summary["returned"].fillna(0).astype(int)
if key == "injury_type":
    summary = summary.merge(scope[["injury_type", "category"]].drop_duplicates("injury_type"),
                            on="injury_type")
summary["share"] = summary["injuries"] / summary["injuries"].sum()
summary = summary.sort_values("injuries", ascending=False)

left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Frequency")
    plot = charts.with_category_order(summary.head(25) if key == "injury_type" else summary)
    if key == "injury_type":
        st.altair_chart(charts.stacked_hbar(plot.assign(n=plot["injuries"]), "injury_type", "n",
                                            "category", x_title="Injuries"), width="stretch")
    else:
        st.altair_chart(charts.hbar(plot, "category", "injuries", x_title="Injuries"),
                        width="stretch")
with right:
    st.subheader("Typical time out")
    st.dataframe(
        summary[[key, "injuries", "open", "returned", "avg_days", "median_days", "avg_games",
                 "reinjury_rate", "share"]]
        .rename(columns={key: "Injury type" if key == "injury_type" else "Body region",
                         "injuries": "Injuries", "open": "Open", "returned": "Timed",
                         "avg_days": "Avg days", "median_days": "Median days", "avg_games": "Avg games",
                         "reinjury_rate": "Re-injury %", "share": "Share"}),
        hide_index=True, width="stretch", height=520, placeholder="—",
        column_config={
            "Avg days": st.column_config.NumberColumn(format="%.1f"),
            "Median days": st.column_config.NumberColumn(format="%.0f"),
            "Avg games": st.column_config.NumberColumn(
                format="%.1f", help="Games missed, over injuries where he has played again"),
            "Re-injury %": st.column_config.NumberColumn(
                format="percent", help="Share that were re-injuries of the same body region"),
            "Share": st.column_config.ProgressColumn(format="percent", min_value=0,
                                                     max_value=float(summary["share"].max() or 1)),
            "Timed": st.column_config.NumberColumn(help="Returned injuries with a known start date"),
        })

st.divider()
st.subheader("Drill into one")
values = list(summary[key].astype(str))
pick = st.selectbox("Injury type" if key == "injury_type" else "Body region", values)
sel = scope[scope[key].astype(str) == pick]

a, b = st.columns(2, gap="large")
with a:
    st.markdown("**By position**")
    pos = sel.groupby("position").size().reindex(POSITIONS, fill_value=0).rename("injuries").reset_index()
    st.altair_chart(charts.hbar(pos, "position", "injuries", sort=POSITIONS, x_title="Injuries"),
                    width="stretch")
with b:
    st.markdown("**By team**")
    tm = sel.groupby("latest_team").size().rename("injuries").reset_index()
    st.altair_chart(charts.hbar(tm, "latest_team", "injuries", x_title="Injuries"), width="stretch")

display_table(sel.sort_values("first_seen", ascending=False),
              ["player", "position", "age", "latest_team", "injury_type", "status", "first_seen",
               "return_date", "duration", "games_missed", "reinjury_match", "season"])
download_buttons(sel, f"{pick.lower().replace(' ', '_').replace('/', '')}_injuries", key="types")
