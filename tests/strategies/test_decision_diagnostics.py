"""A decision records what it was taken among: saying no is not having nothing to read.

Audit 13, C04. A rule on one fund used to answer ``ctx.cash()`` bare, whether
its signal said no or could not be computed, and a report counted both as a
session with nothing to choose from. The targets below are what they always
were; what changes is the record beside them.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies import WorldMA20Benchmark
from quant_backtester.strategies.base import Strategy

FUND = "ETF_EU"
UNIVERSE = (FUND, "ETF_OTHER")
MISSING = SignalStatus.INSUFFICIENT_HISTORY

WrittenDecision = Callable[..., StrategyContext]

SA1 = WorldMA20Benchmark(instrument_id=FUND, window_sessions=3)

ONE_SIGNAL: dict[str, tuple[Strategy, str]] = {
    "sa1_rule_strategy": (SA1, SA1.signal().signal_id),
}


def written(signal_id: str, value: float | SignalStatus) -> dict:
    """Return one signal's written value for both funds of the universe."""
    return {(signal_id, name): value for name in UNIVERSE}


@pytest.mark.parametrize("name", ONE_SIGNAL)
def test_a_signal_that_says_yes_no_or_nothing_gives_three_different_records(
    name: str, written_decision: WrittenDecision
) -> None:
    strategy, signal_id = ONE_SIGNAL[name]

    def decide(value: float | SignalStatus) -> TargetAllocation:
        ctx = written_decision(strategy, written(signal_id, value), universe=UNIVERSE)
        return strategy.decide(ctx)

    invested, refused, level, unreadable = decide(0.02), decide(-0.02), decide(0.0), decide(MISSING)

    # The targets are the ones the rule always gave.
    assert dict(invested.weights) == {FUND: 1.0}
    assert dict(refused.weights) == dict(level.weights) == dict(unreadable.weights) == {}
    # A valid signal was considered, whatever it said; a missing one was not.
    assert (invested.considered, refused.considered, level.considered) == (1, 1, 1)
    assert dict(refused.skipped) == dict(level.skipped) == {}
    assert unreadable.considered == 0
    assert dict(unreadable.skipped) == {FUND: MISSING}
