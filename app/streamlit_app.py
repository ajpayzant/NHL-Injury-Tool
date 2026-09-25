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

from core import last_updated, load  # noqa: E402

inj, events, runs = load()

with st.sidebar:
    st.markdown("### NHL Injury Database")
    st.caption(f"Source: CBS Sports injury report  \nUpdated {last_updated(runs)}")

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
