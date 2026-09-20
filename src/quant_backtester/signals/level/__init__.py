"""Signals over published series: rates, yields, index levels.

A published series is not a price. Nobody trades it, no venue holds sessions
for it, and it is released on a calendar of its own - so a window over it is
counted in **observations available**, never in sessions in a row, and the
window loader refuses the other contract for it outright.

Its arithmetic is different too. A ten-year yield of 4.20 that becomes 4.45 has
moved twenty-five basis points, not six percent, and a yield that crosses zero
makes a ratio meaningless rather than large. So nothing here takes a return:
the change is a difference in the series' own units, and the comparison across
instruments is done by standardising, not by dividing.
"""

from __future__ import annotations

from quant_backtester.signals.level.change import LevelChangeSignal
from quant_backtester.signals.level.zscore import LevelZScoreSignal

__all__ = ["LevelChangeSignal", "LevelZScoreSignal"]
