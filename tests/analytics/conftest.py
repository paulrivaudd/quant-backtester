"""A finished run, written by hand.

Analytics is a function of a curve, so its tests are about curves and not about
the engine: every number below is small enough to check on paper, and no test
here has to run a backtest to find out what a drawdown is. The one test that
does run the engine lives in ``test_report.py``, and its job is to check that
the two layers meet, not to check arithmetic.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta

import pytest

from quant_backtester.backtest.engine import BacktestRecord, BacktestResult

START = date(2026, 1, 5)
"""First session of a hand-written run."""

RunBuilder = Callable[..., BacktestResult]


def sessions_from(start: date, count: int, step_days: int) -> list[date]:
    """Return ``count`` session dates, ``step_days`` apart."""
    return [start + timedelta(days=step_days * position) for position in range(count)]


def make_run(
    equity: Sequence[float],
    *,
    gross: Sequence[float] | None = None,
    start: date = START,
    step_days: int = 1,
    initial_cash: float | None = None,
    commission: Sequence[float] | None = None,
    market_cost: Sequence[float] | None = None,
    traded_value: Sequence[float] | None = None,
    considered: int = 2,
    cash: Sequence[float] | None = None,
    untradable: Sequence[tuple[str, ...]] | None = None,
    unfunded: Sequence[tuple[str, ...]] | None = None,
    priced_from_earlier: Sequence[tuple[str, ...]] | None = None,
) -> BacktestResult:
    """Return a run whose records say exactly what the test needs them to say.

    Parameters
    ----------
    equity : Sequence[float]
        The net book, session by session.
    gross : Sequence[float] | None
        The book that paid nothing; the net one again when left out.
    start : date
        First session.
    step_days : int
        Calendar days between two sessions. One by default, so that a run of
        366 of them covers a year.
    initial_cash : float | None
        What the run started with; the first equity when left out.
    commission, market_cost, traded_value : Sequence[float] | None
        Per session, zero everywhere when left out.
    considered : int
        Instruments the strategy had to choose among, the same on every
        session.
    cash : Sequence[float] | None
        The uninvested part per session, zero everywhere when left out.
    untradable, unfunded, priced_from_earlier : Sequence[tuple[str, ...]] | None
        Per session, empty everywhere when left out.

    Returns
    -------
    BacktestResult
        A run holding one record per equity given.
    """
    dates = sessions_from(start, len(equity), step_days)
    gross_book = list(gross) if gross is not None else list(equity)
    zeros = [0.0] * len(equity)
    nothing: list[tuple[str, ...]] = [() for _ in equity]
    records = tuple(
        BacktestRecord(
            session_date=session,
            decision_at=datetime.combine(session, datetime.min.time(), tzinfo=UTC),
            equity=net,
            gross_equity=gross_book[position],
            cash=(cash or zeros)[position],
            invested=1.0,
            considered=considered,
            traded_value=(traded_value or zeros)[position],
            commission=(commission or zeros)[position],
            market_cost=(market_cost or zeros)[position],
            untradable=(untradable or nothing)[position],
            unfunded=(unfunded or nothing)[position],
            priced_from_earlier=(priced_from_earlier or nothing)[position],
            weights={},
        )
        for position, (session, net) in enumerate(zip(dates, equity, strict=True))
    )
    return BacktestResult(
        records=records,
        initial_cash=initial_cash if initial_cash is not None else (equity[0] if equity else 0.0),
    )


@pytest.fixture
def run() -> RunBuilder:
    """Return the builder of a hand-written run."""
    return make_run
