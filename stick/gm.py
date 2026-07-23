"""S.T.I.C.K. — the GM (front-office) metric.

Composite of three league-standardized components:

    S.T.I.C.K. = 0.50*Z(ST) + 0.30*Z(IC) + 0.20*Z(K)

  ST  Surplus Talent     (roster WAR x $/WAR) - active payroll
  IC  Injury Control      actual WAR of the projected roster / projected WAR
  K   Knowledge / Depth   Z(depth WAR, players 26-40) + Z(bullpen strength)

WAR is Baseball-Reference bWAR (via pybaseball). Payroll (RosterResource) and
preseason projections (ZiPS/Steamer) have no open feed and load from
data/manual/*.csv. When those files are absent the affected component drops
out and the remaining weights renormalize.
"""

from __future__ import annotations

import pandas as pd

from . import fetch
from .zscore import zscore

WEIGHTS = {"ST": 0.50, "IC": 0.30, "K": 0.20}

# Open-market cost per 1.0 WAR (dollars). Adjust for market inflation.
DOLLARS_PER_WAR = 9_500_000

# A pitcher counts as a reliever when at least this share of his innings came
# in relief.
RELIEF_THRESHOLD = 0.5


def roster_war(season: int) -> pd.Series:
    """Total team bWAR = position players + pitchers."""
    players = fetch.bref_war(season)
    if players.empty:
        return pd.Series(dtype=float, name="roster_war")
    out = players.groupby("team")["war"].sum()
    out.name = "roster_war"
    return out


def surplus_talent(season: int) -> pd.Series:
    """(roster WAR x $/WAR) - active payroll, in dollars.

    Payroll comes from data/manual/payroll_<season>.csv (columns: team,
    payroll). Without it, ST is unavailable.
    """
    war = roster_war(season)
    pay = fetch.load_manual("payroll", season)
    if pay is None:
        return pd.Series(dtype=float, name="ST")
    pcol = fetch._first_col(pay, "payroll", "active_payroll", "salary")
    if pcol is None:
        return pd.Series(dtype=float, name="ST")
    # A 0 payroll means the template hasn't been filled yet -> treat as missing
    # so ST drops out cleanly rather than masquerading as pure roster WAR.
    payroll = pd.to_numeric(pay[pcol], errors="coerce")
    payroll = payroll.where(payroll > 0)
    st = (war * DOLLARS_PER_WAR) - payroll
    st.name = "ST"
    return st


def injury_control(season: int) -> pd.Series:
    """Actual cumulative WAR of the preseason-projected roster / projected WAR.

    Both numbers come from data/manual/projections_<season>.csv (columns:
    team, projected_war, actual_war). Near 1.0 means the club got the season
    it was projected; below 1.0 flags durability losses.
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
        # 0 projected -> template unfilled -> missing (drops out).
        out = actual / projected.where(projected > 0)
    else:
        return pd.Series(dtype=float, name="IC")
    out.name = "IC"
    return out


def depth_war(season: int, lo: int = 26, hi: int = 40) -> pd.Series:
    """Summed bWAR of each club's Nth-through-Mth most valuable players.

    Players 1-25 are the active roster; 26-40 are the depth that separates a
    club that survives injuries from one that doesn't.
    """
    players = fetch.bref_war(season)
    if players.empty:
        return pd.Series(dtype=float, name="depth_war")
    result = {}
    for team, grp in players.groupby("team"):
        ranked = grp.sort_values("war", ascending=False).reset_index(drop=True)
        result[team] = ranked.iloc[lo - 1:hi]["war"].sum()
    return pd.Series(result, name="depth_war")


def bullpen_strength(season: int) -> pd.Series:
    """Relief-pitching value per team (summed bWAR of relievers).

    A live stand-in for "bullpen Pitching+". Override with a
    data/manual/bullpen_<season>.csv (columns: team, bullpen) for a truer
    figure.
    """
    override = fetch.load_manual("bullpen", season)
    if override is not None:
        bcol = fetch._first_col(override, "bullpen", "pitching_plus", "bullpen_plus")
        if bcol is not None:
            out = pd.to_numeric(override[bcol], errors="coerce")
            out.name = "bullpen"
            return out

    players = fetch.bref_war(season)
    if players.empty:
        return pd.Series(dtype=float, name="bullpen")
    relievers = players[(players["is_pitcher"]) &
                        (players["relief_share"] >= RELIEF_THRESHOLD)]
    out = relievers.groupby("team")["war"].sum()
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
    # Always expose live roster WAR for context, even when ST/IC are dormant.
    raw.insert(0, "roster_war", roster_war(season).reindex(fetch.TEAMS))

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
