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
from quant_backtester.strategies import (
    GoldenCrossETF,
    MomentumSingleAsset,
    MovingAverageBandETF,
    MovingAverageCross,
    MovingAverageEntryExitETF,
    WorldMA20Benchmark,
)
from quant_backtester.strategies.base import Strategy

FUND = "ETF_EU"
UNIVERSE = (FUND, "ETF_OTHER")
MISSING = SignalStatus.INSUFFICIENT_HISTORY

WrittenDecision = Callable[..., StrategyContext]

GOLDEN = GoldenCrossETF(instrument_id=FUND, fast_sessions=2, slow_sessions=3)
CROSS = MovingAverageCross(instrument_id=FUND, first_sessions=2, second_sessions=3)
MOMENTUM = MomentumSingleAsset(instrument_id=FUND, lookback_sessions=3)
BAND = MovingAverageBandETF(instrument_id=FUND, window_sessions=3, sell_below=0.99, buy_above=1.01)
ENTRY_EXIT = MovingAverageEntryExitETF(instrument_id=FUND, entry_sessions=2, exit_sessions=3)
SA1 = WorldMA20Benchmark(instrument_id=FUND, window_sessions=3)

ONE_SIGNAL: dict[str, tuple[Strategy, str]] = {
    "golden_cross": (GOLDEN, GOLDEN.signal().signal_id),
    "moving_average_cross": (CROSS, CROSS.signal_id),
    "momentum_single_asset": (MOMENTUM, MOMENTUM.signal_id),
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


def test_a_band_that_waits_in_cash_on_a_valid_signal_considered_its_fund(
    written_decision: WrittenDecision,
) -> None:
    def decide(
        value: float | SignalStatus, held: dict[str, float] | None = None
    ) -> TargetAllocation:
        ctx = written_decision(BAND, written(BAND.signal_id, value), universe=UNIVERSE, held=held)
        return BAND.decide(ctx)

    waiting, sold, unreadable = decide(0.0), decide(-0.05, {FUND: 0.99}), decide(MISSING)

    # Between the two levels and not held: nothing to do, on a signal that was read.
    assert waiting.hold_positions and dict(waiting.weights) == {}
    assert (waiting.considered, dict(waiting.skipped)) == (1, {})
    assert (dict(sold.weights), sold.considered) == ({}, 1)
    assert unreadable.hold_positions
    assert (unreadable.considered, dict(unreadable.skipped)) == (0, {FUND: MISSING})


def test_a_fund_read_through_two_signals_is_unreadable_as_soon_as_one_is(
    written_decision: WrittenDecision,
) -> None:
    entry_id, exit_id = ENTRY_EXIT.entry_signal().signal_id, ENTRY_EXIT.exit_signal().signal_id

    def decide(entry: float | SignalStatus, leave: float | SignalStatus) -> TargetAllocation:
        values = written(entry_id, entry) | written(exit_id, leave)
        return ENTRY_EXIT.decide(written_decision(ENTRY_EXIT, values, universe=UNIVERSE))

    bought, below, half_read = decide(0.02, 0.01), decide(-0.02, -0.01), decide(0.02, MISSING)

    assert (dict(bought.weights), bought.considered) == ({FUND: 1.0}, 1)
    assert (dict(below.weights), below.considered, dict(below.skipped)) == ({}, 1, {})
    assert half_read.hold_positions
    assert (half_read.considered, dict(half_read.skipped)) == (0, {FUND: MISSING})
