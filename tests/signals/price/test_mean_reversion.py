"""MeanReversionSignal: the same arithmetic as a return, pointing the other way."""

from __future__ import annotations

import pytest

from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.price.mean_reversion import MeanReversionSignal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus


def signal(lookback: int = 4, **overrides: object) -> MeanReversionSignal:
    """Build a mean reversion signal with the usual defaults."""
    parameters: dict[str, object] = {
        "signal_id": f"reversion_{lookback}d",
        "lookback_sessions": lookback,
        "price_basis": PriceBasis.RAW,
    }
    parameters.update(overrides)
    return MeanReversionSignal(**parameters)  # type: ignore[arg-type]


def test_the_formula_on_a_hand_checkable_series(context: SignalContext) -> None:
    """The prices rose from 105 to 109, so the reversion signal is negative."""
    result = signal(4).compute(context, ["ETF_EU"])

    assert result.status("ETF_EU") is SignalStatus.OK
    assert result.value("ETF_EU") == pytest.approx(-(109.0 / 105.0 - 1.0))
    assert result.value("ETF_EU") < 0


def test_a_fall_gives_a_positive_signal(
    make_market, make_bars, make_context, evening, sessions, xpar
) -> None:
    """What the hypothesis is about: the more it dropped, the higher the score."""
    falling = {session: 120.0 - 2.0 * index for index, session in enumerate(sessions)}
    market = make_market({"ETF_EU": make_bars("ETF_EU", xpar, falling)})

    result = signal(4).compute(make_context(market, evening(sessions[-1])), ["ETF_EU"])

    assert result.value("ETF_EU") > 0
    assert result.value("ETF_EU") == pytest.approx(-(102.0 / 110.0 - 1.0))


def test_it_is_the_exact_opposite_of_a_return(context: SignalContext) -> None:
    """The same window, the same prices, the sign moved into the signal.

    Putting the minus sign here rather than in the strategy is what lets the
    strategy stay a rule about ranks instead of a rule about directions.
    """
    reversion = signal(4).compute(context, ["ETF_EU"])
    plain = ReturnSignal(
        signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW
    ).compute(context, ["ETF_EU"])

    assert reversion.value("ETF_EU") == pytest.approx(-plain.value("ETF_EU"))
    assert reversion.definition != plain.definition


def test_it_is_not_divided_by_a_volatility(context: SignalContext) -> None:
    """The normalised version is a different quantity, and will be a different id.

    A move in standard deviations is not a move in percent; adding the division
    behind a flag would change what an existing id means.
    """
    definition = dict(signal(4).definition())

    assert definition["unit"] == "FRACTION"
    assert "volatility" not in str(definition)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"lookback_sessions": 0}, "lookback_sessions"),
        ({"max_age_sessions": -1}, "max_age_sessions"),
    ],
    ids=["zero-lookback", "negative-age"],
)
def test_an_impossible_configuration_stops_the_run(
    overrides: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        signal(4, **overrides)
