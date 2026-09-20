"""The engine: one decision, several signals, and one immutable answer."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.level.zscore import LevelZScoreSignal
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.signals.windows import LoadedWindow

RAW = PriceBasis.RAW

SESSIONS: tuple[date, ...] = (
    date(2026, 9, 1),
    date(2026, 9, 2),
    date(2026, 9, 3),
    date(2026, 9, 4),
    date(2026, 9, 7),
    date(2026, 9, 8),
    date(2026, 9, 9),
    date(2026, 9, 10),
    date(2026, 9, 11),
    date(2026, 9, 14),
)
"""The ten Paris sessions the synthetic market spans."""


def three_signals() -> list[Signal]:
    """Return the three signals of a plain rotation strategy."""
    return [
        ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=RAW),
        MomentumSignal(
            signal_id="momentum_5d", lookback_sessions=5, skip_recent_sessions=1, price_basis=RAW
        ),
        RealizedVolatilitySignal(signal_id="volatility_4d", window_returns=4, price_basis=RAW),
    ]


@dataclass(frozen=True, slots=True)
class WrongInstant(Signal):
    """A signal that stamps its answer at some other moment."""

    signal_id: str = "wrong_instant"

    def definition(self) -> Mapping[str, object]:
        """Return an empty definition; this one exists to misbehave."""
        return {"type": "WrongInstant"}

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return a result dated a day after the context."""
        rows = {
            instrument_id: result_row(1.0, LoadedWindow(status=SignalStatus.OK, points=(1.0,)))
            for instrument_id in instrument_ids
        }
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of + timedelta(days=1),
            _frame=build_result_frame(rows),
            definition=self.definition(),
        )


def test_every_signal_is_computed_against_the_same_instant(
    context: SignalContext,
) -> None:
    """The snapshot is one decision, not three separate ones."""
    snapshot = SignalEngine().compute(context, three_signals(), ["ETF_EU", "IDX_US"])

    assert set(snapshot) == {"return_4d", "momentum_5d", "volatility_4d"}
    assert snapshot.as_of == context.as_of
    for signal_id in snapshot:
        assert snapshot.result(signal_id).as_of == context.as_of


def test_the_numbers_are_the_ones_each_signal_computes(context: SignalContext) -> None:
    """The engine centralises, it does not transform."""
    signals = three_signals()
    snapshot = SignalEngine().compute(context, signals, ["ETF_EU"])

    for signal in signals:
        alone = signal.compute(context, ["ETF_EU"])
        assert snapshot.values(signal.signal_id).equals(alone.frame)


def test_two_signals_sharing_an_id_are_refused(context: SignalContext) -> None:
    """One would replace the other in the snapshot, silently."""
    twice = [
        ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=RAW),
        ReturnSignal(signal_id="return_4d", lookback_sessions=9, price_basis=RAW),
    ]

    with pytest.raises(ValueError, match="share the id"):
        SignalEngine().compute(context, twice, ["ETF_EU"])


def test_an_instrument_asked_for_twice_is_refused(context: SignalContext) -> None:
    """A universe with a duplicate is a configuration mistake, not a weighting."""
    with pytest.raises(ValueError, match="twice"):
        SignalEngine().compute(context, three_signals(), ["ETF_EU", "ETF_EU"])


def test_a_result_stamped_elsewhere_is_refused(context: SignalContext) -> None:
    """A snapshot that mixed two instants would be unfalsifiable."""
    with pytest.raises(ValueError, match="stamped"):
        SignalEngine().compute(context, [WrongInstant()], ["ETF_EU"])


def test_an_empty_set_of_signals_is_an_empty_snapshot(context: SignalContext) -> None:
    """Nothing asked for, nothing computed, and still a well-formed answer."""
    snapshot = SignalEngine().compute(context, [], ["ETF_EU"])

    assert list(snapshot) == []
    assert snapshot.as_of == context.as_of


def test_the_same_series_is_read_once_per_decision(
    context: SignalContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three signals over the same closes are three formulas, one read.

    Not an optimisation for its own sake: it is what lets a backtest add a
    signal without multiplying its reads, and the cache lives and dies with the
    decision so no invalidation question outlives it.
    """
    reads: list[str] = []
    original = context.market.history

    def counting(instrument_id: str, *args: object, **kwargs: object) -> pd.Series:  # type: ignore[type-arg]
        reads.append(instrument_id)
        return original(instrument_id, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(context.market, "history", counting)

    SignalEngine().compute(context, three_signals(), ["ETF_EU"])

    assert reads == ["ETF_EU"]


def test_the_engine_does_not_advance_time(
    context: SignalContext,
    market: MarketDataReader,
    make_context: Callable[..., SignalContext],
    evening: Callable[[date], datetime],
    sessions: tuple[date, ...],
) -> None:
    """Two decisions are two contexts, built outside, and they do not interfere."""
    engine = SignalEngine()
    earlier = make_context(market, evening(sessions[-3]))

    now = engine.compute(context, three_signals(), ["ETF_EU"])
    then = engine.compute(earlier, three_signals(), ["ETF_EU"])

    assert now.as_of != then.as_of
    assert now.value("return_4d", "ETF_EU") != then.value("return_4d", "ETF_EU")


# --- the engine checks the answers it is given -------------------------------
#
# The signals here all go through one window loader and cannot get the shape
# wrong. A fitted model, later, will build its own frame, and a row quietly
# missing from it would leave a strategy ranking a universe it thinks is whole.


@dataclass(frozen=True, slots=True)
class Malformed(Signal):
    """A signal returning a frame broken in one chosen way."""

    signal_id: str
    breakage: str

    def definition(self) -> Mapping[str, object]:
        """Return a definition naming the breakage, so two instances differ."""
        return {"type": "Malformed", "breakage": self.breakage}

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return a result that breaks the contract in exactly one way."""
        names = list(instrument_ids)
        if self.breakage == "missing-instrument":
            names = names[:-1]
        elif self.breakage == "extra-instrument":
            names = [*names, "NOT_ASKED_FOR"]
        elif self.breakage == "reordered":
            names = list(reversed(names))
        elif self.breakage == "duplicate-index":
            names = [names[0], names[0]]
        rows = {
            name: result_row(1.0, LoadedWindow(status=SignalStatus.OK, points=(1.0,)))
            for name in names
        }
        frame = build_result_frame(rows)
        if self.breakage == "duplicate-index":
            frame = pd.concat([frame, frame])
        if self.breakage == "missing-column":
            frame = frame.drop(columns=["observations_used"])
        if self.breakage == "invalid-status":
            frame["status"] = "OK"
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=frame,
            definition=self.definition(),
        )


@pytest.mark.parametrize(
    ("breakage", "match"),
    [
        ("missing-instrument", "missing"),
        ("extra-instrument", "unasked for"),
        ("reordered", "another order"),
    ],
    ids=["missing-instrument", "extra-instrument", "reordered"],
)
def test_a_result_about_another_universe_is_refused(
    context: SignalContext, breakage: str, match: str
) -> None:
    """A strategy ranks what it was handed; the universe has to be the one asked for."""
    with pytest.raises(ValueError, match=match):
        SignalEngine().compute(
            context, [Malformed(signal_id="bad", breakage=breakage)], ["ETF_EU", "IDX_US"]
        )


@pytest.mark.parametrize(
    ("breakage", "match"),
    [
        ("duplicate-index", "more than once"),
        ("missing-column", "missing column"),
        ("invalid-status", "not a SignalStatus"),
    ],
    ids=["duplicate-index", "missing-column", "invalid-status"],
)
def test_a_malformed_frame_is_refused_when_it_is_built(
    context: SignalContext, breakage: str, match: str
) -> None:
    """Checked by SignalResult itself, so it holds outside the engine too."""
    with pytest.raises(ValueError, match=match):
        Malformed(signal_id="bad", breakage=breakage).compute(context, ["ETF_EU", "IDX_US"])


def test_one_signal_cannot_mutate_the_series_the_next_one_sees(
    context: SignalContext,
) -> None:
    """The cache is shared; what it hands out is not.

    A signal that normalised a series in place would change what every signal
    computed after it reads, and a snapshot would then depend on the order its
    signals happened to be listed in.
    """

    @dataclass(frozen=True, slots=True)
    class Vandal(Signal):
        signal_id: str = "vandal"

        def definition(self) -> Mapping[str, object]:
            return {"type": "Vandal"}

        def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
            for instrument_id in instrument_ids:
                series = context.series(instrument_id, BarField.CLOSE, RAW)
                series.iloc[:] = 0.0
            rows = {
                instrument_id: result_row(0.0, LoadedWindow(status=SignalStatus.OK, points=(1.0,)))
                for instrument_id in instrument_ids
            }
            return SignalResult(
                signal_id=self.signal_id,
                as_of=context.as_of,
                _frame=build_result_frame(rows),
                definition=self.definition(),
            )

    plain = ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=RAW)
    alone = plain.compute(context, ["ETF_EU"]).value("ETF_EU")

    after_the_vandal = SignalEngine().compute(context, [Vandal(), plain], ["ETF_EU"])

    assert after_the_vandal.value("return_4d", "ETF_EU") == alone


@dataclass(frozen=True, slots=True)
class Misrecorded(Signal):
    """A signal that computes one way and writes down another."""

    signal_id: str = "misrecorded"
    recorded: int = 20

    def definition(self) -> Mapping[str, object]:
        """Return the definition of this instance, lookback included."""
        return {"type": "Misrecorded", "lookback_sessions": self.recorded}

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return a result carrying a definition that is not this signal's."""
        rows = {
            instrument_id: result_row(1.0, LoadedWindow(status=SignalStatus.OK, points=(1.0,)))
            for instrument_id in instrument_ids
        }
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=build_result_frame(rows),
            definition={"type": "Misrecorded", "lookback_sessions": 60},
        )


def test_a_result_describing_another_calculation_is_refused(context: SignalContext) -> None:
    """The definition is the audit trail, and a wrong one is worse than none.

    A signal that computed over sixty sessions and recorded twenty gives a
    number nobody can reproduce from what was written down, and a fingerprint
    saying two different experiments were the same one.
    """
    with pytest.raises(ValueError, match="definition that is not its own"):
        SignalEngine().compute(context, [Misrecorded()], ["ETF_EU"])


def test_a_definition_holding_a_sequence_is_still_its_own(context: SignalContext) -> None:
    """Freezing turns a list into a tuple, which is not a disagreement.

    A cross-asset signal naming its inputs carries one, and comparing the
    frozen forms is what keeps it from failing on the shape of its container.
    """

    @dataclass(frozen=True, slots=True)
    class Listed(Signal):
        signal_id: str = "listed"

        def definition(self) -> Mapping[str, object]:
            return {"type": "Listed", "inputs": ["ETF_EU", "IDX_US"]}

        def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
            rows = {
                instrument_id: result_row(1.0, LoadedWindow(status=SignalStatus.OK, points=(1.0,)))
                for instrument_id in instrument_ids
            }
            return SignalResult(
                signal_id=self.signal_id,
                as_of=context.as_of,
                _frame=build_result_frame(rows),
                definition=self.definition(),
            )

    snapshot = SignalEngine().compute(context, [Listed()], ["ETF_EU"])

    assert snapshot.result("listed").definition["inputs"] == ("ETF_EU", "IDX_US")


# --- a signal may be asked about a universe of its own -----------------------


def test_a_signal_can_carry_its_own_universe(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    make_context: Callable[..., SignalContext],
    xpar: TradingCalendar,
    prices: Callable[..., dict[date, float]],
    evening: Callable[[date], datetime],
) -> None:
    """A yield and a fund in one snapshot, and neither asked about the other.

    This is what a cross-asset decision needs. Asked about the fund, the level
    signal would stop the run - a window over a fund is counted in sessions -
    and asked about the yield, the return signal would be measuring a
    difference of percentages as if it were a return.
    """
    rates = dict(zip(SESSIONS, [4.0 + 0.05 * step for step in range(len(SESSIONS))], strict=True))
    market = make_market(
        {"ETF_EU": make_bars("ETF_EU", xpar, prices(100.0, 1.0))},
        None,
        {"RATE_US": make_levels("RATE_US", rates)},
    )
    context = make_context(market, evening(SESSIONS[-1]))

    snapshot = SignalEngine().compute(
        context,
        [
            ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=RAW),
            SignalRequest(
                LevelZScoreSignal(signal_id="rate_z_5o", window_observations=5), ["RATE_US"]
            ),
        ],
        ["ETF_EU"],
    )

    assert snapshot.result("return_4d").instruments() == ("ETF_EU",)
    assert snapshot.result("rate_z_5o").instruments() == ("RATE_US",)
    assert snapshot.status("rate_z_5o", "RATE_US") is SignalStatus.OK
    # One instant, two universes: the property a snapshot exists for still holds.
    assert snapshot.as_of == context.as_of


def test_a_bare_signal_still_gets_the_snapshot_universe(context: SignalContext) -> None:
    """The old call is the new call with the universe left unsaid."""
    snapshot = SignalEngine().compute(context, three_signals(), ["ETF_EU", "IDX_US"])

    for signal_id in snapshot:
        assert snapshot.result(signal_id).instruments() == ("ETF_EU", "IDX_US")


def test_a_requests_own_universe_cannot_repeat_a_name(context: SignalContext) -> None:
    """It would be weighted twice in its own cross-section."""
    request = SignalRequest(
        ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=RAW),
        ["ETF_EU", "ETF_EU"],
    )

    with pytest.raises(ValueError, match="return_4d asks for ETF_EU twice"):
        SignalEngine().compute(context, [request], ["ETF_EU"])
