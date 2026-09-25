"""The vocabulary a strategy answers in, and what it refuses to say.

Two families of test here. The first is that the decision is one instant: the
signals, the market and the book all answer for it, and a context whose parts
disagree cannot be built. The second is that a helper refuses a book nobody
could hold - a short, a name outside the universe, an instrument the registry
says cannot be bought.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from quant_backtester.backtest.context import (
    Selection,
    StrategyContext,
    UnusableSignal,
)
from quant_backtester.backtest.market import StrategyMarketView
from quant_backtester.portfolio.state import PortfolioState
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import SignalStatus
from quant_backtester.signals.windows import LoadedWindow

DecisionBuilder = Callable[..., StrategyContext]
"""Builds the context a strategy is handed; the fixture lives in conftest."""


@dataclass(frozen=True, slots=True)
class Fixed(Signal):
    """A signal returning values the test decided, statuses included."""

    signal_id: str
    values: Mapping[str, float | SignalStatus]

    def definition(self) -> Mapping[str, object]:
        """Return a definition that tells two instances apart."""
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
    """Return a snapshot holding one signal over the decided values."""
    return SignalEngine().compute(context, [Fixed(signal_id="score", values=values)], list(values))


@pytest.fixture
def decision(context: SignalContext, make_decision: DecisionBuilder) -> StrategyContext:
    """Return a decision over three tradable funds, two of them rankable."""
    snapshot = snapshot_of(
        context,
        {"ETF_EU": 0.9, "ETF_OTHER": 0.4, "ETF_LATE": SignalStatus.INSUFFICIENT_HISTORY},
    )
    return make_decision(context, snapshot)


# -- one instant -------------------------------------------------------------


def test_every_part_of_a_context_answers_the_same_instant(
    decision: StrategyContext,
) -> None:
    """The property the object exists for, checked where it is built."""
    assert decision.signals.as_of == decision.as_of
    assert decision.market.as_of == decision.as_of
    assert decision.portfolio.as_of == decision.as_of


def test_a_context_whose_parts_disagree_cannot_be_built(
    context: SignalContext, decision: StrategyContext
) -> None:
    """A snapshot of yesterday beside a market of today is not a decision."""
    with pytest.raises(ValueError, match="answer for"):
        StrategyContext(
            as_of=decision.as_of + timedelta(days=1),
            signals=decision.signals,
            market=StrategyMarketView(context),
            portfolio=decision.portfolio,
            universe=decision.universe,
            instruments=context.instruments,
        )


def test_a_naive_instant_is_refused(context: SignalContext, decision: StrategyContext) -> None:
    """An instant with no zone belongs to no market's close."""
    with pytest.raises(ValueError, match="timezone-aware"):
        StrategyContext(
            as_of=datetime(2026, 9, 14, 21, 0),
            signals=decision.signals,
            market=decision.market,
            portfolio=decision.portfolio,
            universe=decision.universe,
            instruments=context.instruments,
        )


def test_a_universe_cannot_hold_a_name_twice(
    context: SignalContext, decision: StrategyContext
) -> None:
    """It would be weighted twice by anything that iterated over it."""
    with pytest.raises(ValueError, match="more than once"):
        StrategyContext(
            as_of=decision.as_of,
            signals=decision.signals,
            market=decision.market,
            portfolio=decision.portfolio,
            universe=("ETF_EU", "ETF_EU"),
            instruments=context.instruments,
        )


def test_a_context_hands_out_no_reader(decision: StrategyContext) -> None:
    """The one thing a strategy must not be able to reach."""
    assert not hasattr(decision, "reader")
    assert not hasattr(decision.market, "reader")
    assert not hasattr(decision, "repository")


# -- reading the signals -----------------------------------------------------


def test_a_value_that_is_not_usable_is_refused_rather_than_returned(
    decision: StrategyContext,
) -> None:
    """A NaN compares false against every threshold, silently."""
    with pytest.raises(UnusableSignal, match="INSUFFICIENT_HISTORY"):
        decision.signal_value("score", "ETF_LATE")


def test_the_tolerant_read_says_none_instead(decision: StrategyContext) -> None:
    """For a strategy that has a rule for the missing case and says so."""
    assert decision.signal_value_or_none("score", "ETF_LATE") is None
    assert decision.signal_value_or_none("score", "ETF_EU") == pytest.approx(0.9)


def test_a_status_can_always_be_read(decision: StrategyContext) -> None:
    """Reading why is never an error, whatever the answer is."""
    assert decision.signal_status("score", "ETF_LATE") is SignalStatus.INSUFFICIENT_HISTORY


def test_a_signal_frame_is_a_copy(decision: StrategyContext) -> None:
    """Two strategies reading the same signal cannot interfere."""
    frame = decision.signal("score")
    frame.loc["ETF_EU", "value"] = 99.0

    assert decision.signal_value("score", "ETF_EU") == pytest.approx(0.9)


def test_naming_a_signal_nobody_computed_is_loud(decision: StrategyContext) -> None:
    """A wiring mistake, not an empty day."""
    with pytest.raises(KeyError):
        decision.signal_value("momentum_60d", "ETF_EU")


# -- choosing ----------------------------------------------------------------


def test_the_top_of_a_ranking_keeps_only_what_is_usable(
    decision: StrategyContext,
) -> None:
    """An instrument with no number is never chosen, and never counted."""
    selected = decision.top("score", 2)

    assert tuple(selected) == ("ETF_EU", "ETF_OTHER")
    assert selected.considered == 2
    assert selected.skipped["ETF_LATE"] is SignalStatus.INSUFFICIENT_HISTORY


def test_the_bottom_is_the_other_end_of_the_same_ordering(
    decision: StrategyContext,
) -> None:
    """Symmetric, and it excludes the unusable names just the same."""
    assert tuple(decision.bottom("score", 1)) == ("ETF_OTHER",)


def test_a_filter_keeps_what_the_test_accepts(decision: StrategyContext) -> None:
    """Simple on purpose: Python is already the language of this project."""
    selected = decision.where("score", lambda value: value > 0.5)

    assert tuple(selected) == ("ETF_EU",)
    assert selected.considered == 2


def test_a_selection_reads_like_a_list(decision: StrategyContext) -> None:
    """It carries the count and the reasons, and still iterates."""
    selected = decision.top("score", 2)

    assert len(selected) == 2
    assert "ETF_EU" in selected
    assert selected[0] == "ETF_EU"
    assert list(selected) == ["ETF_EU", "ETF_OTHER"]


def test_asking_for_no_instrument_is_a_configuration_mistake(
    decision: StrategyContext,
) -> None:
    """Nobody means "the best zero of the ranking"."""
    with pytest.raises(ValueError, match="count"):
        decision.top("score", 0)


# -- expressing a decision ---------------------------------------------------


def test_equal_weight_splits_the_capital(decision: StrategyContext) -> None:
    """Two names, half each, and the selection's count carried through."""
    allocation = decision.equal_weight(decision.top("score", 2))

    assert dict(allocation.weights) == {"ETF_EU": 0.5, "ETF_OTHER": 0.5}
    assert allocation.considered == 2


def test_equal_weight_into_a_declared_number_of_parts(
    decision: StrategyContext,
) -> None:
    """One name out of two wanted is held at half, not at everything."""
    allocation = decision.equal_weight(decision.top("score", 1), count=2)

    assert dict(allocation.weights) == {"ETF_EU": 0.5}
    assert allocation.invested == pytest.approx(0.5)


def test_weights_are_taken_as_they_are_given(decision: StrategyContext) -> None:
    """A strategy with a view of its own is not forced through equal parts."""
    allocation = decision.weights({"ETF_EU": 0.6, "ETF_OTHER": 0.4})

    assert dict(allocation.weights) == {"ETF_EU": 0.6, "ETF_OTHER": 0.4}


def test_cash_holds_nothing_and_says_what_it_stood_aside_from(
    decision: StrategyContext,
) -> None:
    """A flat day with names considered is a decision; with none it is a hole."""
    allocation = decision.cash(among=decision.top("score", 2))

    assert dict(allocation.weights) == {}
    assert allocation.invested == 0.0
    assert allocation.considered == 2


def test_holding_the_current_book_is_not_the_same_as_going_to_cash(
    context: SignalContext,
    make_decision: DecisionBuilder,
    make_book: Callable[..., PortfolioState],
) -> None:
    """The two honest answers to a day whose data cannot be trusted."""
    snapshot = snapshot_of(context, {"ETF_EU": 0.9, "ETF_OTHER": 0.4})
    held = make_decision(
        context,
        snapshot,
        holdings=make_book(500.0, {"ETF_EU": 5.0}),
        prices={"ETF_EU": 100.0},
    )

    allocation = held.hold_current()

    assert dict(allocation.weights) == {"ETF_EU": pytest.approx(0.5)}
    assert allocation.invested == pytest.approx(0.5)


def test_a_negative_weight_is_refused(decision: StrategyContext) -> None:
    """Nothing in this project borrows a security."""
    with pytest.raises(ValueError, match="the weight of ETF_EU"):
        decision.weights({"ETF_EU": -0.2})


def test_weights_above_the_whole_book_are_refused(decision: StrategyContext) -> None:
    """A target of 60/60 is a loan the model never granted."""
    with pytest.raises(ValueError, match="add up to"):
        decision.weights({"ETF_EU": 0.6, "ETF_OTHER": 0.6})


def test_an_instrument_outside_the_session_universe_cannot_be_targeted(
    decision: StrategyContext,
) -> None:
    """Read anything the registry declares; hold only what the universe held."""
    with pytest.raises(ValueError, match="not in this session's universe"):
        decision.weights({"ETF_US": 1.0})


def test_an_instrument_the_registry_says_is_not_tradable_cannot_be_targeted(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """An index has a price and no way to buy it, and a strategy may read it."""
    snapshot = snapshot_of(context, {"ETF_EU": 0.9, "IDX_US": 1.0})
    decision = make_decision(context, snapshot, universe=("ETF_EU", "IDX_US"))

    assert decision.signal_value("score", "IDX_US") == pytest.approx(1.0)
    with pytest.raises(ValueError, match="tradable = false"):
        decision.weights({"IDX_US": 1.0})


def test_a_selection_of_nothing_becomes_a_flat_day(decision: StrategyContext) -> None:
    """Equal parts of no names is cash, and it keeps what it chose among."""
    empty = Selection(names=(), considered=3, skipped={})

    allocation = decision.equal_weight(empty)

    assert dict(allocation.weights) == {}
    assert allocation.considered == 3


def test_more_names_than_parts_is_a_configuration_mistake(
    decision: StrategyContext,
) -> None:
    """Two instruments cannot be held in one equal part."""
    with pytest.raises(ValueError, match="equal parts"):
        decision.equal_weight(["ETF_EU", "ETF_OTHER"], count=1)


def test_an_allocation_is_stamped_at_the_decision_instant(
    decision: StrategyContext,
) -> None:
    """So it cannot be mistaken for another day's."""
    assert decision.weights({"ETF_EU": 1.0}).as_of == decision.as_of
    assert decision.cash().as_of == decision.as_of


def test_a_plain_list_of_names_is_accepted_too(decision: StrategyContext) -> None:
    """A buy-and-hold does not go through a ranking to say what it holds."""
    allocation = decision.equal_weight(["ETF_EU"])

    assert dict(allocation.weights) == {"ETF_EU": 1.0}
    assert allocation.considered == 1


def test_a_universe_degraded_to_one_name_leaves_nothing_to_rank(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """Two deliberate things meet here, and the decision is the flat day.

    A ranking of one instrument is refused upstream - it would only say the one
    name is both the best and the worst of itself - so the top of it is empty.
    A strategy reading a raw momentum instead would have put everything into
    the single survivor.
    """
    from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank

    source = Fixed(
        signal_id="score", values={"ETF_EU": 0.9, "ETF_OTHER": SignalStatus.MISSING_INPUT}
    )
    snapshot = SignalEngine().compute(
        context,
        [CrossSectionalRank(signal_id="rank", source=source)],
        ["ETF_EU", "ETF_OTHER"],
    )
    decision = make_decision(context, snapshot)

    allocation = decision.equal_weight(decision.top("rank", 2), count=2)

    assert allocation.selected == ()
    assert allocation.invested == 0.0
    assert allocation.skipped["ETF_EU"] is SignalStatus.INSUFFICIENT_CROSS_SECTION


def test_asking_for_more_names_than_are_usable_leaves_the_rest_in_cash(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """Three wanted, two usable: two thirds invested rather than a doubled bet.

    Concentrating on the survivors is a decision, and a provider being late is
    not the thing that should take it.
    """
    snapshot = snapshot_of(
        context,
        {"ETF_EU": 0.9, "ETF_OTHER": 0.4, "ETF_LATE": SignalStatus.MISSING_INPUT},
    )
    decision = make_decision(context, snapshot)

    allocation = decision.equal_weight(decision.top("score", 3), count=3)

    assert allocation.selected == ("ETF_EU", "ETF_OTHER")
    assert allocation.invested == pytest.approx(2 / 3)


def test_a_decision_says_why_each_name_was_left_out(
    context: SignalContext, make_decision: DecisionBuilder
) -> None:
    """A day holding nothing must be explainable without opening the data."""
    snapshot = snapshot_of(
        context,
        {
            "ETF_EU": 0.9,
            "ETF_OTHER": 0.4,
            "ETF_LATE": SignalStatus.STALE_INPUT,
        },
    )
    decision = make_decision(context, snapshot)

    allocation = decision.equal_weight(decision.top("score", 1), count=1)

    assert allocation.selected == ("ETF_EU",)
    assert allocation.skipped == {
        "ETF_OTHER": SignalStatus.OK,
        "ETF_LATE": SignalStatus.STALE_INPUT,
    }


def test_the_same_name_cannot_be_held_twice(decision: StrategyContext) -> None:
    """One position, half a book, and nothing in the record saying why.

    The weights collapse into a single entry while the capital is split in two,
    so the strategy ends up half invested without having asked to be.
    """
    with pytest.raises(ValueError, match="selected more than once"):
        decision.equal_weight(["ETF_EU", "ETF_EU"])


def test_a_selection_cannot_be_edited_before_it_is_used(
    decision: StrategyContext,
) -> None:
    """It carries the diagnostics of a decision, not a working buffer."""
    selected = decision.top("score", 1)

    with pytest.raises(TypeError):
        selected.skipped["ETF_LATE"] = SignalStatus.OK  # type: ignore[index]


def test_a_selection_that_claims_more_than_it_chose_is_refused() -> None:
    """``considered`` is what tells two of nine from two of two."""
    with pytest.raises(ValueError, match="considered"):
        Selection(names=("A", "B"), considered=1, skipped={})


def test_a_selection_cannot_name_one_instrument_twice() -> None:
    """It would be weighted twice by anything that iterated over it."""
    with pytest.raises(ValueError, match="more than once"):
        Selection(names=("A", "A"), considered=2, skipped={})


def test_a_context_answers_in_utc_like_everything_else(
    decision: StrategyContext,
) -> None:
    """Timezone-aware, and comparable with the instants the engine records."""
    assert decision.as_of.tzinfo is not None
    assert decision.as_of.astimezone(UTC) == decision.as_of
