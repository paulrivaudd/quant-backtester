"""The engine: one decision, several signals, and one immutable answer."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.risk.volatility import RealizedVolatilitySignal
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.signals.windows import LoadedWindow

RAW = PriceBasis.RAW


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
