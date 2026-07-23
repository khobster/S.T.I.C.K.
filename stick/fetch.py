"""Live data ingestion via pybaseball, plus manual-CSV fallbacks.

pybaseball legally pings FanGraphs, Baseball-Reference and Baseball Savant.
It cleanly supplies the Pythagorean inputs, win-probability/leverage data and
WAR. It does NOT supply three things this project needs:

    * replay / ABS challenge success rate   -> data/manual/replay_<year>.csv
    * live 40-man payroll (RosterResource)  -> data/manual/payroll_<year>.csv
    * preseason ZiPS/Steamer projections    -> data/manual/projections_<year>.csv

Every live fetch is wrapped so that one missing feed degrades that single
component to NaN rather than killing the whole leaderboard.
"""

from __future__ import annotations

import os
from functools import lru_cache

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MANUAL_DIR = os.path.join(DATA_DIR, "manual")

# Canonical 3-letter codes for all 30 clubs.
TEAMS = [
    "ARI", "ATL", "BAL", "BOS", "CHC", "CHW", "CIN", "CLE", "COL", "DET",
    "HOU", "KCR", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
    "PHI", "PIT", "SDP", "SEA", "SFG", "STL", "TBR", "TEX", "TOR", "WSN",
]

# Broad alias table so FanGraphs / BBRef / Savant name variants all collapse
# to one canonical code.
_ALIASES = {
    "ari": "ARI", "arizona": "ARI", "diamondbacks": "ARI", "d-backs": "ARI",
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
    "oak": "OAK", "athletics": "OAK", "a's": "OAK", "ath": "OAK",
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


# --------------------------------------------------------------------------- #
# Live pybaseball pulls (each cached for the process lifetime).
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=8)
def team_batting(season: int) -> pd.DataFrame:
    from pybaseball import team_batting  # imported lazily so the pkg loads without it
    return team_batting(season)


@lru_cache(maxsize=8)
def team_pitching(season: int) -> pd.DataFrame:
    from pybaseball import team_pitching
    return team_pitching(season)


@lru_cache(maxsize=8)
def batting_stats(season: int) -> pd.DataFrame:
    from pybaseball import batting_stats
    # qual=0 -> every batter, so we can rank depth and find top hitters.
    return batting_stats(season, qual=0)


@lru_cache(maxsize=8)
def pitching_stats(season: int) -> pd.DataFrame:
    from pybaseball import pitching_stats
    return pitching_stats(season, qual=0)


# --------------------------------------------------------------------------- #
# Manual CSV inputs (payroll, projections, replay).
# --------------------------------------------------------------------------- #
def load_manual(kind: str, season: int) -> pd.DataFrame | None:
    """Load data/manual/<kind>_<season>.csv, normalizing its team column.

    Returns None (not an error) when the file is absent so the pipeline can
    still run on the live-only components.
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
