"""Headless smoke test: every page renders against the committed data without errors."""
import csv
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")
PAGES = ["views/overview.py", "views/news.py", "views/trends.py", "views/search.py", "views/teams.py", "views/players.py",
         "views/injury_types.py", "views/seasons.py", "views/downloads.py"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.switch_page(page).run()
    assert not at.exception, [e.value for e in at.exception]


def test_player_profile_and_filters():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.switch_page("views/players.py").run()
    with open(Path(APP).parent.parent / "data" / "injuries.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # One player with a CBS id who is on the report now, one legacy name-only key.
    live = next(r for r in rows if r["player_id"] and not r["return_date"])
    # Links from before NHL ids were added used the CBS id; they still resolve.
    at.query_params["player"] = live["player_id"]
    at.run()
    assert at.selectbox[0].value == (live["nhl_id"] or live["player_id"])
    assert not at.exception, [e.value for e in at.exception]
    assert any("Currently on the report" in w.value for w in at.warning)
    unmatched = next((r for r in rows if not r["player_id"] and not r["nhl_id"]), None)
    if unmatched:
        at.selectbox[0].set_value("name:" + unmatched["player"]).run()
        assert not at.exception, [e.value for e in at.exception]
    reinjured = next(r for r in rows if r["reinjury_match"])
    at.selectbox[0].set_value(reinjured["nhl_id"]).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Re-injury" in e.value for e in at.error)

    at.switch_page("views/search.py").run()
    at.text_input[0].input("Makar").run()
    assert not at.exception
    assert at.metric[0].value in ("1", "2", "3")

    at.switch_page("views/news.py").run()
    for window in ("Last 2 days", "Last 14 days"):
        at.segmented_control[0].set_value(window).run()
        assert not at.exception, [e.value for e in at.exception]

    at.switch_page("views/injury_types.py").run()
    at.segmented_control[0].set_value("Body region").run()
    assert not at.exception, [e.value for e in at.exception]
