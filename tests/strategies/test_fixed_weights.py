"""FixedWeights: a constant target, the common band, and what it refuses."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.demo import demo_runner
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.strategies import FixedWeights

UNIVERSE = ("ETF_EU", "ETF_OTHER")
BOOK = FixedWeights(weights=(("ETF_EU", 0.6), ("ETF_OTHER", 0.2)))


@pytest.fixture
def decide(written_decision: Callable[..., StrategyContext]):
    """Return what the book decides from given holdings; it reads no signal."""

    def run(strategy: FixedWeights, held: dict[str, float] | None = None) -> TargetAllocation:
        return strategy.decide(written_decision(strategy, {}, universe=UNIVERSE, held=held))

    return run


def test_from_cash_the_constant_target_is_sent(decide) -> None:
    allocation = decide(BOOK)

    assert not allocation.hold_positions
    assert dict(allocation.weights) == {"ETF_EU": 0.6, "ETF_OTHER": 0.2}
    assert allocation.considered == 2
    assert BOOK.required_signals() == ()


def test_inside_the_band_the_book_is_kept_and_outside_it_is_traded_back(decide) -> None:
    kept = decide(BOOK, {"ETF_EU": 0.62, "ETF_OTHER": 0.19})
    traded = decide(BOOK, {"ETF_EU": 0.64, "ETF_OTHER": 0.19})

    assert kept.hold_positions
    assert not traded.hold_positions
    assert dict(traded.weights) == {"ETF_EU": 0.6, "ETF_OTHER": 0.2}


def test_the_weights_are_what_identifies_the_book() -> None:
    other = FixedWeights(weights=(("ETF_EU", 0.5), ("ETF_OTHER", 0.2)))

    assert BOOK.fingerprint() != other.fingerprint()
    same = FixedWeights(weights=(("ETF_EU", 0.6), ("ETF_OTHER", 0.2)))
    assert BOOK.fingerprint() == same.fingerprint()
    assert BOOK.parameters()["weights"] == [["ETF_EU", 0.6], ["ETF_OTHER", 0.2]]


@pytest.mark.parametrize(
    "build",
    [
        lambda: FixedWeights(weights=()),
        lambda: FixedWeights(weights=(("ETF_EU", 0.0),)),
        lambda: FixedWeights(weights=(("ETF_EU", 1.2),)),
        lambda: FixedWeights(weights=(("ETF_EU", float("nan")),)),
        lambda: FixedWeights(weights=(("ETF_EU", 0.6), ("ETF_EU", 0.2))),
        lambda: FixedWeights(weights=(("ETF_EU", 0.6), ("ETF_OTHER", 0.5))),
        lambda: FixedWeights(weights=(("", 0.5),)),
        lambda: FixedWeights(weights=(("ETF_EU", 0.5),), rebalance_band=1.5),
    ],
)
def test_a_book_that_cannot_be_held_is_refused(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        build()


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return a runner over the offline synthetic market."""
    return demo_runner(tmp_path_factory.mktemp("fixed_weights") / "store", seed=20240101)


def test_a_run_stays_within_the_band_of_its_target(demo: StrategyRunner) -> None:
    result = demo.run(
        FixedWeights(weights=(("FUND_A", 0.5),)), ("FUND_A", "FUND_B"), "2025-01-02", "2025-12-31"
    )

    held = result.weights()["FUND_A"].iloc[1:]
    assert len(result.fills()) >= 1
    # A drift past the band is seen at a close and traded back at the next open.
    assert held.between(0.44, 0.56).all()
    assert abs(float(held.mean()) - 0.5) < 0.02
    assert set(result.fills()["instrument_id"]) == {"FUND_A"}
