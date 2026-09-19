"""CrossSectionalRank: a position in a universe, and who is not in it.

The ranking itself is arithmetic. What this file is really about is the
exclusion rule: an instrument whose own signal is not usable must not be handed
the bottom of the ranking, because "the worst of the universe" and "we do not
know" would then be the same number.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_sectional.rank import CROSS_SECTION_SIZE, CrossSectionalRank
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.signals.windows import LoadedWindow


@dataclass(frozen=True, slots=True)
class Fixed(Signal):
    """A signal returning values decided by the test, statuses included."""

    signal_id: str
    values: Mapping[str, float | SignalStatus]

    def definition(self) -> Mapping[str, object]:
        """Return a definition that distinguishes two instances."""
        return {"type": "Fixed", "values": {key: str(value) for key, value in self.values.items()}}

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return the values it was built with, in the order asked for."""
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


def ranked(
    context: SignalContext,
    values: Mapping[str, float | SignalStatus],
    **overrides: object,
) -> SignalResult:
    """Rank a set of decided values and return the result."""
    parameters: dict[str, object] = {
        "signal_id": "momentum_rank",
        "source": Fixed(signal_id="momentum", values=values),
    }
    parameters.update(overrides)
    return CrossSectionalRank(**parameters).compute(  # type: ignore[arg-type]
        context, list(values)
    )


def test_the_best_gets_one_and_the_worst_gets_zero(context: SignalContext) -> None:
    """The example of the specification, worked out on four instruments."""
    result = ranked(
        context,
        {"NASDAQ": 0.15, "ETF_EU": 0.09, "IDX_US": 0.05, "ETF_LATE": -0.02},
    )

    assert result.value("NASDAQ") == pytest.approx(1.0)
    assert result.value("ETF_EU") == pytest.approx(2.0 / 3.0)
    assert result.value("IDX_US") == pytest.approx(1.0 / 3.0)
    assert result.value("ETF_LATE") == pytest.approx(0.0)


def test_ascending_puts_the_smallest_on_top(context: SignalContext) -> None:
    """Ranking a volatility or a drawdown wants the other direction, said out loud."""
    values = {"ETF_EU": 0.09, "IDX_US": 0.21, "ETF_LATE": 0.14}

    low_is_best = ranked(context, values, ascending=True)

    assert low_is_best.value("ETF_EU") == pytest.approx(1.0)
    assert low_is_best.value("IDX_US") == pytest.approx(0.0)


def test_equal_values_share_the_average_of_their_ranks(context: SignalContext) -> None:
    """Two identical numbers cannot be separated by the order they were asked in."""
    result = ranked(context, {"ETF_EU": 0.10, "IDX_US": 0.10, "ETF_LATE": 0.02})

    assert result.value("ETF_EU") == result.value("IDX_US")
    assert result.value("ETF_EU") == pytest.approx(0.75)
    assert result.value("ETF_LATE") == pytest.approx(0.0)


def test_an_unusable_instrument_is_left_out_rather_than_ranked_last(
    context: SignalContext,
) -> None:
    """The rule this component exists for.

    A fund whose data is late must not be handed the bottom of the ranking: a
    strategy selling the worst names would be selling the ones it knows least
    about.
    """
    result = ranked(
        context,
        {
            "ETF_EU": 0.15,
            "IDX_US": SignalStatus.MISSING_INPUT,
            "ETF_LATE": 0.05,
            "NASDAQ": SignalStatus.NOT_LISTED,
        },
    )

    assert result.status("IDX_US") is SignalStatus.MISSING_INPUT
    assert result.status("NASDAQ") is SignalStatus.NOT_LISTED
    for excluded in ("IDX_US", "NASDAQ"):
        assert result.value(excluded) != result.value(excluded)  # NaN, never 0.0

    # And the two that remain are ranked against each other, not against four.
    assert result.value("ETF_EU") == pytest.approx(1.0)
    assert result.value("ETF_LATE") == pytest.approx(0.0)


def test_the_size_of_the_sample_is_visible(context: SignalContext) -> None:
    """A rank of 1.00 out of nine and out of two are not the same statement."""
    result = ranked(
        context,
        {"ETF_EU": 0.15, "IDX_US": SignalStatus.STALE_INPUT, "ETF_LATE": 0.05},
    )

    assert (result.frame[CROSS_SECTION_SIZE] == 2).all()


def test_a_cross_section_too_thin_is_refused(context: SignalContext) -> None:
    """One usable instrument is both the best and the worst of itself."""
    result = ranked(context, {"ETF_EU": 0.15, "IDX_US": SignalStatus.MISSING_INPUT})

    assert result.status("ETF_EU") is SignalStatus.INSUFFICIENT_CROSS_SECTION
    assert result.value("ETF_EU") != result.value("ETF_EU")
    assert result.status("IDX_US") is SignalStatus.MISSING_INPUT


def test_how_thin_is_too_thin_is_declared(context: SignalContext) -> None:
    """A strategy needing four names to rank can say so, and be refused at three."""
    values = {"ETF_EU": 0.15, "IDX_US": 0.09, "ETF_LATE": 0.05}

    loose = ranked(context, values, min_instruments=2)
    strict = ranked(context, values, min_instruments=4)

    assert loose.status("ETF_EU") is SignalStatus.OK
    assert strict.status("ETF_EU") is SignalStatus.INSUFFICIENT_CROSS_SECTION


def test_the_diagnostics_of_the_ranked_signal_are_carried_through(
    context: SignalContext,
) -> None:
    """A rank is only as good as the window underneath it, so the window shows."""
    source = ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW)
    rank = CrossSectionalRank(signal_id="return_4d_rank", source=source)

    inner = source.compute(context, ["ETF_EU", "IDX_US"])
    outer = rank.compute(context, ["ETF_EU", "IDX_US"])

    for column in ("input_start_date", "input_end_date", "observations_used"):
        assert outer.frame[column].equals(inner.frame[column])


def test_a_window_that_is_not_one_is_never_ranked(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., object],
    make_context: Callable[..., SignalContext],
    evening: Callable[[date], datetime],
    prices: Callable[..., dict[date, float]],
    sessions: tuple[date, ...],
    xpar: TradingCalendar,
) -> None:
    """The whole chain, on real windows: a gap upstream is a gap in the ranking."""
    market = make_market(
        {
            "ETF_EU": make_bars(
                "ETF_EU", xpar, prices(100.0, 1.0), contested={sessions[-3]: [BarField.CLOSE]}
            ),
            "IDX_US": make_bars("IDX_US", xpar, prices(200.0, 2.0)),
        }
    )
    context = make_context(market, evening(sessions[-1]))
    rank = CrossSectionalRank(
        signal_id="return_4d_rank",
        source=ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW),
    )

    result = rank.compute(context, ["ETF_EU", "IDX_US"])

    assert result.status("ETF_EU") is SignalStatus.NON_CONSECUTIVE_HISTORY
    assert result.status("IDX_US") is SignalStatus.INSUFFICIENT_CROSS_SECTION  # one name left


def test_the_source_is_part_of_the_identity(context: SignalContext) -> None:
    """Two rankings of two different momenta are two different signals."""
    four = CrossSectionalRank(
        signal_id="rank",
        source=ReturnSignal(signal_id="r", lookback_sessions=4, price_basis=PriceBasis.RAW),
    )
    nine = CrossSectionalRank(
        signal_id="rank",
        source=ReturnSignal(signal_id="r", lookback_sessions=9, price_basis=PriceBasis.RAW),
    )

    assert four.fingerprint() != nine.fingerprint()
    assert dict(four.definition())["unit"] == "RANK"


def test_the_engine_computes_a_ranking_like_any_other_signal(
    context: SignalContext,
) -> None:
    """A strategy reads a rank out of the snapshot; it never ranks anything itself."""
    source = ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW)
    snapshot = SignalEngine().compute(
        context,
        [source, CrossSectionalRank(signal_id="return_4d_rank", source=source)],
        ["ETF_EU", "IDX_US"],
    )

    assert snapshot.value("return_4d_rank", "ETF_EU") in (0.0, 1.0)
    assert snapshot.as_of == context.as_of


@pytest.mark.parametrize("minimum", [1, 0, -2])
def test_a_cross_section_of_fewer_than_two_is_refused(minimum: int) -> None:
    """Not a status: ranking one instrument is a question with no meaning."""
    with pytest.raises(ValueError, match="min_instruments"):
        CrossSectionalRank(
            signal_id="rank",
            source=ReturnSignal(signal_id="r", lookback_sessions=4, price_basis=PriceBasis.RAW),
            min_instruments=minimum,
        )
