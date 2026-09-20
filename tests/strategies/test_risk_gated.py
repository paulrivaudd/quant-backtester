"""A rotation gated by something it does not trade.

The gate is a number and a threshold, so the arithmetic is nothing. What the
tests are about is the three cases a risk filter is judged on: it lets the
strategy run, it stands it down, and - the one that is usually found out too
late - it says what it does when its own input is missing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import SignalStatus
from quant_backtester.signals.windows import LoadedWindow
from quant_backtester.strategies.risk_gated import RiskGatedRotation
from quant_backtester.strategies.rotation import TopRankRotation

DecisionBuilder = Callable[..., StrategyContext]
"""Builds the context a strategy is handed; the fixture lives in conftest."""


@dataclass(frozen=True, slots=True)
class Fixed(Signal):
    """A signal returning values the test decided, statuses included."""

    signal_id: str
    values: Mapping[str, float | SignalStatus]

    def definition(self) -> Mapping[str, object]:
        """Return a definition that tells two instances apart."""
        return {"type": "Fixed", "values": {key: str(value) for key, value in self.values.items()}}

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return the decided values, in the order asked for."""
        rows = {}
        for instrument_id in instrument_ids:
            given = self.values[instrument_id]
            if isinstance(given, SignalStatus):
                rows[instrument_id] = result_row(None, LoadedWindow(status=given))
                continue
            rows[instrument_id] = result_row(
                given, LoadedWindow(status=SignalStatus.OK, points=(1.0, 2.0), age_sessions=0)
            )
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=build_result_frame(rows),
            definition=self.definition(),
        )


def snapshot_of(
    context: SignalContext,
    ranks: Mapping[str, float | SignalStatus],
    gate: float | SignalStatus,
) -> SignalSnapshot:
    """Return a snapshot holding a ranking over funds and a gauge over a rate."""
    return SignalEngine().compute(
        context,
        [
            Fixed(signal_id="momentum_rank", values=ranks),
            SignalRequest(Fixed(signal_id="risk_gauge", values={"RATE_US": gate}), ["RATE_US"]),
        ],
        list(ranks),
    )


def gated(flat_when_unknown: bool = True, maximum: float = 1.0) -> RiskGatedRotation:
    """Return the strategy under test, holding one name when the gate is open."""
    return RiskGatedRotation(
        rotation=TopRankRotation(signal_id="momentum_rank", top_n=1),
        gate_signal_id="risk_gauge",
        gate_instrument_id="RATE_US",
        maximum=maximum,
        flat_when_unknown=flat_when_unknown,
    )


def test_a_quiet_gauge_lets_the_rotation_run(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """Below the threshold, the strategy is exactly the rotation it wraps."""
    snapshot = snapshot_of(context, {"ETF_EU": 1.0, "ETF_OTHER": 0.5}, gate=0.2)

    allocation = gated().decide(make_decision(context, snapshot))

    assert allocation.selected == ("ETF_EU",)
    assert allocation.invested == pytest.approx(1.0)


def test_a_gauge_above_the_threshold_stands_the_book_down(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """The names were rankable and the strategy chose not to hold them."""
    snapshot = snapshot_of(context, {"ETF_EU": 1.0, "ETF_OTHER": 0.5}, gate=2.5)

    allocation = gated().decide(make_decision(context, snapshot))

    assert allocation.selected == ()
    assert allocation.invested == 0.0
    # The distinction a record needs: a gated day had something to choose from.
    assert allocation.considered == 2


def test_the_threshold_is_inclusive(context: SignalContext, make_decision: DecisionBuilder) -> None:
    """At the threshold the gate is open, and the docstring says so."""
    snapshot = snapshot_of(context, {"ETF_EU": 1.0, "ETF_OTHER": 0.5}, gate=1.0)

    assert gated(maximum=1.0).decide(make_decision(context, snapshot)).selected == ("ETF_EU",)


def test_a_gauge_nobody_could_read_stands_the_book_down(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """The case a risk filter is really judged on.

    A filter that silently becomes no filter the day its input is late is only
    noticed afterwards, so what happens is declared in the configuration.
    """
    snapshot = snapshot_of(
        context, {"ETF_EU": 1.0, "ETF_OTHER": 0.5}, gate=SignalStatus.STALE_INPUT
    )

    assert gated(flat_when_unknown=True).decide(make_decision(context, snapshot)).selected == ()


def test_a_gauge_nobody_could_read_can_also_be_ignored(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """The other choice, taken deliberately rather than by omission."""
    snapshot = snapshot_of(
        context, {"ETF_EU": 1.0, "ETF_OTHER": 0.5}, gate=SignalStatus.STALE_INPUT
    )

    assert gated(flat_when_unknown=False).decide(make_decision(context, snapshot)).selected == (
        "ETF_EU",
    )


def test_a_flat_day_with_nothing_to_choose_from_is_not_a_gated_day(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """Both are flat, and they mean opposite things about the strategy."""
    nothing_usable = snapshot_of(
        context,
        {"ETF_EU": SignalStatus.MISSING_INPUT, "ETF_OTHER": SignalStatus.MISSING_INPUT},
        gate=0.1,
    )

    allocation = gated().decide(make_decision(context, nothing_usable))

    assert allocation.selected == ()
    assert allocation.considered == 0


def test_the_gauge_must_have_been_computed(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """A strategy naming a signal the engine was not given is a wiring mistake."""
    snapshot = SignalEngine().compute(
        context,
        [Fixed(signal_id="momentum_rank", values={"ETF_EU": 1.0, "ETF_OTHER": 0.5})],
        ["ETF_EU", "ETF_OTHER"],
    )

    with pytest.raises(KeyError, match="risk_gauge"):
        gated().decide(make_decision(context, snapshot))


def test_the_gauge_must_have_been_computed_for_its_instrument(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """The gauge exists, and it was not asked about the name the gate reads."""
    snapshot = snapshot_of(context, {"ETF_EU": 1.0, "ETF_OTHER": 0.5}, gate=0.2)
    wrong = RiskGatedRotation(
        rotation=TopRankRotation(signal_id="momentum_rank", top_n=1),
        gate_signal_id="risk_gauge",
        gate_instrument_id="ETF_EU",
        maximum=1.0,
        flat_when_unknown=True,
    )

    with pytest.raises(KeyError):
        wrong.decide(make_decision(context, snapshot))


@pytest.mark.parametrize("flat", [None, "yes", 1])
def test_what_to_do_with_an_unreadable_gauge_has_to_be_said(flat: object) -> None:
    """No default: the day it matters is the day nobody remembers choosing."""
    with pytest.raises(ValueError, match="flat_when_unknown"):
        RiskGatedRotation(
            rotation=TopRankRotation(signal_id="rank", top_n=1),
            gate_signal_id="gauge",
            gate_instrument_id="RATE_US",
            maximum=1.0,
            flat_when_unknown=flat,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("maximum", [float("nan"), float("inf"), float("-inf"), "1.0", None, True])
def test_a_threshold_that_is_not_a_number_is_refused(maximum: object) -> None:
    """A comparison against a string or a NaN is never true, silently.

    An infinity is the same mistake with a straight face: a gate at ``+inf``
    never closes and one at ``-inf`` never opens, and both would be read as a
    risk filter that was simply never triggered.
    """
    with pytest.raises(ValueError, match="maximum"):
        RiskGatedRotation(
            rotation=TopRankRotation(signal_id="rank", top_n=1),
            gate_signal_id="gauge",
            gate_instrument_id="RATE_US",
            maximum=maximum,  # type: ignore[arg-type]
            flat_when_unknown=True,
        )


def test_the_snapshot_is_the_only_argument(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """A strategy sees numbers and statuses, and nothing that produced them."""
    snapshot = snapshot_of(context, {"ETF_EU": 1.0, "ETF_OTHER": 0.5}, gate=0.2)

    allocation = gated().decide(make_decision(context, snapshot))

    assert isinstance(allocation.as_of, datetime)
    assert allocation.as_of == snapshot.as_of
