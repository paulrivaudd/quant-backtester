"""A record that cannot contradict itself, and a result whose views all come from it.

The records are the source of truth; every frame is a view built on demand.
The first half checks that a record refuses to describe a session that could
not have happened, the second that each view says what the records say - one
real run over the synthetic market, small enough to read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from quant_backtester.backtest.config import BacktestConfig
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.engine import BacktestEngine
from quant_backtester.backtest.records import BacktestRecord
from quant_backtester.backtest.result import BacktestResult
from quant_backtester.backtest.schedule import DecisionSchedule, EveryNSessions, EverySession
from quant_backtester.backtest.timetable import BacktestTimetable
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.fills import ExecutionReject, ExecutionRejectReason, Fill
from quant_backtester.execution.model import ExecutionModel
from quant_backtester.execution.orders import Order, Side
from quant_backtester.portfolio.allocation import ConstrainedTarget, PortfolioDecision
from quant_backtester.portfolio.holdings import Holding
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.provenance import SourceState
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.base import Strategy

DAY = date(2026, 9, 10)
OPEN = datetime(2026, 9, 10, 7, 1, tzinfo=UTC)
CLOSE = datetime(2026, 9, 10, 21, 0, tzinfo=UTC)


def a_fill(**overrides: object) -> Fill:
    """Return a purchase of ten units at 100, filled at 100.3 with every cost apart."""
    fields: dict[str, object] = {
        "instrument_id": "A",
        "side": Side.BUY,
        "quantity": 10.0,
        "market_price": 100.0,
        "fill_price": 100.3,
        "commission": 1.0,
        "spread_cost": 2.0,
        "slippage_cost": 1.0,
        "executed_at": OPEN,
    }
    fields.update(overrides)
    return Fill(**fields)  # type: ignore[arg-type]


def a_decision(weights: Mapping[str, float] | None = None) -> PortfolioDecision:
    """Return a decision taken at the close, accepted as asked."""
    wanted = dict(weights or {"A": 1.0})
    return PortfolioDecision(
        requested=TargetAllocation(
            as_of=CLOSE,
            weights=wanted,
            considered=3,
            skipped={"C": SignalStatus.MISSING_INPUT},
        ),
        constrained=ConstrainedTarget(
            as_of=CLOSE, requested_weights=wanted, accepted_weights=wanted
        ),
    )


def a_record(**overrides: object) -> BacktestRecord:
    """Return a session that bought ten units at the open and holds them at 110."""
    fields: dict[str, object] = {
        "session_date": DAY,
        "valuation_time": CLOSE,
        "cash": 500.0,
        "gross_cash": 504.0,
        "holdings": {"A": Holding("A", 10.0, average_cost=100.4)},
        "valuation_prices": {"A": 110.0},
        "target_invested": 1.0,
        "execution_time": OPEN,
        "executed_decision": DAY - timedelta(days=1),
        "orders": (Order("A", Side.BUY, 10.0, OPEN),),
        "fills": (a_fill(),),
        "rejects": (ExecutionReject("B", ExecutionRejectReason.NO_EXECUTION_PRICE, Side.BUY),),
        "decision_time": CLOSE,
        "decision": a_decision(),
    }
    fields.update(overrides)
    return BacktestRecord(**fields)  # type: ignore[arg-type]


# -- a record -----------------------------------------------------------------------------


def test_the_equity_is_derived_from_the_cash_and_the_positions() -> None:
    """Stored as its parts, so the total cannot disagree with them."""
    record = a_record()

    assert record.positions_value == pytest.approx(1_100.0)
    assert record.net_equity == pytest.approx(1_600.0)
    assert record.gross_equity == pytest.approx(1_604.0)


def test_the_weights_actually_held_are_the_positions_over_the_equity() -> None:
    """Eleven hundred of sixteen hundred, whatever the target said."""
    record = a_record()

    assert record.actual_weights == {"A": pytest.approx(1_100.0 / 1_600.0)}
    assert record.actual_invested == pytest.approx(1_100.0 / 1_600.0)
    assert record.target_invested == 1.0


def test_the_costs_of_a_session_are_the_sums_of_its_fills() -> None:
    """Commission, spread and slippage, each kept, and their total."""
    record = a_record(fills=(a_fill(), a_fill(commission=2.0, executed_at=OPEN)))

    assert record.commission_cost == pytest.approx(3.0)
    assert record.spread_cost == pytest.approx(4.0)
    assert record.slippage_cost == pytest.approx(2.0)
    assert record.market_cost == pytest.approx(6.0)
    assert record.total_cost == pytest.approx(9.0)
    assert record.traded_value == pytest.approx(2 * 10.0 * 100.3)


def test_the_decision_of_the_session_says_what_was_asked_and_among_what() -> None:
    """The strategy's own diagnostics travel with the record."""
    record = a_record()

    assert record.decided
    assert record.decision_date == DAY
    assert record.considered == 3
    assert record.requested_target is not None
    assert record.constrained_target is not None
    assert record.strategy_diagnostics == {
        "considered": 3,
        "selected": ("A",),
        "skipped": {"C": "MISSING_INPUT"},
    }


def test_a_session_nobody_decided_on_has_no_diagnostics() -> None:
    """Not a decision to hold cash: no decision at all."""
    record = a_record(decision=None, decision_time=None)

    assert not record.decided
    assert record.decision_date is None
    assert record.considered is None
    assert record.strategy_diagnostics is None


def test_a_book_worth_nothing_has_no_weights() -> None:
    """And no division by a zero equity."""
    record = a_record(cash=0.0, gross_cash=0.0, holdings={}, valuation_prices={})

    assert record.actual_weights == {}
    assert record.actual_invested == 0.0


def test_a_record_cannot_be_edited_afterwards() -> None:
    """A result is what the run produced."""
    record = a_record()

    with pytest.raises(TypeError):
        record.holdings["B"] = Holding("B", 1.0)  # type: ignore[index]
    with pytest.raises(TypeError):
        record.valuation_prices["A"] = 1.0  # type: ignore[index]
    with pytest.raises(AttributeError):
        record.cash = 0.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"valuation_time": datetime(2026, 9, 10, 23, 0)}, "timezone-aware"),
        ({"cash": -0.01}, "cash"),
        ({"target_invested": 1.5}, "target_invested"),
        ({"valuation_prices": {}}, "was not valued"),
        ({"valuation_prices": {"A": 0.0}}, "valuation price of A"),
        ({"estimated_valuation_instruments": ("B",)}, "not held"),
        ({"holdings": {"A": Holding("B", 1.0)}, "valuation_prices": {"A": 1.0}}, "filed under"),
        ({"executed_decision": None}, "both its instant"),
        (
            {"execution_time": None, "executed_decision": None, "fills": (), "rejects": ()},
            "belong to an execution",
        ),
        ({"fills": (a_fill(executed_at=OPEN + timedelta(hours=1)),)}, "is recorded with"),
        ({"decision": None}, "both its instant and what was decided"),
        ({"decision_time": CLOSE + timedelta(hours=1)}, "is recorded at"),
    ],
    ids=[
        "naive",
        "negative-cash",
        "leverage",
        "unvalued",
        "zero-price",
        "estimate-not-held",
        "misfiled",
        "half-execution",
        "orphan-orders",
        "fill-elsewhere",
        "half-decision",
        "decision-elsewhere",
    ],
)
def test_a_record_of_a_session_that_could_not_have_happened_is_refused(
    overrides: dict[str, object], match: str
) -> None:
    """Every inconsistency is refused where the record is written, not found in a report."""
    with pytest.raises(ValueError, match=match):
        a_record(**overrides)


# -- a result -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HalfAndHalf(Strategy):
    """Half the book in each of two funds, one of which never prints an open."""

    weights: Mapping[str, float]
    strategy_id: str = "half_and_half"

    def decide(self, ctx: StrategyContext) -> TargetAllocation:
        """Return the fixed target."""
        return TargetAllocation(as_of=ctx.as_of, weights=dict(self.weights))


def a_run(
    market: MarketDataReader,
    calendars: CalendarRegistry,
    *,
    schedule: DecisionSchedule | None = None,
    costs: CostModel | None = None,
) -> BacktestResult:
    """Run half in each fund over the last four synthetic sessions."""
    return BacktestEngine(
        reader=market,
        calendars=calendars,
        strategy=HalfAndHalf({"ETF_EU": 0.5, "ETF_OTHER": 0.5}),
        universe=("ETF_EU", "ETF_OTHER"),
        config=BacktestConfig(
            start=date(2026, 9, 9),
            end=date(2026, 9, 14),
            initial_cash=10_000.0,
            base_currency="EUR",
            reference_calendar="XPAR",
            schedule=schedule or EverySession(),
            timetable=BacktestTimetable(),
        ),
        execution=ExecutionModel(costs=costs or CostModel()),
    ).run()


def test_the_frame_is_one_row_per_session_with_the_three_instants(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """What a notebook reads first."""
    frame = a_run(market, calendars).frame()

    assert list(frame.index) == list(sessions[-4:])
    assert frame.index.name == "session_date"
    for column in (
        "execution_time",
        "valuation_time",
        "decision_time",
        "net_equity",
        "gross_equity",
        "target_invested",
        "actual_invested",
        "orders",
        "fills",
        "rejects",
        "commission_cost",
        "spread_cost",
        "slippage_cost",
        "total_cost",
    ):
        assert column in frame.columns


def test_the_holdings_can_be_rebuilt_at_every_session(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Quantity of each fund and the cash, every session - zero where nothing is held."""
    result = a_run(market, calendars)

    holdings = result.holdings()

    assert list(holdings.columns) == ["ETF_EU", "ETF_OTHER", "cash"]
    assert holdings.loc[sessions[-4], "ETF_EU"] == 0.0
    assert holdings.loc[sessions[-3], "ETF_EU"] == pytest.approx(5_000.0 / 107.0)
    assert holdings.loc[sessions[-4], "cash"] == 10_000.0


def test_the_weights_actually_held_are_a_frame_of_their_own(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """Target and actual are different concepts, and have different frames."""
    result = a_run(market, calendars)

    actual = result.weights()
    target = result.target_weights()

    assert actual.loc[sessions[-4]].sum() == 0.0
    assert target.loc[sessions[-4]].to_dict() == {"ETF_EU": 0.5, "ETF_OTHER": 0.5}
    assert actual.loc[sessions[-3]].sum() == pytest.approx(1.0)


def test_a_target_stands_on_the_sessions_nobody_decided_on(
    market: MarketDataReader, calendars: CalendarRegistry, sessions: tuple[date, ...]
) -> None:
    """The row of a session the schedule skipped repeats the last decision."""
    result = a_run(market, calendars, schedule=EveryNSessions(3))

    target = result.target_weights()

    assert target.loc[sessions[-3]].to_dict() == {"ETF_EU": 0.5, "ETF_OTHER": 0.5}
    assert not result.records[1].decided


def test_every_fill_is_kept_with_both_prices_and_every_cost(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Fills do not disappear after execution."""
    costly = CostModel(commission_rate=0.001, half_spread_rate=0.002, slippage_rate=0.001)
    result = a_run(market, calendars, costs=costly)

    fills = result.fills()

    assert list(fills["instrument_id"][:2]) == ["ETF_EU", "ETF_OTHER"]
    assert (fills["fill_price"] > fills["market_price"])[fills["side"] == "BUY"].all()
    assert fills["total_cost"].sum() == pytest.approx(result.total_cost)
    assert fills["total_cost"].sum() == pytest.approx(
        (fills["commission"] + fills["spread_cost"] + fills["slippage_cost"]).sum()
    )


def test_every_order_says_what_became_of_it(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Filled, filled in part, or refused - with the decision it carried out."""
    costly = CostModel(commission_rate=0.001)
    result = a_run(market, calendars, costs=costly)

    orders = result.orders()

    first = orders[orders["session_date"] == date(2026, 9, 10)]
    assert set(first["status"]) == {"PARTIALLY_FILLED"}
    assert set(first["decided_on"]) == {date(2026, 9, 9)}
    assert (orders["filled_quantity"] <= orders["quantity"]).all()


def test_every_reject_is_kept_with_its_reason(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """The cut a commission forces on a whole book is on the record, one line per fund."""
    result = a_run(market, calendars, costs=CostModel(commission_rate=0.001))

    rejects = result.rejects()

    assert set(rejects["reason"]) == {"INSUFFICIENT_CASH"}
    assert set(rejects["instrument_id"]) == {"ETF_EU", "ETF_OTHER"}
    assert list(rejects.columns) == [
        "session_date",
        "instrument_id",
        "reason",
        "side",
        "requested_quantity",
    ]


def test_the_costs_and_the_equity_are_views_of_the_same_records(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """Gross and net side by side; the bill term by term."""
    costly = CostModel(commission_rate=0.001, half_spread_rate=0.002)
    result = a_run(market, calendars, costs=costly)

    equity = result.equity()
    costs = result.costs()

    assert list(equity.columns) == ["net_equity", "gross_equity"]
    assert (equity["gross_equity"] >= equity["net_equity"]).all()
    assert costs["total_cost"].sum() == pytest.approx(result.total_cost)
    assert result.net_return < result.gross_return


def test_a_run_with_no_fill_has_empty_frames_with_their_columns(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """An empty frame still says what it would have held."""
    result = a_run(market, calendars)
    nothing = BacktestResult(
        records=result.records[:1],
        config=result.config,
        configuration={},
        strategy_definition={"strategy_id": "x"},
        strategy_fingerprint="x",
    )

    assert nothing.fills().empty
    assert "fill_price" in nothing.fills().columns
    assert nothing.orders().empty
    assert nothing.rejects().empty


def test_a_result_is_frozen_all_the_way_down(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A record of an experiment that can be edited afterwards is a record of nothing."""
    result = a_run(market, calendars)

    with pytest.raises(TypeError):
        result.configuration["initial_cash"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        result.strategy_definition["strategy_id"] = "other"  # type: ignore[index]
    assert isinstance(result.records, tuple)


def test_a_result_says_what_it_started_with_and_what_code_made_it(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """The cash from the configuration, and a code version that is honestly unknown."""
    result = a_run(market, calendars)

    assert result.initial_cash == 10_000.0
    assert result.source == SourceState.unrecorded()
    assert result.code_version is None


def test_records_out_of_order_are_refused(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A run walks forwards."""
    result = a_run(market, calendars)

    with pytest.raises(ValueError, match="session order"):
        BacktestResult(
            records=tuple(reversed(result.records)),
            config=result.config,
            configuration={},
            strategy_definition={},
            strategy_fingerprint="x",
        )


def test_records_outside_the_configured_period_are_refused(
    market: MarketDataReader, calendars: CalendarRegistry
) -> None:
    """A record of a session the run was not configured to walk belongs to another run."""
    result = a_run(market, calendars)
    narrower = BacktestConfig(
        start=date(2026, 9, 10),
        end=date(2026, 9, 14),
        initial_cash=10_000.0,
        base_currency="EUR",
        reference_calendar="XPAR",
        schedule=EverySession(),
        timetable=BacktestTimetable(),
    )

    with pytest.raises(ValueError, match="outside the configured"):
        BacktestResult(
            records=result.records,
            config=narrower,
            configuration={},
            strategy_definition={},
            strategy_fingerprint="x",
        )


def test_a_result_needs_the_fingerprint_of_what_produced_it() -> None:
    """A result nobody can trace to a strategy is not a result."""
    with pytest.raises(ValueError, match="strategy_fingerprint"):
        BacktestResult(
            records=(),
            config=BacktestConfig(
                start=date(2026, 9, 10),
                end=date(2026, 9, 14),
                initial_cash=1.0,
                base_currency="EUR",
                reference_calendar="XPAR",
                schedule=EverySession(),
                timetable=BacktestTimetable(),
            ),
            configuration={},
            strategy_definition={},
            strategy_fingerprint="",
        )
