"""ML1: from the network's proposal to one of the three answers of a decision."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("torch")

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.artifacts import NeuralArtifact
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.ml.neural_allocation import (
    Action,
    InformationCutoffError,
    NeuralAllocationStrategy,
    capped_targets,
    neural_decision,
    require_after_cutoff,
)

A, B = "ETF_EU", "ETF_OTHER"
DECISION = date(2026, 9, 14)
RULE = {"max_asset_weight": 0.60, "min_asset_weight": 0.01, "rebalance_band": 0.03}

Decide = Callable[..., TargetAllocation]


def evening(day: date) -> datetime:
    """Return the decision instant of a session: 23:00 in Paris."""
    return datetime(day.year, day.month, day.day, 23, 0, tzinfo=ZoneInfo("Europe/Paris"))


def test_the_cap_and_the_minimum_send_what_they_remove_to_cash() -> None:
    target = capped_targets({A: 0.985, B: 0.005}, max_asset_weight=0.60, min_asset_weight=0.01)

    # 0.385 capped away and 0.005 too small: 40% of the book ends in cash.
    assert target == {A: 0.60}
    assert capped_targets({A: 0.01, B: 0.0099}, max_asset_weight=1.0, min_asset_weight=0.01) == {
        A: 0.01
    }
    assert capped_targets({A: 0.55, B: 0.25}, max_asset_weight=1.0, min_asset_weight=0.01) == {
        A: 0.55,
        B: 0.25,
    }


@pytest.mark.parametrize(
    "proposed",
    [{A: 0.7, B: 0.4}, {A: -0.1, B: 0.2}, {A: 1.2}, {A: float("nan"), B: 0.1}],
)
def test_a_proposal_that_is_not_an_allocation_is_an_error_and_is_not_rescaled(proposed) -> None:
    with pytest.raises(ValueError, match="proposed weight"):
        capped_targets(proposed, max_asset_weight=1.0, min_asset_weight=0.01)


def test_missing_data_and_a_choice_of_cash_are_two_different_days_in_cash() -> None:
    missing = neural_decision(None, {A: 0.5}, **RULE)
    chosen = neural_decision({A: 0.004, B: 0.003}, {A: 0.5}, **RULE)

    assert (missing.action, missing.reason) == (Action.CASH, "MISSING_DATA")
    assert (chosen.action, chosen.reason) == (Action.CASH, "NO_FUND_ABOVE_MINIMUM")
    assert missing.target == chosen.target == {}


def test_a_small_drift_keeps_the_book_and_a_large_one_rebalances_it() -> None:
    proposed = {A: 0.55, B: 0.25}

    kept = neural_decision(proposed, {A: 0.57, B: 0.24}, **RULE)
    moved = neural_decision(proposed, {A: 0.59, B: 0.25}, **RULE)
    entered = neural_decision(proposed, {}, **RULE)

    assert (kept.action, kept.reason) == (Action.HOLD, "INSIDE_BAND")
    assert kept.gap == pytest.approx(0.02)
    assert (moved.action, moved.reason) == (Action.WEIGHTS, "OUTSIDE_BAND")
    assert moved.target == proposed
    assert (entered.action, entered.gap) == (Action.WEIGHTS, pytest.approx(0.80))


def test_the_band_counts_cash_like_any_other_weight() -> None:
    # Each fund is two points from its target and cash is four: outside the band.
    decision = neural_decision({A: 0.48, B: 0.48}, {A: 0.50, B: 0.50}, **RULE)

    assert decision.action is Action.WEIGHTS
    assert decision.gap == pytest.approx(0.04)


def test_the_band_never_holds_back_a_full_exit_or_a_breached_cap() -> None:
    leaving = neural_decision({A: 0.50, B: 0.005}, {A: 0.50, B: 0.02}, **RULE)
    breached = neural_decision({A: 0.70}, {A: 0.61}, **RULE)

    assert (leaving.action, leaving.reason) == (Action.WEIGHTS, "FULL_EXIT")
    assert leaving.target == {A: 0.50}
    assert (breached.action, breached.reason) == (Action.WEIGHTS, "CAP_BREACHED")
    assert breached.target == {A: 0.60}


@pytest.fixture
def strategy(neural_artifact: NeuralArtifact) -> NeuralAllocationStrategy:
    """Return ML1 on the untrained model of the fixtures."""
    return NeuralAllocationStrategy.from_artifact(neural_artifact)


@pytest.fixture
def contexts(
    strategy: NeuralAllocationStrategy, calendars, make_decision, make_book
) -> Callable[..., StrategyContext]:
    """Return the context ML1 is handed for one decision on a given store and book."""

    def at(
        reader: MarketDataReader,
        day: date = DECISION,
        held: dict[str, float] | None = None,
    ) -> StrategyContext:
        context = SignalContext(
            market=reader.at(evening(day)), instruments=reader.instruments, calendars=calendars
        )
        snapshot = SignalEngine().compute(context, list(strategy.required_signals()), [A, B])
        # Every fund valued at 100 in a book worth 10 000: a weight is a quantity over 100.
        quantities = {name: weight * 100.0 for name, weight in (held or {}).items()}
        book = make_book(10_000.0 * (1.0 - sum((held or {}).values())), quantities)
        return make_decision(
            context,
            snapshot,
            universe=(A, B),
            holdings=book,
            prices=dict.fromkeys(quantities, 100.0),
        )

    return at


def test_from_cash_the_strategy_buys_what_the_network_proposes(
    strategy: NeuralAllocationStrategy, contexts, neural_market: MarketDataReader
) -> None:
    ctx = contexts(neural_market)

    allocation = strategy.decide(ctx)

    proposed = strategy.proposal(ctx)
    assert proposed is not None
    assert dict(allocation.weights) == pytest.approx(proposed)
    assert not allocation.hold_positions
    assert 0.0 < sum(allocation.weights.values()) < 1.0


def test_a_book_already_at_the_proposal_is_kept_without_an_order(
    strategy: NeuralAllocationStrategy, contexts, neural_market: MarketDataReader
) -> None:
    proposed = strategy.proposal(contexts(neural_market))
    assert proposed is not None
    held = {A: proposed[A] + 0.01, B: proposed[B] - 0.01}

    allocation = strategy.decide(contexts(neural_market, held=held))

    assert allocation.hold_positions
    assert dict(allocation.weights) == pytest.approx(held)


def test_an_unusable_input_asks_for_cash_and_records_why(
    strategy: NeuralAllocationStrategy,
    contexts,
    make_neural_market: Callable[..., MarketDataReader],
) -> None:
    def stop_publishing(bars, levels) -> None:
        for day in [day for day in levels if day > date(2026, 9, 9)]:
            del levels[day]

    ctx = contexts(make_neural_market(mutate=stop_publishing), held={A: 0.40})

    allocation = strategy.decide(ctx)

    assert strategy.proposal(ctx) is None
    assert dict(allocation.weights) == {}
    assert not allocation.hold_positions
    assert allocation.considered == 0
    assert dict(allocation.skipped) == {
        A: SignalStatus.STALE_INPUT,
        B: SignalStatus.STALE_INPUT,
    }


def test_a_decision_at_or_before_the_information_cutoff_is_refused(
    strategy: NeuralAllocationStrategy, contexts, neural_market: MarketDataReader
) -> None:
    with pytest.raises(InformationCutoffError, match="starts after the cutoff"):
        strategy.decide(contexts(neural_market, day=date(2026, 8, 31)))
    with pytest.raises(InformationCutoffError, match="not after"):
        require_after_cutoff(strategy, evening(date(2026, 8, 31)))
    require_after_cutoff(strategy, evening(date(2026, 9, 1)))


def test_the_strategy_is_recorded_by_its_models_identity(
    strategy: NeuralAllocationStrategy, neural_artifact: NeuralArtifact
) -> None:
    definition = strategy.definition()
    again = NeuralAllocationStrategy.from_artifact(neural_artifact)

    strategy.validate()
    assert strategy.strategy_id == "ML1_neural_allocation"
    assert strategy.parameters()["model_id"] == neural_artifact.model_id
    assert strategy.parameters()["config"] == neural_artifact.config.definition()
    assert definition["signals"][0]["signal"]["model_id"] == neural_artifact.model_id  # type: ignore[index]
    assert definition["signals"][0]["instruments"] == [A, B]  # type: ignore[index]
    assert again.fingerprint() == strategy.fingerprint()
    assert again == strategy
    assert "_signal" not in repr(strategy)
    json.dumps(definition)
