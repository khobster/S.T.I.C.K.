"""Front-office names for the scoreboard.

Manager names are pulled LIVE from Baseball-Reference (see fetch.team_managers).
GM / head-of-baseball-operations names have no clean live feed, so this is a
hand-maintained reference of each club's top decision-maker. It only affects
the scoreboard label, never the S.T.I.C.K. math. Verify/edit as roles change.
"""

# Manual manager overrides — used when the live feed lags a mid-season change.
# team code -> current manager name. Takes precedence over the BBRef scrape.
MANAGER_OVERRIDES = {
    "NYM": "Andy Green",
}

# Current GM (title-holder) per club (Wikipedia current-GM list, 2026).
# BOS/TBR GM seats are vacant, so their top baseball-ops exec is shown.
GMS = {
    "ARI": "Mike Hazen",
    "ATL": "Alex Anthopoulos",
    "BAL": "Mike Elias",
    "BOS": "Craig Breslow",        # GM seat vacant — Chief Baseball Officer
    "CHC": "Carter Hawkins",
    "CHW": "Chris Getz",
    "CIN": "Brad Meador",
    "CLE": "Mike Chernoff",
    "COL": "Josh Byrnes",
    "DET": "Jeff Greenberg",
    "HOU": "Dana Brown",
    "KCR": "J.J. Picollo",
    "LAA": "Perry Minasian",
    "LAD": "Brandon Gomes",
    "MIA": "Gabe Kapler",
    "MIL": "Matt Arnold",
    "MIN": "Jeremy Zoll",
    "NYM": "David Stearns",
    "NYY": "Brian Cashman",
    "OAK": "David Forst",
    "PHI": "Preston Mattingly",
    "PIT": "Ben Cherington",
    "SDP": "A.J. Preller",
    "SEA": "Justin Hollander",
    "SFG": "Zack Minasian",
    "STL": "Mike Girsch",
    "TBR": "Erik Neander",         # GM seat vacant — President of Baseball Ops
    "TEX": "Ross Fenstermaker",
    "TOR": "Ross Atkins",
    "WSN": "Anirudh Kilambi",
}
