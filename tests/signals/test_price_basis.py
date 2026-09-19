"""Raw prices against total return, and the corporate action that separates them.

A distribution takes a price down without taking anything away from the holder.
Measured on quoted prices, a fund that pays two percent a year looks like a fund
that falls two percent a year - which is why the basis is a declared parameter
and not a default.

The adjustment uses only the actions knowable at the decision instant, so a
dividend announced afterwards cannot move a number that was already computed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import ActionType
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus

ContextBuilder = Callable[..., SignalContext]


def signal(basis: PriceBasis) -> ReturnSignal:
    """Build a four-session return on one basis or the other."""
    return ReturnSignal(
        signal_id=f"return_4d_{basis.value.lower()}",
        lookback_sessions=4,
        price_basis=basis,
    )


def test_a_distribution_separates_the_two_bases(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_actions: Callable[..., object],
    make_context: ContextBuilder,
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """The same prices and one dividend give two different, both correct, numbers."""
    ex_date = sessions[-2]
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        make_actions(
            [("ETF_EU", ActionType.DIVIDEND, ex_date, 2.0, datetime(2026, 9, 11, 7, 0, tzinfo=UTC))]
        ),
    )
    context = make_context(market, evening(sessions[-1]))

    raw = signal(PriceBasis.RAW).compute(context, ["ETF_EU"]).value("ETF_EU")
    total = signal(PriceBasis.TOTAL_RETURN).compute(context, ["ETF_EU"]).value("ETF_EU")

    assert raw == pytest.approx(109.0 / 105.0 - 1.0)
    assert total > raw


def test_an_action_announced_after_the_decision_changes_nothing(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_actions: Callable[..., object],
    make_context: ContextBuilder,
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """The look-ahead guard, on the input that is easiest to forget.

    A split known only the next morning would rescale every adjusted price
    before it. A total-return signal taken tonight must not feel it.
    """
    closes = prices(100.0, 1.0)
    without = make_market({"ETF_EU": make_bars("ETF_EU", xpar, closes)})
    before = signal(PriceBasis.TOTAL_RETURN).compute(
        make_context(without, evening(sessions[-1])), ["ETF_EU"]
    )

    with_split = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, closes)},
        make_actions(
            [
                (
                    "ETF_EU",
                    ActionType.SPLIT,
                    sessions[-3],
                    4.0,
                    datetime(2026, 9, 15, 7, 0, tzinfo=UTC),
                )
            ]
        ),
    )
    after = signal(PriceBasis.TOTAL_RETURN).compute(
        make_context(with_split, evening(sessions[-1])), ["ETF_EU"]
    )

    assert after.frame.equals(before.frame)


def test_the_basis_is_part_of_the_identity() -> None:
    """Two returns differing only by their basis are two different signals."""
    assert signal(PriceBasis.RAW).fingerprint() != signal(PriceBasis.TOTAL_RETURN).fingerprint()
    assert signal(PriceBasis.RAW).definition()["price_basis"] == "RAW"


def test_total_return_on_a_field_other_than_the_close_is_refused(
    context: SignalContext,
) -> None:
    """The adjusted series is a closing series; there is no adjusted high.

    A configuration mistake rather than a status: silently reading the close
    when the open was asked for would be worse than failing.
    """
    from quant_backtester.data.schemas import BarField

    asking_for_the_open = ReturnSignal(
        signal_id="return_4d_open",
        lookback_sessions=4,
        price_basis=PriceBasis.TOTAL_RETURN,
        bar_field=BarField.OPEN,
    )

    with pytest.raises(ValueError, match="TOTAL_RETURN"):
        asking_for_the_open.compute(context, ["ETF_EU"])


def test_both_bases_agree_when_nothing_was_paid(context: SignalContext) -> None:
    """With no action in the window, the adjustment is the identity."""
    raw = signal(PriceBasis.RAW).compute(context, ["ETF_EU"])
    total = signal(PriceBasis.TOTAL_RETURN).compute(context, ["ETF_EU"])

    assert total.status("ETF_EU") is SignalStatus.OK
    assert total.value("ETF_EU") == pytest.approx(raw.value("ETF_EU"))
