"""Rules that turn signal values into weights, shared by the strategies beside this package.

``rules`` holds each rule as a pure function of numbers: no context, no book,
no market. ``SA1`` to ``SA9`` read their signals and hand the values to one
rule each; ``SA10_etf_ensemble`` hands them to all of them
and applies one risk control to the sum. ``inputs`` builds the signals every
rule reads, in one place, so that two strategies asking for a sixty-return
volatility ask for the same one.

Nothing is imported here on purpose: the ensemble imports the other
strategies, which import the rules of this package.
"""

from __future__ import annotations
