"""W.E.A.V.E.R. — the manager metric.

Composite of four league-standardized components:

    W.E.A.V.E.R. = 0.40*Z(PV) + 0.35*Z(mWPA) + 0.15*Z(LOF) + 0.10*Z(RSR)

  PV   Pythagorean Variance   games stolen/blown vs. run differential
  mWPA Manager Win Prob Added bullpen deployment, context stripped out
  LOF  Lineup Optimization    share of team PAs given to the best hitters
  RSR  Replay Success Rate    overturn rate on manager challenges
"""

from __future__ import annotations

import pandas as pd

from . import fetch
from .zscore import zscore

WEIGHTS = {"PV": 0.40, "mWPA": 0.35, "LOF": 0.15, "RSR": 0.10}


def _by_team(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a canonical 'team' code and drop rows we can't map."""
    tcol = fetch._first_col(df, "Team", "Tm", "team")
    if tcol is None:
        raise ValueError("no team column found in FanGraphs frame")
    out = df.copy()
    out["team"] = out[tcol].map(fetch.normalize_team)
    return out.dropna(subset=["team"])


def pythagorean_variance(season: int, exponent: float = 2.0) -> pd.Series:
    """Actual wins minus Pythagorean expectation. Positive = outperformed."""
    bat = _by_team(fetch.team_batting(season))
    pit = _by_team(fetch.team_pitching(season))

    rs = bat.set_index("team")[fetch._first_col(bat, "R")]           # runs scored
    ra = pit.set_index("team")[fetch._first_col(pit, "R")]           # runs allowed
    w = pit.set_index("team")[fetch._first_col(pit, "W")].astype(float)
    l = pit.set_index("team")[fetch._first_col(pit, "L")].astype(float)

    games = w + l
    denom = rs.pow(exponent) + ra.pow(exponent)
    pyth_wins = games * (rs.pow(exponent) / denom)
    pv = w - pyth_wins
    pv.name = "PV"
    return pv


def manager_wpa(season: int) -> pd.Series:
    """Reliever-only sum of (WPA - WPA/LI), grouped by team.

    Subtracting the context-neutral WPA/LI strips out how good the pitcher was
    and leaves the leverage the manager chose to deploy him in. Season tables
    don't isolate relief-only WPA for swingmen, so we classify a pitcher as a
    reliever when at least half his appearances came in relief -- an
    approximation of bullpen usage, not a perfect split.
    """
    p = _by_team(fetch.pitching_stats(season))
    g = fetch._first_col(p, "G")
    gs = fetch._first_col(p, "GS")
    wpa = fetch._first_col(p, "WPA")
    wpa_li = fetch._first_col(p, "WPA/LI", "WPA_LI", "WPALI")
    if not all([g, gs, wpa, wpa_li]):
        return pd.Series(dtype=float, name="mWPA")

    appearances = p[g].astype(float)
    starts = p[gs].astype(float)
    relief_share = (appearances - starts) / appearances.where(appearances > 0)
    relievers = p[relief_share >= 0.5].copy()

    relievers["_mwpa"] = relievers[wpa].astype(float) - relievers[wpa_li].astype(float)
    out = relievers.groupby("team")["_mwpa"].sum()
    out.name = "mWPA"
    return out


def lineup_optimization(season: int, min_pa: int = 100) -> pd.Series:
    """Share of team plate appearances handled by its four best hitters.

    "Best" = top four by OBP+SLG among batters with at least `min_pa` PAs, to
    keep small-sample .400-OBP cameos out of the ranking. High LOF means the
    manager funneled bats to his best on-base/slugging threats.
    """
    b = _by_team(fetch.batting_stats(season))
    pa = fetch._first_col(b, "PA")
    obp = fetch._first_col(b, "OBP")
    slg = fetch._first_col(b, "SLG")
    if not all([pa, obp, slg]):
        return pd.Series(dtype=float, name="LOF")

    b = b.copy()
    b[pa] = b[pa].astype(float)
    b["_ops"] = b[obp].astype(float) + b[slg].astype(float)

    result = {}
    for team, grp in b.groupby("team"):
        team_pa = grp[pa].sum()
        regulars = grp[grp[pa] >= min_pa]
        top4 = regulars.sort_values("_ops", ascending=False).head(4)
        if team_pa > 0 and len(top4) > 0:
            result[team] = top4[pa].sum() / team_pa
    out = pd.Series(result, name="LOF")
    return out


def replay_success(season: int) -> pd.Series:
    """Successful challenges / total challenges, from the manual replay CSV.

    Expected columns: team, successful_challenges, total_challenges
    (or a precomputed rsr column). Returns an empty Series if the file is
    absent so RSR simply drops out of the composite.
    """
    man = fetch.load_manual("replay", season)
    if man is None:
        return pd.Series(dtype=float, name="RSR")
    cols = {c.lower(): c for c in man.columns}
    if "rsr" in cols:
        out = man[cols["rsr"]].astype(float)
    elif "successful_challenges" in cols and "total_challenges" in cols:
        succ = man[cols["successful_challenges"]].astype(float)
        total = man[cols["total_challenges"]].astype(float)
        out = succ / total.where(total > 0)
    else:
        return pd.Series(dtype=float, name="RSR")
    out.name = "RSR"
    return out


def compute(season: int, weights: dict | None = None) -> pd.DataFrame:
    """Build the full W.E.A.V.E.R. table for every club with data.

    Weights are renormalized across whichever components actually have data,
    so a missing RSR (no replay CSV) reweights the remaining three cleanly
    instead of silently zeroing them.
    """
    w = dict(weights or WEIGHTS)
    components = {
        "PV": pythagorean_variance(season),
        "mWPA": manager_wpa(season),
        "LOF": lineup_optimization(season),
        "RSR": replay_success(season),
    }
    raw = pd.DataFrame(components)
    raw = raw.reindex(fetch.TEAMS)

    z = pd.DataFrame({f"z_{k}": zscore(raw[k]) for k in components})

    present = [k for k in w if raw[k].notna().any()]
    wsum = sum(w[k] for k in present) or 1.0
    score = sum((w[k] / wsum) * z[f"z_{k}"].fillna(0.0) for k in present)

    out = raw.join(z)
    out["WEAVER"] = score
    out = out.sort_values("WEAVER", ascending=False)
    out.index.name = "team"
    return out
