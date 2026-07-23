# S.T.I.C.K.

Front-office and dugout analytics for all 30 MLB clubs — two composite metrics
that grade the two decision-makers a box score never credits: the **GM** and the
**manager**.

- **S.T.I.C.K.** — the GM metric (roster building, cost efficiency, depth).
- **W.E.A.V.E.R.** — the manager metric (in-game tactics, bullpen, lineup, replay).

Both roll up inputs measured in different units (runs, dollars, WAR, percentages),
so every input is first converted to a **z-score** before it's weighted:

```
Z = (value − league_average) / standard_deviation
```

A z-score is how many standard deviations a club sits above (+) or below (−) the
30-team average for that input. Weighted z-scores share one scale, so they add up
honestly.

---

## W.E.A.V.E.R. — the manager metric

```
W.E.A.V.E.R. = 0.40·Z(PV) + 0.35·Z(mWPA) + 0.15·Z(LOF) + 0.10·Z(RSR)
```

The baseline weights value run-differential variance and high-leverage bullpen
usage the most; edit `stick/weaver.py::WEIGHTS` to retune.

**1. Pythagorean Variance (PV)** — games "stolen" or "blown" vs. run differential.

```
Pythagorean Wins = Games × ( RS² / (RS² + RA²) )
PV               = Actual Wins − Pythagorean Wins
```

**2. Manager Win Probability Added (mWPA)** — bullpen deployment with the
pitcher's context-neutral performance stripped out.

```
mWPA = Σ over relievers ( WPA − WPA/LI )
```

**3. Lineup Optimization Factor (LOF)** — share of team PAs given to the four
best OBP/SLG hitters.

```
LOF = PA(top 4 OBP/SLG hitters) / total team PA
```

**4. Replay Success Rate (RSR)** — challenge overturn rate.

```
RSR = Successful Challenges / Total Challenges
```

---

## S.T.I.C.K. — the GM metric

```
S.T.I.C.K. = 0.50·Z(ST) + 0.30·Z(IC) + 0.20·Z(K)
```

**1. Surplus Talent (ST)** — WAR bought vs. dollars spent, at ~$9.5M / 1.0 WAR
(edit `stick/gm.py::DOLLARS_PER_WAR` for market inflation).

```
ST = (Total Roster WAR × $9,500,000) − Active Team Payroll
```

**2. Injury Control (IC)** — the "Alonso vs. Polanco" durability index.

```
IC = Actual cumulative WAR of the preseason-projected roster / Preseason Projected WAR
```

**3. Knowledge / Depth (K)** — organizational depth beyond the active roster.

```
K = Z(Depth WAR, players 26–40) + Z(Bullpen strength)
```

---

## Live data feed

Powered by [`pybaseball`](https://github.com/jldbc/pybaseball), which legally
pings FanGraphs, Baseball-Reference, and Baseball Savant (Statcast). No scraping
you have to maintain by hand.

| Input | Source | Status |
|-------|--------|--------|
| PV (RS / RA / W) | `team_batting`, `team_pitching` | **live** |
| mWPA (WPA, WPA/LI) | `pitching_stats`, reliever split | **live** (approx. — season tables don't isolate relief-only WPA for swingmen) |
| LOF (PA / OBP / SLG) | `batting_stats` | **live** |
| Roster & depth WAR | `team_*` + player `*_stats` | **live** |
| Bullpen strength | reliever WAR (stand-in for Pitching+) | **live** (override via CSV) |
| **RSR** (replay/ABS) | Savant challenge dashboard | **manual CSV** — not in pybaseball |
| **Payroll** (ST) | FanGraphs RosterResource | **manual CSV** — not in pybaseball |
| **Projections** (IC) | ZiPS / Steamer preseason | **manual CSV** — not in pybaseball |

Anything without a live feed is read from `data/manual/*.csv` (templates provided,
zero-filled). Missing an input isn't fatal: that component drops out of the
composite and the remaining weights **renormalize**, so the board always ranks
every club it has data for.

### Manual CSV templates

- `data/manual/payroll_<year>.csv` — `team,payroll`
- `data/manual/projections_<year>.csv` — `team,projected_war,actual_war`
- `data/manual/replay_<year>.csv` — `team,successful_challenges,total_challenges`
- `data/manual/bullpen_<year>.csv` — `team,bullpen` (optional Pitching+ override)

Team codes are the 30 canonical three-letter abbreviations (e.g. `NYM`, `LAD`);
the loader also accepts full names and common variants.

---

## Usage

```bash
pip install -r requirements.txt

python run.py                  # both boards, current season, writes JSON + CSV
python run.py --season 2025    # a specific season
python run.py --metric weaver  # managers only
python run.py --no-write       # print only
```

Output lands in `data/output/{weaver,stick}_<season>.{csv,json}`. A GitHub Actions
cron (`.github/workflows/leaderboard.yml`) rebuilds and commits the boards daily.

---

## Layout

```
stick/
  zscore.py   league-relative standardization
  fetch.py    pybaseball pulls + team-name normalization + manual CSV loader
  weaver.py   manager metric (PV, mWPA, LOF, RSR)
  gm.py       GM metric (ST, IC, K)
run.py        CLI leaderboard builder
data/manual   payroll / projections / replay inputs (you fill these)
data/output   generated leaderboards
```

## Notes on the honest edges

- **mWPA / bullpen** classify a pitcher as a reliever when ≥50% of his
  appearances came in relief; a swingman's WPA blends both roles, so treat this
  as bullpen-usage signal, not a surgical relief-only split.
- **Bullpen strength** uses reliever WAR as a live stand-in for "Bullpen
  Pitching+"; drop a real Pitching+ figure into `bullpen_<year>.csv` to replace it.
- **Weights** are a defensible baseline, not gospel — they're one edit away.
