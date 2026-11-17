"""NHL Injury Database - Streamlit entry point."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make app/ (core, charts) and the repo root (nhl_injuries) importable however the
# app is launched: streamlit run, Streamlit Cloud, or AppTest.
_APP = Path(__file__).resolve().parent
for _p in (_APP.parent, _APP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

st.set_page_config(page_title="NHL Injury Database", page_icon=":material/healing:", layout="wide")

from core import data_version, last_updated, load, updated_ago  # noqa: E402

st.session_state["data_version"] = data_version()  # what this full run loads
inj, events, runs = load()

# The Action commits new data every few minutes and Streamlit Cloud pulls it onto disk.
# This checks once a minute and reruns the whole page when it lands, so a tab left open
# shows new injuries and news without a manual refresh. Filters and selections persist.
REFRESH_EVERY = "60s"


@st.fragment(run_every=REFRESH_EVERY)
def freshness() -> None:
    if data_version() != st.session_state.get("data_version"):
        st.rerun()
    _, _, r = load()
    ago = updated_ago(r)
    st.caption(f"Sources: CBS Sports injury report, Daily Faceoff and NHL.com injury news  \n"
               f"Updated {last_updated(r)}{f' ({ago})' if ago else ''}  \n"
               "Checks for new data every minute")


with st.sidebar:
    st.markdown("### NHL Injury Database")
    freshness()

pages = st.navigation({
    "": [
        st.Page("views/overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page("views/news.py", title="Latest Injury News", icon=":material/campaign:"),
        st.Page("views/search.py", title="Injury Search", icon=":material/search:"),
    ],
    "Explore": [
        st.Page("views/teams.py", title="Teams", icon=":material/groups:"),
        st.Page("views/players.py", title="Players", icon=":material/person:"),
        st.Page("views/injury_types.py", title="Injury Types", icon=":material/personal_injury:"),
        st.Page("views/seasons.py", title="Seasons", icon=":material/calendar_month:"),
        st.Page("views/trends.py", title="Season Trends", icon=":material/show_chart:"),
    ],
    "Data": [
        st.Page("views/downloads.py", title="Data & Downloads", icon=":material/download:"),
    ],
})
pages.run()
