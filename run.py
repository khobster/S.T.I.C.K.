#!/usr/bin/env python3
"""Build the live S.T.I.C.K. / W.E.A.V.E.R. leaderboards for all 30 clubs.

    python run.py                 # current season, print + write JSON/CSV
    python run.py --season 2025   # a specific season
    python run.py --metric weaver # just the manager board
    python run.py --no-write      # print only, don't touch data/output

Missing feeds degrade gracefully: components with no data drop out and the
remaining weights renormalize, so the board always prints something useful.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os

import pandas as pd

from stick import gm, weaver

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data", "output")


def _default_season() -> int:
    # MLB regular season runs within a calendar year; before April, last year
    # is the most recent complete season to look at.
    today = dt.date.today()
    return today.year if today.month >= 4 else today.year - 1


def _print_board(title: str, df: pd.DataFrame, score_col: str) -> None:
    print(f"\n{title}")
    print("=" * len(title))
    show = df[[score_col]].copy()
    show.insert(0, "rank", range(1, len(show) + 1))
    for team, row in show.iterrows():
        print(f"{int(row['rank']):>2}. {team:<4} {row[score_col]:+.3f}")


def _write(df: pd.DataFrame, metric: str, season: int) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    stamp = dt.date.today().isoformat()
    csv_path = os.path.join(OUTPUT_DIR, f"{metric}_{season}.csv")
    json_path = os.path.join(OUTPUT_DIR, f"{metric}_{season}.json")
    df.round(4).to_csv(csv_path)
    payload = {
        "metric": metric,
        "season": season,
        "generated": stamp,
        "leaderboard": json.loads(df.round(4).reset_index().to_json(orient="records")),
    }
    with open(json_path, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"  wrote {csv_path}")
    print(f"  wrote {json_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=_default_season())
    ap.add_argument("--metric", choices=["stick", "weaver", "both"], default="both")
    ap.add_argument("--no-write", action="store_true", help="print only")
    args = ap.parse_args()

    if args.metric in ("weaver", "both"):
        w = weaver.compute(args.season)
        _print_board(f"W.E.A.V.E.R. — Managers {args.season}", w, "WEAVER")
        if not args.no_write:
            _write(w, "weaver", args.season)

    if args.metric in ("stick", "both"):
        s = gm.compute(args.season)
        _print_board(f"S.T.I.C.K. — GMs {args.season}", s, "STICK")
        if not args.no_write:
            _write(s, "stick", args.season)


if __name__ == "__main__":
    main()
