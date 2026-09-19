"""Concrete strategies composed from the building blocks above.

Each strategy is a declarative configuration (universe, signals, portfolio
rules, execution assumptions) plus any strategy-specific glue code.

A strategy receives a ``SignalSnapshot`` and nothing else. Not a reader, not a
repository, not a calendar: holding one of those, it could write its own
``tail(20)`` and get twenty observations spanning twenty-six sessions, or read a
price it had no business seeing at the instant it was deciding. Everything it
needs to know about the market has already been turned into numbers, and every
number comes with a status saying whether it can be used.
"""

from __future__ import annotations

from quant_backtester.strategies.rotation import TopRankRotation

__all__ = ["TopRankRotation"]
