import pandas as pd
import streamlit as st

import charts
from core import (REINJURY_HELP, RETURN_CHECK_HELP, display_table, download_buttons, fmt_date,
                  history, load, news, news_time, today, tracking_changes_since)
from nhl_injuries.reference import TEAMS

inj, events, _ = load()
feed = news()

st.title("Players")

latest = inj.sort_values("last_seen").groupby("pkey").tail(1).set_index("pkey")
labels = latest["player"] + " · " + latest["position"] + " · " + latest["latest_team"]
# Players Daily Faceoff has written about who have never been on the CBS report.
news_only = feed[~feed["pkey"].isin(latest.index)].drop_duplicates("pkey").set_index("pkey")
labels = pd.concat([labels, news_only["player"] + " · " + news_only["position"] + " · "
                    + news_only["team_shown"] + " (news only)"]).sort_values()

wanted = st.query_params.get("player")
keys = list(labels.index)
if wanted and wanted not in keys:  # older links used the CBS id
    hit = inj.loc[inj["player_id"] == wanted, "pkey"]
    wanted = hit.iloc[0] if len(hit) else None
# Seed the picker from the URL only when the URL changed (a player link was followed);
# otherwise the picker keeps whatever was just chosen in it.
if wanted != st.session_state.get("player_url") or "player_pick" not in st.session_state:
    st.session_state["player_pick"] = wanted if wanted in keys else None
    st.session_state["player_url"] = wanted
pkey = st.selectbox("Player", keys, format_func=labels.get, key="player_pick",
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
st.query_params["player"] = st.session_state["player_url"] = pkey
st.query_params.pop("name", None)

eps = inj[inj["pkey"] == pkey].sort_values("first_seen", ascending=False)
my_news = feed[feed["pkey"] == pkey]
if pkey in latest.index:
    me = latest.loc[pkey]
else:
    r = news_only.loc[pkey]
    me = pd.Series({"player": r["player"], "position": r["position"], "latest_team": r["team_shown"],
                    "nhl_id": r["nhl_id"], "player_id": "", "age": pd.NA, "birth_date": pd.NaT})
open_now = eps[eps["is_open"]]
team_name = TEAMS.get(me["latest_team"], (me["latest_team"],))[0]
# Daily Faceoff's team is the player's team when the item was scraped, so a recent
# scrape there catches a trade before CBS moves him.
fresh = my_news[my_news["team"].isin(list(TEAMS))].sort_values("scraped_at")
news_team = fresh.iloc[-1]["team"] if len(fresh) else ""
moved = bool(news_team) and news_team != me["latest_team"] and (
    eps.empty or pd.Timestamp(fresh.iloc[-1]["scraped_at"].date()) >= eps["last_seen"].max() - pd.Timedelta(days=1))

# Header: name, age, position, team.
facts = [f"Age {me['age']}" if pd.notna(me["age"]) else None, me["position"] or None, team_name]
if moved:
    facts[-1] = f"{TEAMS[news_team][0]} (CBS still lists {me['latest_team']})"
links = []
if me["nhl_id"]:
    links.append(f"<a href='https://www.nhl.com/player/{me['nhl_id']}' target='_blank'>NHL.com</a>")
if me["player_id"]:
    links.append(f"<a href='https://www.cbssports.com/nhl/players/{me['player_id']}/' target='_blank'>CBS</a>")
headshot = (f"<img src='https://assets.nhle.com/mugs/nhl/latest/{me['nhl_id']}.png' width='72' height='72' "
            f"style='border-radius:50%;background:#f1f0ec;object-fit:cover' alt='' "
            f"onerror=\"this.style.display='none'\"/>" if me["nhl_id"] else "")
logo = (f"<img src='https://assets.nhle.com/logos/nhl/svg/{news_team if moved else me['latest_team']}_light.svg' width='40' alt=''/>"
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


def news_section(items: pd.DataFrame) -> None:
    st.subheader("Daily Faceoff news")
    if items.empty:
        st.caption("No Daily Faceoff injury news for this player.")
        return
    out = items[["published_at", "news_status", "headline", "context", "timeline", "source_name",
                 "source_url"]].copy()
    out["published_at"] = [f"{fmt_date(t)} {news_time(t)}" for t in out["published_at"]]
    st.dataframe(
        out.rename(columns={"published_at": "Published (ET)", "news_status": "Status", "headline": "Headline",
                            "context": "Background", "timeline": "Timeline", "source_name": "Reporter",
                            "source_url": "Source"}),
        hide_index=True, width="stretch", placeholder="—", height=min(38 + 35 * len(out), 318),
        column_config={"Headline": st.column_config.TextColumn(width="large"),
                       "Background": st.column_config.TextColumn(width="medium"),
                       "Source": st.column_config.LinkColumn(display_text="open")})
    st.caption(f"{len(items)} item{'s' if len(items) != 1 else ''} · from "
               "[Daily Faceoff](https://www.dailyfaceoff.com/hockey-player-news/injuries)")


if eps.empty:
    latest_item = my_news.iloc[0]
    st.warning(f"**Not on the CBS injury report.** Latest from Daily Faceoff "
               f"({fmt_date(latest_item['date'])}): {latest_item['headline']}", icon=":material/campaign:")
    news_section(my_news)
    st.stop()

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
    about = my_news[my_news["injury_id"] == o["injury_id"]]
    latest_news = (f"  \n**Latest news** ({fmt_date(about.iloc[0]['date'])}): {about.iloc[0]['headline']}"
                   if len(about) else "")
    dated = about[about["timeline"] != ""]
    if len(dated):
        t = dated.iloc[0]
        span = fmt_date(t["return_earliest"]) + (f" – {fmt_date(t['return_latest'])}"
                                                 if pd.notna(t["return_latest"]) and t["return_latest"] != t["return_earliest"] else "")
        latest_news += f"  \n**Daily Faceoff timeline:** {t['timeline']} from {fmt_date(t['date'])} (≈ {span})"
    st.warning(f"**Currently on the report:** {o['injury_type']} — {o['status']} "
               f"(first reported {fmt_date(o['first_seen'])}, {int(o['duration'])} days{games}).{back}"
               + latest_news, icon=":material/personal_injury:")
    if o["return_check"] == "Playing while listed":
        st.info("He dressed for his team's latest game while still on the report.",
                icon=":material/sports_hockey:")
for _, r in eps[eps["is_reinjury"]].iterrows():
    prior = inj[inj["injury_id"] == r["reinjury_of"]]
    what = f"{prior.iloc[0]['injury_type']} ({fmt_date(prior.iloc[0]['first_seen'])})" if len(prior) else "a prior injury"
    st.error(f"**Re-injury — {r['reinjury_match'].lower()}:** {r['injury_type']} on {fmt_date(r['first_seen'])}, "
             f"{int(r['days_since_prior'])} days after returning from {what}.",
             icon=":material/replay:")

news_section(my_news)

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
