"""Live data ingestion, pivoted off FanGraphs.

FanGraphs now sits behind a Cloudflare bot challenge that 403s any script
(and any CI runner), so this project pulls from two sources that answer
scripts cleanly:

    * MLB StatsAPI  (statsapi.mlb.com) -- open, no key: standings (RS/RA/W),
      team & player hitting (PA/OBP/SLG). Season tables are cumulative
      season-to-date, so "2026 through today" is just the current season.
    * Baseball-Reference (via pybaseball bwar_bat / bwar_pitch) -- bWAR for
      every player, plus G/GS/relief splits and leverage index.

Three inputs have no open feed and load from data/manual/*.csv:
    * replay / ABS challenge success rate   -> replay_<year>.csv
    * live 40-man payroll (RosterResource)  -> payroll_<year>.csv
    * preseason ZiPS/Steamer projections    -> projections_<year>.csv

mWPA (WPA - WPA/LI) was a FanGraphs-only input and has no open substitute;
it drops out of W.E.A.V.E.R. unless supplied via a manual mwpa_<year>.csv.

Every live fetch is wrapped so one missing feed degrades that single
component rather than killing the whole leaderboard.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

import pandas as pd
import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MANUAL_DIR = os.path.join(DATA_DIR, "manual")

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/124.0 Safari/537.36"}
_STATSAPI = "https://statsapi.mlb.com/api/v1"

# Canonical 3-letter codes for all 30 clubs.
TEAMS = [
    "ARI", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET",
    "HOU", "KCR", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SDP", "SEA", "SFG", "STL", "TBR", "TEX", "TOR", "WSN",
]

# Stable MLB StatsAPI team id -> canonical code (ids never change year to year).
MLB_TEAM_ID = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC", 113: "CIN",
    114: "CLE", 115: "COL", 116: "DET", 117: "HOU", 118: "KCR", 119: "LAD",
    120: "WSN", 121: "NYM", 133: "OAK", 134: "PIT", 135: "SDP", 136: "SEA",
    137: "SFG", 138: "STL", 139: "TBR", 140: "TEX", 141: "TOR", 142: "MIN",
    143: "PHI", 144: "ATL", 145: "CHW", 146: "MIA", 147: "NYY", 158: "MIL",
}

# Broad alias table so BBRef / StatsAPI name variants collapse to one code.
_ALIASES = {
    "ari": "ARI", "az": "ARI", "arizona": "ARI", "diamondbacks": "ARI", "d-backs": "ARI",
    "atl": "ATL", "atlanta": "ATL", "braves": "ATL",
    "bal": "BAL", "baltimore": "BAL", "orioles": "BAL",
    "bos": "BOS", "boston": "BOS", "red sox": "BOS",
    "chc": "CHC", "chn": "CHC", "cubs": "CHC", "chi cubs": "CHC",
    "chw": "CHW", "cws": "CHW", "cha": "CHW", "white sox": "CHW", "chi white sox": "CHW",
    "cin": "CIN", "cincinnati": "CIN", "reds": "CIN",
    "cle": "CLE", "cleveland": "CLE", "guardians": "CLE", "indians": "CLE",
    "col": "COL", "colorado": "COL", "rockies": "COL",
    "det": "DET", "detroit": "DET", "tigers": "DET",
    "hou": "HOU", "houston": "HOU", "astros": "HOU",
    "kc": "KCR", "kcr": "KCR", "kca": "KCR", "kansas city": "KCR", "royals": "KCR",
    "laa": "LAA", "ana": "LAA", "angels": "LAA", "la angels": "LAA",
    "lad": "LAD", "lan": "LAD", "dodgers": "LAD", "la dodgers": "LAD",
    "mia": "MIA", "miami": "MIA", "marlins": "MIA", "fla": "MIA",
    "mil": "MIL", "milwaukee": "MIL", "brewers": "MIL",
    "min": "MIN", "minnesota": "MIN", "twins": "MIN",
    "nym": "NYM", "nyn": "NYM", "mets": "NYM", "ny mets": "NYM",
    "nyy": "NYY", "nya": "NYY", "yankees": "NYY", "ny yankees": "NYY",
    "oak": "OAK", "ath": "OAK", "athletics": "OAK", "a's": "OAK", "sac": "OAK",
    "phi": "PHI", "philadelphia": "PHI", "phillies": "PHI",
    "pit": "PIT", "pittsburgh": "PIT", "pirates": "PIT",
    "sd": "SDP", "sdp": "SDP", "sdn": "SDP", "san diego": "SDP", "padres": "SDP",
    "sea": "SEA", "seattle": "SEA", "mariners": "SEA",
    "sf": "SFG", "sfg": "SFG", "sfn": "SFG", "san francisco": "SFG", "giants": "SFG",
    "stl": "STL", "st. louis": "STL", "cardinals": "STL",
    "tb": "TBR", "tbr": "TBR", "tba": "TBR", "tampa bay": "TBR", "rays": "TBR",
    "tex": "TEX", "texas": "TEX", "rangers": "TEX",
    "tor": "TOR", "toronto": "TOR", "blue jays": "TOR",
    "wsn": "WSN", "was": "WSN", "wsh": "WSN", "washington": "WSN", "nationals": "WSN",
}


def normalize_team(name: object) -> str | None:
    """Map any common team spelling/abbreviation to a canonical 3-letter code."""
    if name is None:
        return None
    key = str(name).strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    upper = str(name).strip().upper()
    if upper in TEAMS:
        return upper
    return None


def _first_col(df: pd.DataFrame, *candidates: str) -> str | None:
    """Return the first column present in df from a list of candidate names."""
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _get(url: str) -> dict:
    r = requests.get(url, headers=_UA, timeout=60)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- #
# MLB StatsAPI (open, no key) — cumulative season-to-date.
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=8)
def standings(season: int) -> pd.DataFrame:
    """Per-team runs scored/allowed and W/L, indexed by canonical code."""
    data = _get(f"{_STATSAPI}/standings?leagueId=103,104&season={season}"
                f"&standingsTypes=regularSeason")
    rows = []
    for div in data.get("records", []):
        for t in div.get("teamRecords", []):
            code = MLB_TEAM_ID.get(t["team"]["id"])
            if code is None:
                continue
            rows.append({
                "team": code,
                "W": t.get("wins", 0),
                "L": t.get("losses", 0),
                "RS": t.get("runsScored", 0),
                "RA": t.get("runsAllowed", 0),
            })
    df = pd.DataFrame(rows).set_index("team")
    df["G"] = df["W"] + df["L"]
    return df


@lru_cache(maxsize=8)
def team_hitting(season: int) -> pd.DataFrame:
    """Team totals: PA, OBP, SLG, indexed by canonical code."""
    data = _get(f"{_STATSAPI}/teams/stats?season={season}&group=hitting"
                f"&stats=season&sportId=1&gameType=R")
    rows = []
    for sp in data["stats"][0]["splits"]:
        code = MLB_TEAM_ID.get(sp.get("team", {}).get("id"))
        if code is None:
            continue
        st = sp["stat"]
        rows.append({
            "team": code,
            "PA": float(st.get("plateAppearances", 0) or 0),
            "OBP": float(st.get("obp", 0) or 0),
            "SLG": float(st.get("slg", 0) or 0),
        })
    return pd.DataFrame(rows).set_index("team")


@lru_cache(maxsize=8)
def player_hitting(season: int) -> pd.DataFrame:
    """One row per batter: team code, PA, OBP, SLG (playerPool=all)."""
    data = _get(f"{_STATSAPI}/stats?stats=season&group=hitting&season={season}"
                f"&sportId=1&gameType=R&playerPool=all&limit=3000")
    rows = []
    for sp in data["stats"][0]["splits"]:
        code = MLB_TEAM_ID.get(sp.get("team", {}).get("id"))
        if code is None:
            continue
        st = sp["stat"]
        rows.append({
            "team": code,
            "PA": float(st.get("plateAppearances", 0) or 0),
            "OBP": float(st.get("obp", 0) or 0),
            "SLG": float(st.get("slg", 0) or 0),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Baseball-Reference WAR (via pybaseball), with relief splits.
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=2)
def _bwar_bat_raw() -> pd.DataFrame:
    from pybaseball import bwar_bat
    return bwar_bat(return_all=True)


@lru_cache(maxsize=2)
def _bwar_pitch_raw() -> pd.DataFrame:
    from pybaseball import bwar_pitch
    return bwar_pitch(return_all=True)


@lru_cache(maxsize=8)
def bref_war(season: int) -> pd.DataFrame:
    """One row per player: team, war, is_pitcher, G, GS, relief_share.

    Batters and pitchers are stacked. `relief_share` is only meaningful for
    pitchers (fraction of innings thrown in relief); it is NaN for batters.
    """
    bat = _bwar_bat_raw()
    pit = _bwar_pitch_raw()

    b = bat[bat["year_ID"] == season].copy()
    b["team"] = b["team_ID"].map(normalize_team)
    b["war"] = pd.to_numeric(b["WAR"], errors="coerce")
    b["is_pitcher"] = False
    b["relief_share"] = float("nan")
    b = b[["team", "war", "is_pitcher", "relief_share"]]

    p = pit[pit["year_ID"] == season].copy()
    p["team"] = p["team_ID"].map(normalize_team)
    p["war"] = pd.to_numeric(p["WAR"], errors="coerce")
    p["is_pitcher"] = True
    ip_rel = pd.to_numeric(p.get("IPouts_relief"), errors="coerce")
    ip_all = pd.to_numeric(p.get("IPouts"), errors="coerce")
    p["relief_share"] = ip_rel / ip_all.where(ip_all > 0)
    p = p[["team", "war", "is_pitcher", "relief_share"]]

    out = pd.concat([b, p], ignore_index=True).dropna(subset=["team"])
    return out


@lru_cache(maxsize=8)
def bref_relievers(season: int) -> pd.DataFrame:
    """One row per reliever: team, li (avg entry leverage), waa, war.

    `li` is Baseball-Reference's GR_leverage_index_avg -- the average leverage
    index at which the pitcher entered games, i.e. how much the manager trusted
    him in tight spots. Relievers are pitchers with >=50% of innings in relief.
    """
    pit = _bwar_pitch_raw()
    p = pit[pit["year_ID"] == season].copy()
    ip_rel = pd.to_numeric(p.get("IPouts_relief"), errors="coerce")
    ip_all = pd.to_numeric(p.get("IPouts"), errors="coerce")
    share = ip_rel / ip_all.where(ip_all > 0)
    p = p[share >= 0.5].copy()
    p["team"] = p["team_ID"].map(normalize_team)
    p["li"] = pd.to_numeric(p["GR_leverage_index_avg"], errors="coerce")
    p["waa"] = pd.to_numeric(p["WAA"], errors="coerce")
    p["war"] = pd.to_numeric(p["WAR"], errors="coerce")
    return p[["team", "li", "waa", "war"]].dropna(subset=["team"])


# --------------------------------------------------------------------------- #
# Baseball-Reference manager replay challenges (live scrape).
# --------------------------------------------------------------------------- #
def _bref_cell(row: str, stat: str) -> str:
    m = re.search(r'data-stat="' + stat + r'"[^>]*>(?:<[^>]+>)*([^<]*)', row)
    return m.group(1).strip() if m else ""


@lru_cache(maxsize=8)
def _managers_rows(season: int) -> tuple:
    """Parsed rows from BBRef's season managers page: one per manager stint.

    Each row is (team, manager, challenges, overturns). Challenge counts live
    in data-stat cells that read_html mangles, so we parse <tr> rows directly.
    Returns an empty tuple if the page can't be fetched or parsed.
    """
    url = (f"https://www.baseball-reference.com/leagues/majors/"
           f"{season}-managers.shtml")
    try:
        html = requests.get(url, headers=_UA, timeout=60).text
    except requests.RequestException:
        return ()
    html = html.replace("<!--", "").replace("-->", "")

    rows = []
    for row in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S):
        code = normalize_team(_bref_cell(row, "team_ID")
                              or _bref_cell(row, "team_name_abbr"))
        ch = _bref_cell(row, "mgr_challenge_count")
        if code is None or not ch.isdigit():
            continue
        ov = _bref_cell(row, "mgr_overturn_count")
        mgr = _bref_cell(row, "manager") or _bref_cell(row, "mgr_ID")
        rows.append((code, mgr, int(ch), int(ov) if ov.isdigit() else 0))
    return tuple(rows)


def replay_challenges(season: int) -> pd.DataFrame:
    """Per-team replay challenges & overturns, summed across the year's managers.

    Teams with a mid-season managerial change get both stints summed. Columns:
    successful, total. Empty frame if the page can't be parsed.
    """
    agg: dict[str, list[int]] = {}
    for team, _mgr, ch, ov in _managers_rows(season):
        cur = agg.setdefault(team, [0, 0])
        cur[0] += ov
        cur[1] += ch
    if not agg:
        return pd.DataFrame(columns=["successful", "total"])
    df = pd.DataFrame(agg, index=["successful", "total"]).T
    df.index.name = "team"
    return df


def team_managers(season: int) -> pd.Series:
    """Primary manager per team = the stint with the most challenges (a proxy
    for most games managed). Series indexed by team code."""
    best: dict[str, tuple[str, int]] = {}
    for team, mgr, ch, _ov in _managers_rows(season):
        if team not in best or ch > best[team][1]:
            best[team] = (mgr, ch)
    return pd.Series({t: v[0] for t, v in best.items()}, name="manager")


# --------------------------------------------------------------------------- #
# Manual CSV inputs (payroll, projections, replay, optional mwpa/bullpen).
# --------------------------------------------------------------------------- #
def load_manual(kind: str, season: int) -> pd.DataFrame | None:
    """Load data/manual/<kind>_<season>.csv, normalizing its team column.

    Returns None (not an error) when the file is absent so the pipeline can
    still run on whatever feeds are present.
    """
    path = os.path.join(MANUAL_DIR, f"{kind}_{season}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    team_col = _first_col(df, "team", "tm", "club")
    if team_col is None:
        raise ValueError(f"{path} has no team column (expected 'team').")
    df["team"] = df[team_col].map(normalize_team)
    df = df.dropna(subset=["team"]).set_index("team")
    return df
