"""S.T.I.C.K. — front-office and dugout analytics for all 30 MLB clubs.

Two composite metrics:
  * W.E.A.V.E.R.  (manager metric)  -> stick.weaver
  * S.T.I.C.K.    (GM metric)       -> stick.gm

Both standardize their raw inputs with league-relative z-scores so that
components measured in different units (runs, dollars, WAR, percentages)
can be combined on one scale.
"""

__version__ = "0.1.0"
