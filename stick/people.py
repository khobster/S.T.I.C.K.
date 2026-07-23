"""Front-office names for the scoreboard.

Manager names are pulled LIVE from Baseball-Reference (see fetch.team_managers).
GM / head-of-baseball-operations names have no clean live feed, so this is a
hand-maintained reference of each club's top decision-maker. It only affects
the scoreboard label, never the S.T.I.C.K. math. Verify/edit as roles change.
"""

# Top baseball-ops decision-maker per club (POBO where one outranks the GM).
GMS = {
    "ARI": "Mike Hazen",
    "ATL": "Alex Anthopoulos",
    "BAL": "Mike Elias",
    "BOS": "Craig Breslow",
    "CHC": "Jed Hoyer",
    "CHW": "Chris Getz",
    "CIN": "Nick Krall",
    "CLE": "Chris Antonetti",
    "COL": "Bill Schmidt",
    "DET": "Scott Harris",
    "HOU": "Dana Brown",
    "KCR": "J.J. Picollo",
    "LAA": "Perry Minasian",
    "LAD": "Andrew Friedman",
    "MIA": "Peter Bendix",
    "MIL": "Matt Arnold",
    "MIN": "Derek Falvey",
    "NYM": "David Stearns",
    "NYY": "Brian Cashman",
    "OAK": "David Forst",
    "PHI": "Dave Dombrowski",
    "PIT": "Ben Cherington",
    "SDP": "A.J. Preller",
    "SEA": "Jerry Dipoto",
    "SFG": "Buster Posey",
    "STL": "Chaim Bloom",
    "TBR": "Erik Neander",
    "TEX": "Chris Young",
    "TOR": "Ross Atkins",
    "WSN": "Mike DeBartolo",
}
