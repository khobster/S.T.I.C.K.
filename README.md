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

Season tables are **cumulative season-to-date**, so "2026 through today" is just
the current season — no date range to specify.

> **FanGraphs is off the table.** It now sits behind a Cloudflare bot challenge
> that returns `403` to any script (and to CI runners). So this project pulls
> from two sources that answer scripts cleanly:
>
> - **MLB StatsAPI** (`statsapi.mlb.com`) — open, no key: standings (RS/RA/W),
>   team & player hitting (PA/OBP/SLG).
> - **Baseball-Reference** bWAR via [`pybaseball`](https://github.com/jldbc/pybaseball)
>   (`bwar_bat` / `bwar_pitch`) — WAR for every player, plus relief splits.

| Input | Source | Status |
|-------|--------|--------|
| PV (RS / RA / W) | MLB StatsAPI standings | **live** |
| LOF (PA / OBP / SLG) | MLB StatsAPI hitting | **live** |
| RSR (replay overturn rate) | Baseball-Reference managers page | **live** (override via CSV) |
| mWPA (leverage deployment) | Baseball-Reference reliever LI × WAA | **live proxy** (override via CSV) |
| Roster & depth WAR | Baseball-Reference bWAR | **live** |
| Bullpen strength | reliever bWAR (relief-innings split) | **live** (override via CSV) |
| K (depth + bullpen) | Baseball-Reference bWAR | **live** |
| **Payroll** (ST) | AP Opening Day (RosterResource/Spotrac blocked) | **manual CSV — filled 2026** |
| **Projections** (IC) | preseason projected wins → WAR | **manual CSV — filled 2026** |

Both boards now run on real data across every component. The only inputs that
aren't a live API pull are the two point-in-time figures — Opening Day payroll
(ST) and preseason projections (IC) — which are filled for 2026 in
`data/manual/`. Anything unfilled isn't fatal: that component **drops out** and
the remaining weights **renormalize**, so the board always ranks every club it
has data for.

> **mWPA is a proxy, not the exact metric.** The formula's `WPA − WPA/LI` is
> FanGraphs-only (blocked), so mWPA uses a Baseball-Reference stand-in —
> `Σ relievers (avg_entry_leverage − 1) × WAA` — which rewards a manager for
> putting effective relievers into high-leverage innings. Drop a
> `mwpa_<year>.csv` with true FanGraphs values in to override it.

### Manual CSV templates

- `data/manual/payroll_<year>.csv` — `team,payroll` (**required for ST**)
- `data/manual/projections_<year>.csv` — `team,projected_war` (**required for IC**;
  `actual_war` is pulled live — leave it `0`)
- `data/manual/replay_<year>.csv` — `team,successful_challenges,total_challenges`
  (optional override; RSR is otherwise scraped live)
- `data/manual/mwpa_<year>.csv` — `team,mwpa` (optional override; true FanGraphs WPA−WPA/LI)
- `data/manual/bullpen_<year>.csv` — `team,bullpen` (optional Pitching+ override)

A `0` in the payroll or projection templates counts as "not filled yet" and
that component stays dormant.

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

Output lands in `data/output/{weaver,stick}_<season>.{csv,json}` plus a
`manifest.json` the scoreboard reads. A GitHub Actions cron
(`.github/workflows/leaderboard.yml`) rebuilds and commits the boards **weekly**
(Mondays).

## Scoreboard

`index.html` is a self-contained scoreboard (no build step) that reads the JSON
output and ranks every manager by W.E.A.V.E.R. and every GM by S.T.I.C.K., with
each metric's components shown as chips. Served via GitHub Pages from the repo
root, so the weekly cron commit refreshes it automatically. Manager names are
live from Baseball-Reference; GM names come from the editable map in
`stick/people.py`.

---

## Layout

```
stick/
  zscore.py   league-relative standardization
  fetch.py    StatsAPI + Baseball-Reference pulls, team normalization, CSV loader
  weaver.py   manager metric (PV, mWPA, LOF, RSR)
  gm.py       GM metric (ST, IC, K)
run.py        CLI leaderboard builder
data/manual   payroll / projections / replay inputs (you fill these)
data/output   generated leaderboards
```

## Notes on the honest edges

- **mWPA** can't be computed exactly (WPA/LI is FanGraphs-only, blocked), so it
  runs as a Baseball-Reference proxy — `Σ relievers (entry_leverage − 1) × WAA`.
  Same intent and sign as the real metric; override with `mwpa_<year>.csv` if
  you get true FanGraphs numbers.
- **RSR** is scraped live from Baseball-Reference's managers page and summed
  across a team's managers when there's a mid-season change.
- **Bullpen strength** classifies a reliever by relief-innings share (≥50% of
  innings in relief) and uses reliever bWAR as a live stand-in for "Bullpen
  Pitching+"; drop a real Pitching+ figure into `bullpen_<year>.csv` to replace it.
- **Weights** are a defensible baseline, not gospel — they're one edit away.
