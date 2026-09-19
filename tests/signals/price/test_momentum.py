"""MomentumSignal: the same shape as a return, and the skip that makes it one."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import pytest

from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus

ContextBuilder = Callable[..., SignalContext]


def signal(lookback: int = 5, skip: int = 0, **overrides: object) -> MomentumSignal:
    """Build a momentum signal with the usual defaults."""
    parameters: dict[str, object] = {
        "signal_id": f"momentum_{lookback}d_skip{skip}",
        "lookback_sessions": lookback,
        "skip_recent_sessions": skip,
        "price_basis": PriceBasis.RAW,
    }
    parameters.update(overrides)
    return MomentumSignal(**parameters)  # type: ignore[arg-type]


def test_the_formula_with_nothing_skipped(context: SignalContext) -> None:
    """Five sessions back from 109 is 104, so the momentum is 109/104 - 1."""
    result = signal(5, 0).compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(109.0 / 104.0 - 1.0)


def test_the_skip_moves_the_end_of_the_measurement(context: SignalContext) -> None:
    """Skipping two sessions compares 107 with 104, not 109 with 104.

    That is the point of the parameter: a twelve-month momentum measured to
    last month, with the recent reversal left out of it.
    """
    result = signal(5, 2).compute(context, ["ETF_EU"])

    assert result.value("ETF_EU") == pytest.approx(107.0 / 104.0 - 1.0)


def test_the_window_still_reaches_the_present(context: SignalContext) -> None:
    """A skipped session is left out of the formula, not out of the window.

    The freshest price still has to be there and be fresh enough: a momentum
    computed on a fund that stopped trading a month ago is not a momentum.
    """
    row = signal(5, 2).compute(context, ["ETF_EU"]).frame.loc["ETF_EU"]

    assert row["observations_used"] == 6
    assert row["max_input_age_sessions"] == 0


def test_with_no_skip_it_agrees_with_a_return(context: SignalContext) -> None:
    """The same number, and deliberately not the same signal.

    Keeping the two apart is what lets the skip be turned on later without an
    existing id quietly starting to mean something else.
    """
    momentum = signal(5, 0).compute(context, ["ETF_EU"])
    plain = ReturnSignal(
        signal_id="return_5d", lookback_sessions=5, price_basis=PriceBasis.RAW
    ).compute(context, ["ETF_EU"])

    assert momentum.value("ETF_EU") == plain.value("ETF_EU")
    assert momentum.definition != plain.definition


def test_a_later_session_does_not_change_an_earlier_momentum(
    make_market: Callable[..., object],
    make_bars: Callable[..., object],
    make_context: ContextBuilder,
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: object,
) -> None:
    """The look-ahead guard, on the signal that reaches furthest back."""
    closes = prices(100.0, 1.0)
    before = signal(5, 1).compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)}), evening(sessions[-1])
        ),
        ["ETF_EU"],
    )

    with_future = dict(closes)
    with_future[date(2026, 9, 15)] = 500.0
    after = signal(5, 1).compute(
        make_context(
            make_market({"ETF_EU": make_bars("ETF_EU", xpar, with_future)}), evening(sessions[-1])
        ),
        ["ETF_EU"],
    )

    assert after.frame.equals(before.frame)


@pytest.mark.parametrize(
    ("lookback", "skip", "match"),
    [
        (5, 5, "below"),
        (5, 6, "below"),
        (0, 0, "lookback_sessions"),
        (5, -1, "skip_recent_sessions"),
    ],
    ids=["skip-equals-lookback", "skip-above-lookback", "zero-lookback", "negative-skip"],
)
def test_an_impossible_configuration_stops_the_run(lookback: int, skip: int, match: str) -> None:
    """Skipping everything the window measures leaves nothing to measure."""
    with pytest.raises(ValueError, match=match):
        signal(lookback, skip)


def test_the_skip_is_part_of_the_identity() -> None:
    """Two momenta differing only by their skip are two different signals."""
    assert signal(5, 0).fingerprint() != signal(5, 2).fingerprint()
