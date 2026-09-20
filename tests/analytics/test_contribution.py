"""Taking a run apart by instrument, with numbers small enough to check on paper.

The decomposition is exact by construction, so the test that matters is the one
that adds it back up: an attribution that does not reconcile with the equity it
explains is a table of plausible numbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta

import pytest

from quant_backtester.analytics.contribution import InstrumentAttribution
from quant_backtester.backtest.engine import BacktestRecord, BacktestResult
from quant_backtester.execution.costs import Side
from quant_backtester.execution.fills import Fill

START = date(2026, 1, 5)
"""First session of a hand-written run."""


def buy(instrument_id: str, quantity: float, price: float, *, commission: float = 0.0) -> Fill:
    """Return a purchase done at the reference price."""
    return Fill(
        instrument_id=instrument_id,
        side=Side.BUY,
        quantity=quantity,
        reference_price=price,
        fill_price=price,
        commission=commission,
    )


def sell(instrument_id: str, quantity: float, price: float, *, commission: float = 0.0) -> Fill:
    """Return a sale done at the reference price."""
    return Fill(
        instrument_id=instrument_id,
        side=Side.SELL,
        quantity=quantity,
        reference_price=price,
        fill_price=price,
        commission=commission,
    )


def run_of(
    sessions: Sequence[tuple[float, Mapping[str, float], Mapping[str, float], Sequence[Fill]]],
) -> BacktestResult:
    """Build a run from ``(equity, quantities, closes, fills)`` per session."""
    records = []
    for position, (equity, quantities, closes, fills) in enumerate(sessions):
        session_date = START + timedelta(days=position)
        records.append(
            BacktestRecord(
                session_date=session_date,
                decision_at=datetime.combine(session_date, datetime.min.time(), tzinfo=UTC),
                equity=equity,
                gross_equity=equity,
                cash=equity - sum(quantities[name] * closes[name] for name in quantities),
                target_invested=1.0,
                actual_invested=1.0,
                considered=2,
                traded_value=sum(fill.traded_value for fill in fills),
                commission=sum(fill.commission for fill in fills),
                market_cost=sum(fill.market_cost for fill in fills),
                untradable=(),
                unfunded=(),
                priced_from_earlier=(),
                weights={},
                quantities=dict(quantities),
                fills=tuple(fills),
                closes=dict(closes),
            )
        )
    return BacktestResult(records=tuple(records), initial_cash=sessions[0][0])


def one_fund_bought_and_held() -> BacktestResult:
    """Return a run that buys ten units at 100 and watches them reach 110."""
    return run_of(
        [
            (1_000.0, {}, {}, []),
            (1_050.0, {"A": 10.0}, {"A": 105.0}, [buy("A", 10.0, 100.0)]),
            (1_100.0, {"A": 10.0}, {"A": 110.0}, []),
        ]
    )


def test_an_instrument_carries_what_holding_it_added() -> None:
    """Ten units bought at 100 and worth 110: a hundred, and no other source."""
    attribution = InstrumentAttribution.of(one_fund_bought_and_held())

    assert attribution.get("A").pnl == pytest.approx(100.0)


def test_the_parts_add_up_to_what_the_book_did() -> None:
    """The reconciliation, which is the only thing that makes the parts mean anything."""
    attribution = InstrumentAttribution.of(one_fund_bought_and_held())

    assert attribution.total_pnl == pytest.approx(100.0)
    assert attribution.unexplained == pytest.approx(0.0, abs=1e-9)


def test_a_position_followed_across_sessions_is_one_figure() -> None:
    """Not a sum of round trips: a fund held through a fall and a rise is one story."""
    result = run_of(
        [
            (1_000.0, {}, {}, []),
            (1_000.0, {"A": 10.0}, {"A": 100.0}, [buy("A", 10.0, 100.0)]),
            (900.0, {"A": 10.0}, {"A": 90.0}, []),
            (1_200.0, {"A": 10.0}, {"A": 120.0}, []),
            (1_200.0, {}, {}, [sell("A", 10.0, 120.0)]),
        ]
    )

    attribution = InstrumentAttribution.of(result)

    assert attribution.get("A").pnl == pytest.approx(200.0)
    assert attribution.get("A").sessions_held == 3


def test_a_sale_closes_the_position_without_inventing_a_gain() -> None:
    """Selling at the price the book was marked at changes nothing but the form.

    A run always starts on cash - nothing is filled on its first session - so
    the opening session is part of the arithmetic rather than a state the
    decomposition has to be told about.
    """
    result = run_of(
        [
            (1_000.0, {}, {}, []),
            (1_000.0, {"A": 10.0}, {"A": 100.0}, [buy("A", 10.0, 100.0)]),
            (1_000.0, {}, {}, [sell("A", 10.0, 100.0)]),
        ]
    )

    attribution = InstrumentAttribution.of(result)
    assert attribution.get("A").pnl == pytest.approx(0.0)
    assert attribution.unexplained == pytest.approx(0.0, abs=1e-9)


def test_what_execution_took_is_charged_to_the_instrument_it_was_taken_on() -> None:
    """A commission is paid on one order, in one name, and belongs to it."""
    result = run_of(
        [
            (1_000.0, {}, {}, []),
            (995.0, {"A": 10.0}, {"A": 100.0}, [buy("A", 10.0, 100.0, commission=5.0)]),
        ]
    )

    entry = InstrumentAttribution.of(result).get("A")
    assert entry.pnl == pytest.approx(-5.0)
    assert entry.commission == pytest.approx(5.0)
    assert entry.cost == pytest.approx(5.0)


def test_the_gross_figure_hands_execution_back() -> None:
    """Net says what the holder got; gross says whether the idea was worth trading."""
    spread = Fill(
        instrument_id="A",
        side=Side.BUY,
        quantity=10.0,
        reference_price=100.0,
        fill_price=101.0,
        commission=5.0,
    )
    result = run_of([(1_000.0, {}, {}, []), (985.0, {"A": 10.0}, {"A": 100.0}, [spread])])

    entry = InstrumentAttribution.of(result).get("A")
    assert entry.market_cost == pytest.approx(10.0)
    assert entry.pnl == pytest.approx(-15.0)
    assert entry.gross_pnl == pytest.approx(0.0)


def test_two_instruments_are_told_apart_and_still_add_up() -> None:
    """The question a total cannot answer: which of the two made the money."""
    result = run_of(
        [
            (2_000.0, {}, {}, []),
            (
                2_000.0,
                {"A": 10.0, "B": 10.0},
                {"A": 100.0, "B": 100.0},
                [buy("A", 10.0, 100.0), buy("B", 10.0, 100.0)],
            ),
            (2_300.0, {"A": 10.0, "B": 10.0}, {"A": 150.0, "B": 80.0}, []),
        ]
    )

    attribution = InstrumentAttribution.of(result)

    assert attribution.get("A").pnl == pytest.approx(500.0)
    assert attribution.get("B").pnl == pytest.approx(-200.0)
    assert attribution.total_pnl == pytest.approx(300.0)
    assert attribution.unexplained == pytest.approx(0.0, abs=1e-9)


def test_the_best_contributor_comes_first() -> None:
    """A report is read from the top, and the top is the name that carried the run."""
    result = run_of(
        [
            (2_000.0, {"A": 10.0, "B": 10.0}, {"A": 100.0, "B": 100.0}, []),
            (2_300.0, {"A": 10.0, "B": 10.0}, {"A": 150.0, "B": 80.0}, []),
        ]
    )

    ordered = [entry.instrument_id for entry in InstrumentAttribution.of(result).instruments]

    assert ordered == ["A", "B"]


def test_a_name_the_run_never_touched_is_not_a_zero() -> None:
    """A name that earned nothing and a name nobody held are different facts."""
    attribution = InstrumentAttribution.of(one_fund_bought_and_held())

    with pytest.raises(KeyError, match="never held or traded"):
        attribution.get("B")


def test_a_run_that_held_nothing_explains_nothing_and_says_so() -> None:
    """No instruments, no residual: an empty decomposition is still exact."""
    result = run_of([(1_000.0, {}, {}, []), (1_000.0, {}, {}, [])])

    attribution = InstrumentAttribution.of(result)

    assert attribution.instruments == ()
    assert attribution.unexplained == pytest.approx(0.0)


def test_an_empty_run_is_not_an_error() -> None:
    """A range with no session is a run that did nothing, not a broken one."""
    attribution = InstrumentAttribution.of(BacktestResult(records=(), initial_cash=1_000.0))

    assert attribution.instruments == ()
    assert attribution.total_pnl == 0.0


def test_the_frame_is_one_row_per_instrument() -> None:
    """What a notebook reads, with the same numbers the report prints."""
    frame = InstrumentAttribution.of(one_fund_bought_and_held()).as_frame()

    assert list(frame.index) == ["A"]
    assert frame.loc["A", "pnl"] == pytest.approx(100.0)
    assert frame.index.name == "instrument_id"
