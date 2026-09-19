"""The first strategy, and the boundary it exists to prove.

The rule it applies is three lines long. What the tests are about is everything
it is *not* given: no reader, no repository, no calendar, no provider. The
market reached it as numbers with statuses attached, and the decision is taken
on those alone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import pytest

from quant_backtester.data.reader import MarketDataReader
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.signals.windows import LoadedWindow
from quant_backtester.strategies.rotation import TopRankRotation


@dataclass(frozen=True, slots=True)
class Fixed(Signal):
    """A signal returning values decided by the test, statuses included."""

    signal_id: str
    values: Mapping[str, float | SignalStatus]

    def definition(self) -> Mapping[str, object]:
        """Return a definition that distinguishes two instances."""
        return {"type": "Fixed", "values": {k: str(v) for k, v in self.values.items()}}

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
    context: SignalContext, values: Mapping[str, float | SignalStatus]
) -> SignalSnapshot:
    """Return a snapshot holding one ranking over the decided values."""
    source = Fixed(signal_id="momentum", values=values)
    return SignalEngine().compute(
        context,
        [CrossSectionalRank(signal_id="momentum_rank", source=source)],
        list(values),
    )


def decide(
    context: SignalContext,
    values: Mapping[str, float | SignalStatus],
    top_n: int = 2,
) -> TargetAllocation:
    """Run the rotation over the decided values."""
    return TopRankRotation(signal_id="momentum_rank", top_n=top_n).decide(
        snapshot_of(context, values)
    )


def test_it_holds_the_best_ranked_instruments(context: SignalContext) -> None:
    """Four names, the top two held, equally weighted."""
    allocation = decide(context, {"A": 0.15, "ETF_EU": 0.09, "IDX_US": 0.05, "D": -0.02}, top_n=2)

    assert allocation.selected == ("A", "ETF_EU")
    assert allocation.weights == {"A": 0.5, "ETF_EU": 0.5}
    assert allocation.invested == pytest.approx(1.0)
    assert allocation.considered == 4


def test_it_answers_the_instant_it_was_given(context: SignalContext) -> None:
    """An allocation cannot be mistaken for another day's."""
    allocation = decide(context, {"A": 0.15, "ETF_EU": 0.09, "IDX_US": 0.05})

    assert allocation.as_of == context.as_of


def test_an_instrument_without_a_usable_signal_is_never_held(
    context: SignalContext,
) -> None:
    """The reason the ranking excludes them rather than putting them last.

    ETF_EU has the second-best momentum of the three that have one, but IDX_US
    has no number at all - and a strategy must not end up holding it because a
    rank of 0.0 looked like a number.
    """
    allocation = decide(
        context,
        {
            "A": 0.15,
            "ETF_EU": 0.09,
            "IDX_US": SignalStatus.MISSING_INPUT,
            "D": SignalStatus.NOT_LISTED,
        },
        top_n=3,
    )

    assert allocation.selected == ("A", "ETF_EU")
    assert "IDX_US" not in allocation.weights
    assert allocation.considered == 2


def test_it_says_why_each_instrument_was_left_out(context: SignalContext) -> None:
    """A day holding nothing must be explainable without opening the data."""
    allocation = decide(
        context,
        {
            "A": 0.15,
            "ETF_EU": 0.09,
            "IDX_US": SignalStatus.STALE_INPUT,
            "D": SignalStatus.INSUFFICIENT_HISTORY,
        },
        top_n=1,
    )

    assert allocation.selected == ("A",)
    assert allocation.skipped == {
        "ETF_EU": SignalStatus.OK,
        "IDX_US": SignalStatus.STALE_INPUT,
        "D": SignalStatus.INSUFFICIENT_HISTORY,
    }


def test_a_missing_name_leaves_cash_rather_than_doubling_a_bet(
    context: SignalContext,
) -> None:
    """The decision this strategy makes explicitly.

    A rotation meant to hold two that can only find one holds it at half the
    capital. Concentrating on the survivor is a choice, and a provider being
    late is not the thing that should take it.
    """
    allocation = decide(
        context,
        {"A": 0.15, "ETF_EU": 0.09, "IDX_US": SignalStatus.MISSING_INPUT},
        top_n=3,
    )

    assert allocation.selected == ("A", "ETF_EU")
    assert allocation.weights == {"A": 1 / 3, "ETF_EU": 1 / 3}
    assert allocation.invested == pytest.approx(2 / 3)


def test_a_universe_degraded_to_one_name_is_a_flat_day(context: SignalContext) -> None:
    """Two things meet here, and both of them are deliberate.

    A ranking of one instrument is refused upstream - it would only say that
    the one name is both the best and the worst of itself - so the rotation
    finds nothing usable and holds nothing. A strategy reading a raw momentum
    instead would have put everything into the single survivor.
    """
    allocation = decide(context, {"A": 0.15, "ETF_EU": SignalStatus.MISSING_INPUT}, top_n=2)

    assert allocation.selected == ()
    assert allocation.invested == 0.0
    assert allocation.skipped["A"] is SignalStatus.INVALID_INPUT


def test_a_universe_with_nothing_usable_is_a_flat_day(context: SignalContext) -> None:
    """No number, no position, and a record of why."""
    allocation = decide(
        context,
        {"A": SignalStatus.MISSING_INPUT, "ETF_EU": SignalStatus.NOT_LISTED},
        top_n=2,
    )

    assert allocation.selected == ()
    assert allocation.weights == {}
    assert allocation.invested == 0.0
    assert allocation.considered == 0


def test_more_names_wanted_than_the_universe_holds(context: SignalContext) -> None:
    """Asking for five out of three holds three, at a fifth of the capital each."""
    allocation = decide(context, {"A": 0.15, "ETF_EU": 0.09, "IDX_US": 0.05}, top_n=5)

    assert len(allocation.selected) == 3
    assert allocation.invested == pytest.approx(0.6)


def test_an_allocation_cannot_be_edited_afterwards(context: SignalContext) -> None:
    """A decision is a record of what was decided, not a working buffer."""
    allocation = decide(context, {"A": 0.15, "ETF_EU": 0.09, "IDX_US": 0.05})

    with pytest.raises(TypeError):
        allocation.weights["A"] = 1.0  # type: ignore[index]
    with pytest.raises((AttributeError, TypeError)):
        allocation.selected = ()  # type: ignore[misc]


def test_naming_a_signal_the_engine_never_computed_is_loud(
    context: SignalContext,
) -> None:
    """A wiring mistake, not an empty day."""
    snapshot = snapshot_of(context, {"A": 0.15, "ETF_EU": 0.09})

    with pytest.raises(KeyError, match="momentum_120d_rank"):
        TopRankRotation(signal_id="momentum_120d_rank", top_n=2).decide(snapshot)


@pytest.mark.parametrize("top_n", [0, -1])
def test_a_rotation_holding_nothing_is_refused(top_n: int) -> None:
    """Not a status: a rotation of zero names is a configuration mistake."""
    with pytest.raises(ValueError, match="top_n"):
        TopRankRotation(signal_id="momentum_rank", top_n=top_n)


def test_the_whole_chain_on_real_windows(
    market: MarketDataReader,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """Market data, signals, snapshot, decision - with nothing skipped.

    The point of this one is the argument list of ``decide``: a snapshot, and
    nothing else. No reader reaches it, so no window it did not ask for can.
    """
    context = make_context(market, evening(sessions[-1]))
    momentum = MomentumSignal(
        signal_id="momentum_5d",
        lookback_sessions=5,
        skip_recent_sessions=0,
        price_basis=PriceBasis.RAW,
    )
    snapshot = SignalEngine().compute(
        context,
        [momentum, CrossSectionalRank(signal_id="momentum_5d_rank", source=momentum)],
        ["ETF_EU", "IDX_US", "ETF_LATE"],
    )

    allocation = TopRankRotation(signal_id="momentum_5d_rank", top_n=1).decide(snapshot)

    # ETF_LATE has four sessions of history, one short of the window.
    assert allocation.skipped["ETF_LATE"] is SignalStatus.INSUFFICIENT_HISTORY
    assert allocation.considered == 2
    assert len(allocation.selected) == 1
    assert allocation.invested == pytest.approx(1.0)
