"""S.T.I.C.K. — the GM (front-office) metric.

Composite of three league-standardized components:

    S.T.I.C.K. = 0.50*Z(ST) + 0.30*Z(IC) + 0.20*Z(K)

  ST  Surplus Talent     (roster WAR x $/WAR) - active payroll
  IC  Injury Control      actual WAR of the projected roster / projected WAR
  K   Knowledge / Depth   Z(depth WAR, players 26-40) + Z(bullpen strength)

ST needs a live payroll and K's projections/depth need player-level WAR.
Payroll (RosterResource) and preseason projections (ZiPS/Steamer) are not in
pybaseball, so they come from data/manual/*.csv. When those files are absent
the affected component drops out and the remaining weights renormalize.
"""

from __future__ import annotations

import pandas as pd

from . import fetch
from .zscore import zscore

WEIGHTS = {"ST": 0.50, "IC": 0.30, "K": 0.20}

# Open-market cost per 1.0 WAR (dollars). Adjust for market inflation.
DOLLARS_PER_WAR = 9_500_000


def _player_war_frame(season: int) -> pd.DataFrame:
    """One row per player with columns: team, war."""
    frames = []
    for loader in (fetch.batting_stats, fetch.pitching_stats):
        df = loader(season)
        tcol = fetch._first_col(df, "Team", "Tm", "team")
        wcol = fetch._first_col(df, "WAR")
        if tcol is None or wcol is None:
            continue
        sub = pd.DataFrame({
            "team": df[tcol].map(fetch.normalize_team),
            "war": pd.to_numeric(df[wcol], errors="coerce"),
        }).dropna(subset=["team"])
        frames.append(sub)
    if not frames:
        return pd.DataFrame(columns=["team", "war"])
    return pd.concat(frames, ignore_index=True)


def roster_war(season: int) -> pd.Series:
    """Total team WAR = position-player WAR + pitcher WAR."""
    def _team_war(df):
        d = df.copy()
        tcol = fetch._first_col(d, "Team", "Tm", "team")
        wcol = fetch._first_col(d, "WAR")
        d["team"] = d[tcol].map(fetch.normalize_team)
        return d.dropna(subset=["team"]).groupby("team")[wcol].sum()

    bat = _team_war(fetch.team_batting(season))
    pit = _team_war(fetch.team_pitching(season))
    total = bat.add(pit, fill_value=0.0)
    total.name = "roster_war"
    return total


def surplus_talent(season: int) -> pd.Series:
    """(roster WAR x $/WAR) - active payroll, in dollars.

    Payroll comes from data/manual/payroll_<season>.csv
    (columns: team, payroll). Without it, ST is unavailable.
    """
    war = roster_war(season)
    pay = fetch.load_manual("payroll", season)
    if pay is None:
        return pd.Series(dtype=float, name="ST")
    pcol = fetch._first_col(pay, "payroll", "active_payroll", "salary")
    if pcol is None:
        return pd.Series(dtype=float, name="ST")
    payroll = pd.to_numeric(pay[pcol], errors="coerce")
    st = (war * DOLLARS_PER_WAR) - payroll
    st.name = "ST"
    return st


def injury_control(season: int) -> pd.Series:
    """Actual cumulative WAR of the preseason-projected roster / projected WAR.

    Both numbers come from data/manual/projections_<season>.csv
    (columns: team, projected_war, actual_war). A value near 1.0 means the
    club got the season it was supposed to; below 1.0 flags durability losses.
    """
    proj = fetch.load_manual("projections", season)
    if proj is None:
        return pd.Series(dtype=float, name="IC")
    cols = {c.lower(): c for c in proj.columns}
    if "ic" in cols:
        out = pd.to_numeric(proj[cols["ic"]], errors="coerce")
    elif "actual_war" in cols and "projected_war" in cols:
        actual = pd.to_numeric(proj[cols["actual_war"]], errors="coerce")
        projected = pd.to_numeric(proj[cols["projected_war"]], errors="coerce")
        out = actual / projected.where(projected != 0)
    else:
        return pd.Series(dtype=float, name="IC")
    out.name = "IC"
    return out


def depth_war(season: int, lo: int = 26, hi: int = 40) -> pd.Series:
    """Summed WAR of each club's Nth-through-Mth most valuable players.

    Players 1-25 are the active roster; 26-40 are the depth that separates a
    club that survives injuries from one that doesn't.
    """
    players = _player_war_frame(season)
    if players.empty:
        return pd.Series(dtype=float, name="depth_war")
    result = {}
    for team, grp in players.groupby("team"):
        ranked = grp.sort_values("war", ascending=False).reset_index(drop=True)
        # 1-indexed ranks lo..hi -> iloc slice [lo-1 : hi]
        result[team] = ranked.iloc[lo - 1:hi]["war"].sum()
    out = pd.Series(result, name="depth_war")
    return out


def bullpen_strength(season: int) -> pd.Series:
    """Relief-pitching value per team (reliever WAR sum).

    A live stand-in for "bullpen Pitching+". Override with a
    data/manual/bullpen_<season>.csv (columns: team, bullpen) if you have a
    truer Pitching+ figure.
    """
    override = fetch.load_manual("bullpen", season)
    if override is not None:
        bcol = fetch._first_col(override, "bullpen", "pitching_plus", "bullpen_plus")
        if bcol is not None:
            out = pd.to_numeric(override[bcol], errors="coerce")
            out.name = "bullpen"
            return out

    p = fetch.pitching_stats(season)
    tcol = fetch._first_col(p, "Team", "Tm", "team")
    g = fetch._first_col(p, "G")
    gs = fetch._first_col(p, "GS")
    war = fetch._first_col(p, "WAR")
    if not all([tcol, g, gs, war]):
        return pd.Series(dtype=float, name="bullpen")
    d = p.copy()
    d["team"] = d[tcol].map(fetch.normalize_team)
    d = d.dropna(subset=["team"])
    appearances = d[g].astype(float)
    relief_share = (appearances - d[gs].astype(float)) / appearances.where(appearances > 0)
    relievers = d[relief_share >= 0.5]
    out = relievers.groupby("team")[war].apply(lambda s: pd.to_numeric(s, errors="coerce").sum())
    out.name = "bullpen"
    return out


def knowledge_depth(season: int) -> pd.Series:
    """K = Z(depth WAR) + Z(bullpen strength). Sum of two z-scores."""
    depth = depth_war(season).reindex(fetch.TEAMS)
    pen = bullpen_strength(season).reindex(fetch.TEAMS)
    k = zscore(depth) + zscore(pen)
    k.name = "K"
    return k


def compute(season: int, weights: dict | None = None) -> pd.DataFrame:
    """Build the full S.T.I.C.K. table for every club with data.

    As in W.E.A.V.E.R., weights renormalize across whichever components have
    data so a missing payroll or projection file doesn't zero a GM's score.
    """
    w = dict(weights or WEIGHTS)
    components = {
        "ST": surplus_talent(season),
        "IC": injury_control(season),
        "K": knowledge_depth(season),
    }
    raw = pd.DataFrame({k: v for k, v in components.items()}).reindex(fetch.TEAMS)

    # K is already a sum of z-scores; standardize it again so it shares the
    # same scale as Z(ST) and Z(IC) in the weighted composite.
    z = pd.DataFrame({
        "z_ST": zscore(raw["ST"]),
        "z_IC": zscore(raw["IC"]),
        "z_K": zscore(raw["K"]),
    })

    present = [k for k in w if raw[k].notna().any()]
    wsum = sum(w[k] for k in present) or 1.0
    score = sum((w[k] / wsum) * z[f"z_{k}"].fillna(0.0) for k in present)

    out = raw.join(z)
    out["STICK"] = score
    out = out.sort_values("STICK", ascending=False)
    out.index.name = "team"
    return out
