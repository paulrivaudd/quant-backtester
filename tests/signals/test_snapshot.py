"""The snapshot: what a strategy is allowed to hold, and what it cannot do with it."""

from __future__ import annotations

import pytest

from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import PriceBasis, SignalStatus


@pytest.fixture
def snapshot(context: SignalContext) -> SignalSnapshot:
    """Return a snapshot holding one return over three instruments."""
    signal = ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW)
    return SignalEngine().compute(context, [signal], ["ETF_EU", "IDX_US", "ETF_LATE"])


def test_a_strategy_reads_a_number_without_knowing_where_it_came_from(
    snapshot: SignalSnapshot,
) -> None:
    """No Yahoo, no Parquet, no calendar, no field availability: a number."""
    assert snapshot.value("return_4d", "ETF_EU") == pytest.approx(109.0 / 105.0 - 1.0)


def test_it_also_says_why_a_number_is_missing(snapshot: SignalSnapshot) -> None:
    """The four ways of having none stay four different things."""
    assert snapshot.status("return_4d", "ETF_EU") is SignalStatus.OK
    assert snapshot.status("return_4d", "ETF_LATE") is SignalStatus.INSUFFICIENT_HISTORY


def test_the_usable_rows_can_be_taken_apart_from_the_rest(
    snapshot: SignalSnapshot,
) -> None:
    """A cross-section is built on the instruments that have a number."""
    usable = snapshot.result("return_4d").ok()

    assert list(usable.index) == ["ETF_EU", "IDX_US"]
    assert len(snapshot.values("return_4d")) == 3


def test_asking_for_a_signal_that_was_not_computed_is_loud(
    snapshot: SignalSnapshot,
) -> None:
    """A strategy naming a signal the engine was not given is a wiring mistake."""
    with pytest.raises(KeyError, match="momentum_60d"):
        snapshot.result("momentum_60d")


def test_a_snapshot_cannot_be_reassigned(snapshot: SignalSnapshot) -> None:
    """Immutable: a strategy cannot change what it was handed."""
    with pytest.raises((AttributeError, TypeError)):
        snapshot.as_of = snapshot.as_of  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot.results["return_4d"] = snapshot.result("return_4d")  # type: ignore[index]


def test_a_snapshot_refuses_a_result_from_another_instant(
    snapshot: SignalSnapshot,
) -> None:
    """Every number in it answers the same question, asked once."""
    other = snapshot.as_of.replace(year=2027)

    with pytest.raises(ValueError, match="not at the snapshot"):
        SignalSnapshot(as_of=other, results=dict(snapshot.results))


def test_membership_reads_naturally(snapshot: SignalSnapshot) -> None:
    """A strategy can ask whether a signal is there before reaching for it."""
    assert "return_4d" in snapshot
    assert "momentum_60d" not in snapshot
