"""League-relative standardization.

Every raw input in W.E.A.V.E.R. and S.T.I.C.K. is measured in a different
unit, so we convert each to a z-score before weighting:

    Z = (value - league_average) / standard_deviation

A z-score says how many standard deviations a club is above (+) or below (-)
the 30-team mean for that input.
"""

from __future__ import annotations

import pandas as pd


def zscore(series: pd.Series) -> pd.Series:
    """Return the population z-score of a numeric series.

    NaNs are ignored when computing the mean/std and are preserved in the
    output. If the series has zero variance (or fewer than two real values),
    every entry standardizes to 0.0 so a flat input never dominates a
    composite.
    """
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if len(valid) < 2:
        return pd.Series(0.0, index=series.index)
    mean = valid.mean()
    # Population standard deviation (ddof=0): we have the whole league, not a
    # sample of it.
    std = valid.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (s - mean) / std
