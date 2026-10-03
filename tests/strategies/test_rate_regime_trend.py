"""RateRegimeTrend: a trend rule, and the one fall it does not sell.

The decision is tested on signals of known value, one case per line of its
truth table, then once through the engine to prove that the three signals it
declares are the three it reads.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.portfolio.state import PortfolioState
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.types import SignalStatus
from quant_backtester.signals.windows import LoadedWindow
from quant_backtester.strategies.examples.rate_regime_trend import RateRegimeTrend

BarsBuilder = Callable[..., pd.DataFrame]
LevelsBuilder = Callable[..., pd.DataFrame]
MarketBuilder = Callable[..., MarketDataReader]
ContextBuilder = Callable[[MarketDataReader, datetime], SignalContext]
DecisionBuilder = Callable[..., StrategyContext]
BookBuilder = Callable[..., PortfolioState]
Decide = Callable[..., TargetAllocation]

TREND, REGIME, STRESS = "price_over_ma5", "idx_us_rate_us_corr_3p", "rate_us_z_5o"
"""The ids of the three signals the rule below reads."""

UNREADABLE = SignalStatus.STALE_INPUT
"""Any status but ``OK``: the rule does not tell them apart."""


def rule(**changes: object) -> RateRegimeTrend:
    """Return the rule on the synthetic market: the Paris ETF, the US index and the US rate."""
    fields: dict[str, object] = {
        "instrument_id": "ETF_EU",
        "equity_id": "IDX_US",
        "rate_id": "RATE_US",
        "stress_id": "RATE_US",
        "trend_sessions": 5,
        "correlation_pairs": 3,
        "stress_observations": 5,
        "stress_minimum": 1.5,
        "regime_max_age_sessions": 1,
        "stress_max_age_sessions": 1,
    }
    return RateRegimeTrend(**(fields | changes))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class Fixed(Signal):
    """A signal whose value is written by the test, or whose status is not ``OK``."""

    signal_id: str
    value: float | SignalStatus

    def definition(self) -> Mapping[str, object]:
        """Return what identifies this stand-in."""
        return {"type": "Fixed", "signal_id": self.signal_id}

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return the written value for every instrument asked about."""
        if isinstance(self.value, SignalStatus):
            row = result_row(None, LoadedWindow(status=self.value))
        else:
            row = result_row(
                self.value, LoadedWindow(status=SignalStatus.OK, points=(1.0,), age_sessions=0)
            )
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=build_result_frame(dict.fromkeys(instrument_ids, row)),
            definition=self.definition(),
        )


@pytest.fixture
def decide(
    context: SignalContext, make_decision: DecisionBuilder, make_book: BookBuilder
) -> Decide:
    """Return what the rule decides on three written signals, from cash or holding the fund."""

    def run(
        trend: float | SignalStatus,
        regime: float | SignalStatus,
        stress: float | SignalStatus,
        *,
        held: bool,
    ) -> TargetAllocation:
        requests = [
            SignalRequest(Fixed(TREND, trend), ("ETF_EU",)),
            SignalRequest(Fixed(REGIME, regime), ("IDX_US",)),
            SignalRequest(Fixed(STRESS, stress), ("RATE_US",)),
        ]
        snapshot = SignalEngine().compute(context, requests, ["ETF_EU"])
        book = make_book(0.0, {"ETF_EU": 10.0}) if held else make_book(10_000.0)
        prices = {"ETF_EU": 109.0} if held else {}
        return rule().decide(
            make_decision(context, snapshot, universe=("ETF_EU",), holdings=book, prices=prices)
        )

    return run


def is_cash(allocation: TargetAllocation) -> bool:
    """Return whether a target sells everything."""
    return not allocation.hold_positions and not dict(allocation.weights)


def is_purchase(allocation: TargetAllocation) -> bool:
    """Return whether a target puts the whole book in the fund."""
    return not allocation.hold_positions and dict(allocation.weights) == {"ETF_EU": 1.0}


def test_the_rule_reads_three_signals_each_on_its_own_instrument() -> None:
    requests = rule().required_signals()
    assert [(request.signal.signal_id, request.instruments) for request in requests] == [  # type: ignore[union-attr]
        (TREND, ("ETF_EU",)),
        (REGIME, ("IDX_US",)),
        (STRESS, ("RATE_US",)),
    ]


def test_above_its_average_the_fund_is_bought_whatever_the_regime(decide: Decide) -> None:
    assert is_purchase(decide(0.02, -0.5, 0.0, held=False))
    assert is_purchase(decide(0.02, UNREADABLE, UNREADABLE, held=False))


def test_above_its_average_a_fund_already_held_is_left_alone(decide: Decide) -> None:
    assert decide(0.02, -0.5, 0.0, held=True).hold_positions


def test_below_its_average_without_a_panic_the_book_is_cash(decide: Decide) -> None:
    assert is_cash(decide(-0.02, 0.4, 1.0, held=True))
    assert is_cash(decide(-0.02, 0.4, 1.0, held=False))


def test_a_panic_while_shares_and_yields_fall_apart_is_sold(decide: Decide) -> None:
    assert is_cash(decide(-0.02, -0.4, 3.0, held=True))


def test_a_panic_in_a_hedged_regime_is_held_through(decide: Decide) -> None:
    assert decide(-0.02, 0.4, 3.0, held=True).hold_positions


def test_a_panic_in_a_hedged_regime_is_bought_from_cash(decide: Decide) -> None:
    assert is_purchase(decide(-0.02, 0.4, 3.0, held=False))


def test_the_levels_themselves_are_not_a_panic_nor_a_hedged_regime(decide: Decide) -> None:
    assert is_cash(decide(-0.02, 0.4, 1.5, held=True))
    assert is_cash(decide(-0.02, 0.0, 3.0, held=True))
    assert is_cash(decide(0.0, 0.0, 0.0, held=True))


def test_below_its_average_an_unreadable_regime_or_panic_is_cash(decide: Decide) -> None:
    assert is_cash(decide(-0.02, UNREADABLE, 3.0, held=True))
    assert is_cash(decide(-0.02, 0.4, UNREADABLE, held=True))


def test_an_unreadable_trend_keeps_the_book_as_it_is(decide: Decide) -> None:
    assert decide(UNREADABLE, 0.4, 3.0, held=True).hold_positions
    assert decide(UNREADABLE, -0.4, 0.0, held=False).hold_positions


@pytest.mark.parametrize(
    "changes",
    [
        {"instrument_id": ""},
        {"trend_sessions": 1},
        {"correlation_pairs": 2},
        {"stress_observations": 1},
        {"stress_minimum": float("nan")},
        {"regime_max_age_sessions": -1},
    ],
)
def test_a_configuration_that_cannot_be_computed_is_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r"must|at least|finite|empty|identifier"):
        rule(**changes)


def test_through_the_engine_the_rule_reads_exactly_what_it_declares(
    make_market: MarketBuilder,
    make_bars: BarsBuilder,
    make_levels: LevelsBuilder,
    make_context: ContextBuilder,
    make_decision: DecisionBuilder,
    xpar: TradingCalendar,
    xnys: TradingCalendar,
    sessions: tuple[date, ...],
    us_sessions: tuple[date, ...],
    evening: Callable[[date], datetime],
) -> None:
    # The fund ends under its average; the index fell as the rate fell, and the
    # rate ends far from its own mean: a panic the bond market hedged.
    fund = dict(zip(sessions, [100.0] * 9 + [90.0], strict=True))
    index = dict(
        zip(
            us_sessions,
            [5000.0, 5010.0, 5020.0, 5030.0, 5040.0, 5050.0, 5060.0, 5000.0, 4900.0],
            strict=True,
        )
    )
    rates = dict(zip(us_sessions, [4.0, 4.0, 4.0, 4.0, 4.0, 4.01, 4.02, 3.9, 5.0], strict=True))
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, fund), "IDX_US": make_bars("IDX_US", xnys, index)},
        None,
        {"RATE_US": make_levels("RATE_US", rates)},
    )
    context = make_context(market, evening(sessions[-1]))
    strategy = rule()
    requests = [
        item.resolved(sessions[-1]) if isinstance(item, SignalRequest) else item
        for item in strategy.required_signals()
    ]
    snapshot = SignalEngine().compute(context, requests, ["ETF_EU"])
    assert snapshot.value(TREND, "ETF_EU") < 0.0
    assert snapshot.status(REGIME, "IDX_US") is SignalStatus.OK
    assert snapshot.status(STRESS, "RATE_US") is SignalStatus.OK
    allocation = strategy.decide(make_decision(context, snapshot, universe=("ETF_EU",)))
    assert snapshot.value(STRESS, "RATE_US") > 1.5
    assert is_purchase(allocation) == (snapshot.value(REGIME, "IDX_US") > 0.0)
