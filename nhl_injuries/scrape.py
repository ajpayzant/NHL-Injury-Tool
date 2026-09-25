"""Fetch and parse the CBS Sports NHL injury report.

The page is one ``div.TableBaseWrapper`` per team that has injuries: an ``h4``
with the team name/link, then a five-column table (Player, Position, Updated,
Injury, Injury Status). Player cells link to ``/nhl/players/<id>/<slug>/``; that
numeric id is what episodes are matched on, so trades and name spellings don't
split one injury into two rows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from .reference import CBS_CODE_TO_NHL, CBS_NAME_TO_NHL, POSITIONS, TEAMS

CBS_INJURY_URL = "https://www.cbssports.com/nhl/injuries/"
USER_AGENT = "Mozilla/5.0 (compatible; NHL-Injury-Database/2.0; +https://github.com/)"
REQUIRED_HEADERS = ["player", "position", "updated", "injury", "injury status"]

_PLAYER_HREF = re.compile(r"/nhl/players/(\d+)/")
_TEAM_HREF = re.compile(r"/nhl/teams/([A-Z]+)/")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class ScrapeError(RuntimeError):
    pass


@dataclass
class ReportRow:
    player_id: str
    player: str
    position: str
    team: str
    injury_type: str
    status: str
    source_updated: str  # ISO date or ""

    def as_dict(self) -> dict:
        return asdict(self)


def fetch_html(url: str = CBS_INJURY_URL, timeout: int = 30) -> str:
    resp = requests.get(
        url, timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    )
    if not resp.ok:
        raise ScrapeError(f"CBS fetch failed: HTTP {resp.status_code}")
    return resp.text


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def _team_code(wrapper) -> str:
    link = wrapper.select_one(".TeamName a") or wrapper.select_one("h4 a[href*='/nhl/teams/']")
    if link is not None:
        m = _TEAM_HREF.search(link.get("href", ""))
        if m:
            code = CBS_CODE_TO_NHL.get(m.group(1), m.group(1))
            if code in TEAMS:
                return code
        name = _text(link)
        if name in CBS_NAME_TO_NHL:
            return CBS_NAME_TO_NHL[name]
    title = _text(wrapper.select_one("h4"))
    return CBS_NAME_TO_NHL.get(title, "")


def _player(cell) -> tuple[str, str]:
    """(cbs_player_id, full name). The cell has a short ('D. Helleson') and a long
    ('Drew Helleson') rendering; prefer the long one."""
    link = cell.select_one(".CellPlayerName--long a") or cell.select_one("a[href*='/nhl/players/']")
    if link is None:
        return "", _text(cell)
    m = _PLAYER_HREF.search(link.get("href", ""))
    return (m.group(1) if m else ""), _text(link)


def parse_updated(raw: str, as_of: date) -> str:
    """'Tue, Sep 22' -> ISO date. CBS gives no year: use the as-of year, and step
    back a year if that would put the update more than a week in the future."""
    m = re.search(r"(" + "|".join(_MONTHS) + r")\w*\.?\s+(\d{1,2})", raw or "")
    if not m:
        return ""
    month, day = _MONTHS.index(m.group(1)) + 1, int(m.group(2))
    for year in (as_of.year, as_of.year - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if (d - as_of).days <= 7:
            return d.isoformat()
    return ""


def parse_report(html: str, as_of: date) -> list[ReportRow]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[ReportRow] = []
    seen: set[str] = set()

    for wrapper in soup.select("div.TableBaseWrapper"):
        table = wrapper.find("table")
        if table is None:
            continue
        headers = [_text(th).lower() for th in table.select("thead th")]
        if not all(h in headers for h in REQUIRED_HEADERS):
            continue
        idx = {h: headers.index(h) for h in REQUIRED_HEADERS}
        team = _team_code(wrapper)
        if not team:
            raise ScrapeError(f"Unrecognised team heading: {_text(wrapper.select_one('h4'))!r}")

        for tr in table.select("tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < len(REQUIRED_HEADERS):
                continue
            player_id, player = _player(cells[idx["player"]])
            position = _text(cells[idx["position"]]).upper()
            if not player or position not in POSITIONS:
                continue
            key = player_id or f"{player}|{team}"
            if key in seen:  # CBS occasionally lists a player twice
                continue
            seen.add(key)
            rows.append(ReportRow(
                player_id=player_id,
                player=player,
                position=position,
                team=team,
                injury_type=_text(cells[idx["injury"]]),
                status=_text(cells[idx["injury status"]]),
                source_updated=parse_updated(_text(cells[idx["updated"]]), as_of),
            ))
    return rows


def scrape(as_of: date, html: str | None = None) -> list[ReportRow]:
    return parse_report(html if html is not None else fetch_html(), as_of)
