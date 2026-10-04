"""Fixtures for deciding on signals of known value.

A rule is a function of its signals, so its decision is tested on signals
whose values the test writes: one stand-in per declared signal, with the same
id and the same instruments, computed by the real engine into a real snapshot.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.portfolio.state import PortfolioState
from quant_backtester.signals.base import Signal, SignalResult, build_result_frame, result_row
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.types import SignalStatus
from quant_backtester.signals.windows import LoadedWindow
from quant_backtester.strategies.base import Strategy

Written = Mapping[tuple[str, str], float | SignalStatus]
"""A value, or a status other than ``OK``, per ``(signal_id, instrument_id)``."""

WrittenDecision = Callable[..., StrategyContext]

BOOK_EQUITY = 10_000.0
"""What a hand-built book is worth."""

BOOK_PRICE = 100.0
"""The price every held fund is valued at, so a weight is a quantity over one hundred."""


class WrittenSignal(Signal):
    """A signal whose value for each instrument is written by the test."""

    def __init__(self, signal_id: str, values: Mapping[str, float | SignalStatus]) -> None:
        self.signal_id = signal_id
        self._values = dict(values)

    def definition(self) -> Mapping[str, object]:
        """Return what identifies this stand-in."""
        return {"type": "WrittenSignal", "signal_id": self.signal_id}

    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Return the written value, or the written status, of each instrument."""
        rows: dict[str, Mapping[str, object]] = {}
        for instrument_id in instrument_ids:
            written = self._values[instrument_id]
            if isinstance(written, SignalStatus):
                rows[instrument_id] = result_row(None, LoadedWindow(status=written))
            else:
                window = LoadedWindow(status=SignalStatus.OK, points=(1.0,), age_sessions=0)
                rows[instrument_id] = result_row(written, window)
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=build_result_frame(rows),
            definition=self.definition(),
        )


@pytest.fixture
def written_decision(
    context: SignalContext,
    make_decision: Callable[..., StrategyContext],
    make_book: Callable[..., PortfolioState],
) -> WrittenDecision:
    """Return a builder of the decision a strategy sees on written signal values.

    The builder takes the strategy, a value per ``(signal_id, instrument_id)``
    it declares - a missing one is a ``KeyError``, so a test cannot forget a
    signal - the trading universe, and the weights the book already holds.
    """

    def build(
        strategy: Strategy,
        values: Written,
        *,
        universe: Sequence[str],
        held: Mapping[str, float] | None = None,
    ) -> StrategyContext:
        requests = []
        for item in strategy.required_signals():
            # A bare signal is computed over the trading universe, as the engine does.
            names = item.names() if isinstance(item, SignalRequest) else tuple(universe)
            assert names is not None
            signal_id = (item.signal if isinstance(item, SignalRequest) else item).signal_id
            requests.append(
                SignalRequest(
                    WrittenSignal(signal_id, {name: values[signal_id, name] for name in names}),
                    tuple(names),
                )
            )
        snapshot = SignalEngine().compute(context, requests, list(universe))
        weights = dict(held or {})
        book = make_book(
            BOOK_EQUITY * (1.0 - sum(weights.values())),
            {name: weight * BOOK_EQUITY / BOOK_PRICE for name, weight in weights.items()},
        )
        return make_decision(
            context,
            snapshot,
            universe=tuple(universe),
            holdings=book,
            prices=dict.fromkeys(weights, BOOK_PRICE),
        )

    return build
