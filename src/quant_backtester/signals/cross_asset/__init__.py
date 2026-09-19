"""Signals that read one instrument to say something about another.

A VIX level, a ten-year yield move, a currency: inputs from a different market,
and therefore a different calendar, which is why staleness is counted on the
engine's reference calendar rather than on each venue's own.

Empty until the cross-asset phase.
"""
