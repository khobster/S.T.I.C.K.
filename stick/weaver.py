"""W.E.A.V.E.R. — the manager metric.

Composite of four league-standardized components:

    W.E.A.V.E.R. = 0.40*Z(PV) + 0.35*Z(mWPA) + 0.15*Z(LOF) + 0.10*Z(RSR)

  PV   Pythagorean Variance   games stolen/blown vs. run differential
  mWPA Manager Win Prob Added bullpen deployment, context stripped out
  LOF  Lineup Optimization    share of team PAs given to the best hitters
  RSR  Replay Success Rate    overturn rate on manager challenges

Data note: PV and LOF pull live from MLB StatsAPI. mWPA needs FanGraphs
WPA/LI (Cloudflare-blocked, no open substitute) and RSR needs the replay
dashboard, so both come from manual CSVs when available; otherwise they drop
out and the remaining weights renormalize.
"""

from __future__ import annotations

import pandas as pd

from . import fetch
from .zscore import zscore

WEIGHTS = {"PV": 0.40, "mWPA": 0.35, "LOF": 0.15, "RSR": 0.10}


def pythagorean_variance(season: int, exponent: float = 2.0) -> pd.Series:
    """Actual wins minus Pythagorean expectation. Positive = outperformed."""
    st = fetch.standings(season)
    rs = st["RS"].astype(float)
    ra = st["RA"].astype(float)
    games = st["G"].astype(float)
    denom = rs.pow(exponent) + ra.pow(exponent)
    pyth_wins = games * (rs.pow(exponent) / denom.where(denom > 0))
    pv = st["W"].astype(float) - pyth_wins
    pv.name = "PV"
    return pv


def manager_wpa(season: int) -> pd.Series:
    """Bullpen leverage-deployment value per team.

    The exact metric is the reliever sum of (WPA - WPA/LI), which isolates the
    leverage a manager chose to deploy from the pitcher's context-neutral
    value. WPA/LI is FanGraphs-only and FanGraphs is Cloudflare-blocked, so we
    use a Baseball-Reference proxy with the same intent and sign:

        mWPA_proxy = SUM over relievers ( (avg_entry_leverage - 1) * WAA )

    A manager scores positive for putting above-average relievers (WAA > 0)
    into above-average leverage (LI > 1), and negative for burning high-leverage
    innings on struggling arms. Supply a data/manual/mwpa_<season>.csv
    (columns: team, mwpa) with true FanGraphs values to override the proxy.
    """
    man = fetch.load_manual("mwpa", season)
    if man is not None:
        col = fetch._first_col(man, "mwpa", "mWPA")
        if col is not None:
            out = pd.to_numeric(man[col], errors="coerce")
            out.name = "mWPA"
            return out

    rel = fetch.bref_relievers(season)
    if rel.empty:
        return pd.Series(dtype=float, name="mWPA")
    contrib = (rel["li"] - 1.0) * rel["waa"]
    out = contrib.groupby(rel["team"]).sum()
    out.name = "mWPA"
    return out


def lineup_optimization(season: int, min_pa: int = 100) -> pd.Series:
    """Share of team plate appearances handled by its four best hitters.

    "Best" = top four by OBP+SLG among batters with at least `min_pa` PAs, to
    keep small-sample cameos out of the ranking. High LOF means the manager
    funneled bats to his best on-base/slugging threats.
    """
    players = fetch.player_hitting(season)
    team_tot = fetch.team_hitting(season)["PA"]
    if players.empty or team_tot.empty:
        return pd.Series(dtype=float, name="LOF")

    players = players.copy()
    players["_ops"] = players["OBP"] + players["SLG"]

    result = {}
    for team, grp in players.groupby("team"):
        total = float(team_tot.get(team, grp["PA"].sum()))
        regulars = grp[grp["PA"] >= min_pa]
        top4 = regulars.sort_values("_ops", ascending=False).head(4)
        if total > 0 and len(top4) > 0:
            result[team] = top4["PA"].sum() / total
    return pd.Series(result, name="LOF")


def replay_success(season: int) -> pd.Series:
    """Successful challenges / total challenges (overturn rate) per team.

    Pulls live from Baseball-Reference's season managers page. A
    data/manual/replay_<season>.csv with non-zero totals (columns: team,
    successful_challenges, total_challenges, or a precomputed rsr) overrides
    the live scrape.
    """
    man = fetch.load_manual("replay", season)
    if man is not None:
        cols = {c.lower(): c for c in man.columns}
        if "rsr" in cols:
            out = pd.to_numeric(man[cols["rsr"]], errors="coerce")
            if out.notna().any():
                out.name = "RSR"
                return out
        elif "successful_challenges" in cols and "total_challenges" in cols:
            succ = pd.to_numeric(man[cols["successful_challenges"]], errors="coerce")
            total = pd.to_numeric(man[cols["total_challenges"]], errors="coerce")
            if total.gt(0).any():          # real data, not a zero template
                out = succ / total.where(total > 0)
                out.name = "RSR"
                return out

    live = fetch.replay_challenges(season)
    if live.empty:
        return pd.Series(dtype=float, name="RSR")
    out = live["successful"] / live["total"].where(live["total"] > 0)
    out.name = "RSR"
    return out


def compute(season: int, weights: dict | None = None) -> pd.DataFrame:
    """Build the full W.E.A.V.E.R. table for every club with data.

    Weights renormalize across whichever components actually have data, so a
    missing mWPA or RSR reweights the remaining components cleanly instead of
    silently zeroing them.
    """
    w = dict(weights or WEIGHTS)
    components = {
        "PV": pythagorean_variance(season),
        "mWPA": manager_wpa(season),
        "LOF": lineup_optimization(season),
        "RSR": replay_success(season),
    }
    raw = pd.DataFrame(components).reindex(fetch.TEAMS)

    z = pd.DataFrame({f"z_{k}": zscore(raw[k]) for k in components})

    present = [k for k in w if raw[k].notna().any()]
    wsum = sum(w[k] for k in present) or 1.0
    score = sum((w[k] / wsum) * z[f"z_{k}"].fillna(0.0) for k in present)

    out = raw.join(z)
    out["WEAVER"] = score
    out = out.sort_values("WEAVER", ascending=False)
    out.index.name = "team"
    return out
