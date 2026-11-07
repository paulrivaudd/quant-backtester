"""SA17: the sectors with the strongest market-adjusted momentum, scaled to a risk target.

The market of these tests is drawn from a fixed seed: five Paris sector funds,
separate USD LEVEL NAV on XNYS dates, synchronized synthetic FX,
a New York market index and a flat monetary fund,
from January to December 2026 on the synthetic calendars of ``conftest``. The
rule is tested on written scores where the ranking is the question, on the
real monthly signal where the reading of the market is, and through the
engine where the question is whether it runs as a backtest.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Callable, Mapping
from datetime import date, datetime, time

import numpy as np
import pandas as pd
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StrategyResult, StrategyRunner
from quant_backtester.backtest.schedule import Monthly
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    Instrument,
    InstrumentRegistry,
    PublicationRule,
)
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.schemas import BarField
from quant_backtester.execution.costs import CostModel
from quant_backtester.execution.model import ExecutionModel, Sizing
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_asset.residual_momentum import simple_returns
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.signals.windows import load_month_end_window
from quant_backtester.strategies.SA17_sector_residual_momentum import (
    SA17SectorResidualMomentum,
    SectorPlan,
    SectorRanking,
    equal_weight_volatility,
)

SECTORS = ("S_A", "S_B", "S_C", "S_D", "S_E")
MARKET, MONETARY, ELSEWHERE = "MKT", "MM", "S_US"
UNIVERSE = (*SECTORS, MONETARY)
FIRST, LAST = date(2026, 1, 5), date(2026, 12, 31)
SEED = 20261101
VOLATILITY = {"S_A": 0.30, "S_B": 0.25, "S_C": 0.40, "S_D": 0.20, "S_E": 0.35}
VOLATILITY |= {MARKET: 0.18, ELSEWHERE: 0.30, MONETARY: 0.0}
Written = dict[tuple[str, str], float | SignalStatus]


def fund(name: str, calendar_id: str, *, tradable: bool = True) -> Instrument:
    """Return one synthetic instrument listed from the first session of the year."""
    return Instrument(
        id=name,
        name=f"Synthetic {name}",
        asset_type=AssetType.ETF if tradable else AssetType.INDEX,
        data_type=DataType.BAR,
        currency="EUR" if tradable else "USD",
        primary_source="YAHOO",
        source_symbol=name,
        tradable=tradable,
        calendar_id=calendar_id,
        first_session=FIRST,
    )


@pytest.fixture
def instruments() -> InstrumentRegistry:
    """Return the five sectors, a sector on another venue, the market and the monetary fund."""
    return InstrumentRegistry(
        [
            *(fund(name, "XPAR") for name in SECTORS),
            fund(ELSEWHERE, "XNYS"),
            fund(MONETARY, "XPAR"),
            fund(MARKET, "XNYS", tradable=False),
            *(
                Instrument(
                    id=f"{name}_NAV",
                    name=f"Synthetic USD NAV {name}",
                    asset_type=AssetType.ETF,
                    data_type=DataType.LEVEL,
                    currency="USD",
                    primary_source="FRED",
                    source_symbol=name,
                    tradable=False,
                    first_session=FIRST,
                    publication_rule=PublicationRule(time(23, 45), "Europe/Dublin"),
                )
                for name in (*SECTORS, ELSEWHERE)
            ),
            Instrument(
                id="FX",
                name="Synthetic synchronized USD per EUR",
                asset_type=AssetType.FX,
                data_type=DataType.LEVEL,
                currency="USD",
                primary_source="FRED",
                source_symbol="FX",
                tradable=False,
                first_session=FIRST,
                publication_rule=PublicationRule(time(23, 45), "Europe/Dublin"),
            ),
        ]
    )


def drawn(name: str, calendar: TradingCalendar) -> dict[date, float]:
    """Return a fund's closes, drawn from its own seeded stream."""
    rng = np.random.default_rng([SEED, sorted(VOLATILITY).index(name)])
    daily = VOLATILITY[name] / math.sqrt(252.0)
    price, closes = 100.0, {}
    for session in calendar.sessions(FIRST, LAST):
        price *= math.exp(float(rng.normal(0.0, daily)))
        closes[session.session_date] = round(price, 6)
    return closes


@pytest.fixture
def holes() -> Mapping[str, tuple[date, ...]]:
    """Return the closes the provider did not serve, by fund; parametrised by a test."""
    return {}


@pytest.fixture
def build_market(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    xpar: TradingCalendar,
    xnys: TradingCalendar,
) -> Callable[..., MarketDataReader]:
    """Return a builder of the drawn market, with holes and absurd future prices if asked."""

    def build(
        holes: Mapping[str, tuple[date, ...]] | None = None, *, future_after: date | None = None
    ) -> MarketDataReader:
        bars = {}
        for name in VOLATILITY:
            calendar = xnys if name in (MARKET, ELSEWHERE) else xpar
            closes = drawn(name, calendar)
            if future_after is not None:
                closes = {d: p if d <= future_after else 1e6 for d, p in closes.items()}
            missing = (holes or {}).get(name, ())
            bars[name] = make_bars(
                name, calendar, closes, contested={day: [BarField.CLOSE] for day in missing}
            )
        levels = {}
        for name in (*SECTORS, ELSEWHERE):
            values = drawn(name, xnys)
            missing = (holes or {}).get(name, ())
            values = {d: p for d, p in values.items() if d not in missing}
            if future_after is not None:
                values = {d: p if d <= future_after else 1e6 for d, p in values.items()}
            levels[f"{name}_NAV"] = make_levels(f"{name}_NAV", values)
        levels["FX"] = make_levels("FX", {s.session_date: 1.2 for s in xnys.sessions(FIRST, LAST)})
        return make_market(bars, levels=levels)

    return build


@pytest.fixture
def market(build_market, holes) -> MarketDataReader:
    """Return the drawn market the decision fixtures of ``conftest`` read."""
    return build_market(holes)


def candidate(**changes: object) -> SA17SectorResidualMomentum:
    """Return the candidate on the test funds, other parameters as declared."""
    sectors = changes.get("sector_ids", SECTORS)
    assert isinstance(sectors, tuple)
    parameters: dict[str, object] = {
        "sector_ids": SECTORS,
        "market_id": MARKET,
        "monetary_id": MONETARY,
        "signal_input_ids": tuple(f"{name}_NAV" for name in sectors),
        "risk_input_ids": tuple(f"{name}_NAV" for name in sectors),
        "usd_per_eur_fx_id": "FX",
    }
    return SA17SectorResidualMomentum(**(parameters | changes))  # type: ignore[arg-type]


def scores(strategy: SA17SectorResidualMomentum, **values: float | SignalStatus) -> Written:
    """Write each sector's score, by sector name."""
    signal_id = strategy.momentum().signal_id
    return {
        (signal_id, source): values[name]
        for name, source in zip(strategy.sector_ids, strategy.signal_input_ids, strict=True)
    }


@pytest.fixture
def decision(written_decision, context) -> Callable[..., StrategyContext]:
    """Return the decision of 14 September on written scores and a held book."""

    def build(
        strategy: SA17SectorResidualMomentum,
        written: Written,
        held: Mapping[str, float] | None = None,
        universe: tuple[str, ...] = UNIVERSE,
    ) -> StrategyContext:
        result = written_decision(
            dataclasses.replace(strategy, target_volatility=None),
            written,
            universe=universe,
            held=held,
        )
        if strategy.target_volatility is not None:
            risk = strategy.risk_signal().compute(context, strategy.risk_input_ids)
            result = dataclasses.replace(
                result,
                signals=SignalSnapshot(
                    context.as_of, dict(result.signals.results) | {risk.signal_id: risk}
                ),
            )
        return result

    return build


def expected_volatility(names: tuple[str, ...], decided: date, xpar: TradingCalendar) -> float:
    """Return the equal-weight basket's volatility, with numpy, on 63 returns to ``decided``."""
    sessions = [s.session_date for s in xpar.sessions(FIRST, decided)][-64:]
    returns = []
    for name in names:
        closes = drawn(name, xpar)
        prices = np.array([closes[day] for day in sessions])
        returns.append(prices[1:] / prices[:-1] - 1.0)
    weights = np.full(len(names), 1.0 / len(names))
    return math.sqrt(252.0 * float(weights @ np.cov(np.array(returns), ddof=1) @ weights))


# -- choosing the sectors -----------------------------------------------------------------


def test_the_three_best_scores_are_held_in_equal_parts_ties_to_the_smaller_name(decision) -> None:
    strategy = candidate(target_volatility=None)
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=0.5)
    plan = strategy.plan(decision(strategy, written))
    assert plan.selected == ("S_C", "S_A", "S_B")
    assert dict(plan.weights) == pytest.approx(dict.fromkeys(("S_A", "S_B", "S_C"), 1.0 / 3.0))
    target = strategy.decide(decision(strategy, written))
    assert dict(target.weights) == pytest.approx(dict(plan.weights))
    assert target.considered == 5
    assert target.skipped == {"S_D": SignalStatus.OK, "S_E": SignalStatus.OK}


def test_the_selection_stands_when_every_score_is_negative(decision) -> None:
    strategy = candidate(target_volatility=None)
    written = scores(strategy, S_A=-0.1, S_B=-0.4, S_C=-2.0, S_D=-0.2, S_E=-0.3)
    plan = strategy.plan(decision(strategy, written))
    assert plan.selected == ("S_A", "S_D", "S_E")


def test_a_sector_not_yet_eligible_is_left_out(decision) -> None:
    strategy = candidate(target_volatility=None)
    written = scores(
        strategy,
        S_A=1.0,
        S_B=SignalStatus.INSUFFICIENT_HISTORY,
        S_C=2.0,
        S_D=SignalStatus.NOT_LISTED,
        S_E=0.0,
    )
    plan = strategy.plan(decision(strategy, written))
    assert plan.complete
    assert plan.eligible == ("S_A", "S_C", "S_E")
    assert plan.selected == ("S_C", "S_A", "S_E")
    assert dict(plan.ineligible) == {
        "S_B": SignalStatus.INSUFFICIENT_HISTORY,
        "S_D": SignalStatus.NOT_LISTED,
    }


def test_a_sector_outside_the_universe_cannot_be_held(decision) -> None:
    strategy = candidate(target_volatility=None)
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=0.5)
    universe = tuple(name for name in UNIVERSE if name != "S_C")
    plan = strategy.plan(decision(strategy, written, universe=universe))
    assert plan.selected == ("S_A", "S_B", "S_E")
    assert plan.ineligible == {"S_C": SignalStatus.NOT_LISTED}


@pytest.mark.parametrize("monetary", [MONETARY, None])
def test_fewer_eligible_sectors_than_places_leave_the_book_out_of_the_sectors(
    decision, monetary
) -> None:
    strategy = candidate(monetary_id=monetary)
    gone = SignalStatus.INSUFFICIENT_HISTORY
    written = scores(strategy, S_A=1.0, S_B=gone, S_C=2.0, S_D=gone, S_E=gone)
    target = strategy.decide(decision(strategy, written))
    assert dict(target.weights) == ({MONETARY: 1.0} if monetary else {})
    assert target.skipped["S_A"] is SignalStatus.INSUFFICIENT_CROSS_SECTION
    assert target.skipped["S_B"] is gone


@pytest.mark.parametrize(
    "failure",
    [
        SignalStatus.MISSING_INPUT,
        SignalStatus.STALE_INPUT,
        SignalStatus.INVALID_INPUT,
        SignalStatus.NON_CONSECUTIVE_HISTORY,
    ],
)
def test_a_failure_on_any_eligible_sector_keeps_the_book(decision, failure) -> None:
    strategy = candidate()
    # S_E would not even be selected: the universe is not reduced silently.
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=failure)
    held = {"S_A": 0.3, "S_D": 0.3, MONETARY: 0.4}
    plan = strategy.plan(decision(strategy, written, held))
    assert not plan.complete
    assert dict(plan.weights) == {}
    assert plan.unusable == {"S_E": failure}
    target = strategy.decide(decision(strategy, written, held))
    assert target.hold_positions
    assert dict(target.weights) == pytest.approx(held)


def test_the_equal_sectors_control_holds_every_eligible_sector(decision) -> None:
    strategy = candidate().controls()["equal_sectors"]
    signal_id = strategy.momentum().signal_id
    assert signal_id.startswith("sa17_total_")
    written: Written = {(signal_id, name): -5.0 for name in strategy.signal_input_ids}
    written[signal_id, "S_D_NAV"] = SignalStatus.INSUFFICIENT_HISTORY
    plan = strategy.plan(decision(strategy, written))
    assert plan.selected == ("S_A", "S_B", "S_C", "S_E")
    assert dict(plan.weights) == pytest.approx(dict.fromkeys(plan.selected, 0.25))


# -- the volatility target ----------------------------------------------------------------


def test_the_sleeve_is_scaled_to_the_target_and_the_rest_is_monetary(decision, xnys) -> None:
    strategy = candidate(target_volatility=0.15)
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=0.0)
    plan = strategy.plan(decision(strategy, written))
    volatility = expected_volatility(("S_A", "S_B", "S_C"), date(2026, 8, 31), xnys)
    assert plan.volatility == pytest.approx(volatility, rel=1e-9)
    assert volatility > 0.15  # the drawn sectors are more volatile than the target
    exposure = 0.15 / volatility
    assert plan.exposure == pytest.approx(exposure)
    expected = dict.fromkeys(("S_A", "S_B", "S_C"), exposure / 3.0) | {MONETARY: 1.0 - exposure}
    assert dict(plan.weights) == pytest.approx(expected)
    assert math.fsum(plan.weights.values()) == pytest.approx(1.0)
    target = strategy.decide(decision(strategy, written))
    assert target.considered == 6  # five sectors and the monetary fund
    assert set(target.weights) == {"S_A", "S_B", "S_C", MONETARY}


def test_a_target_above_the_basket_volatility_holds_the_whole_book(decision) -> None:
    strategy = candidate(target_volatility=2.0)
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=0.0)
    plan = strategy.plan(decision(strategy, written))
    assert plan.exposure == 1.0
    assert MONETARY not in plan.weights


def test_without_a_monetary_fund_the_rest_stays_in_cash(decision) -> None:
    strategy = candidate(monetary_id=None)
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=0.0)
    plan = strategy.plan(decision(strategy, written))
    assert plan.exposure < 1.0
    assert set(plan.weights) == {"S_A", "S_B", "S_C"}
    assert math.fsum(plan.weights.values()) == pytest.approx(plan.exposure)


@pytest.mark.parametrize("holes", [{"S_B": (date(2026, 8, 28),)}])
def test_a_hole_in_a_selected_fund_s_risk_window_keeps_the_book(decision, holes) -> None:
    strategy = candidate()
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=0.0)
    held = {"S_D": 0.5, MONETARY: 0.5}
    plan = strategy.plan(decision(strategy, written, held))
    assert plan.selected == ("S_C", "S_A", "S_B")
    assert plan.unusable == {"S_B": SignalStatus.MISSING_INPUT}
    assert strategy.decide(decision(strategy, written, held)).hold_positions


@pytest.mark.parametrize("holes", [{"S_E": (date(2026, 8, 28),)}])
def test_a_hole_in_a_fund_not_selected_changes_nothing(decision, holes) -> None:
    strategy = candidate()
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=0.0)
    assert strategy.plan(decision(strategy, written)).complete


@pytest.mark.parametrize("holes", [{ELSEWHERE: (date(2026, 8, 28),)}])
def test_funds_that_do_not_hold_the_same_sessions_cannot_be_paired(decision) -> None:
    sectors = ("S_A", "S_B", ELSEWHERE, "S_D")
    strategy = candidate(sector_ids=sectors)
    signal_id = strategy.momentum().signal_id
    # The New York fund ranks first, so its window is the first one read.
    written = {
        (signal_id, name): value
        for name, value in zip(strategy.signal_input_ids, (2, 1, 3, 0), strict=True)
    }
    plan = strategy.plan(decision(strategy, written, universe=(*sectors, MONETARY)))
    assert plan.selected == (ELSEWHERE, "S_A", "S_B")
    # The missing NAV observation is not replaced by an earlier session.
    assert plan.unusable == {ELSEWHERE: SignalStatus.MISSING_INPUT}


def test_a_cancelled_decision_exits_only_a_line_the_universe_no_longer_holds(decision) -> None:
    strategy = candidate()
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=SignalStatus.MISSING_INPUT)
    held = {"S_A": 0.3, "S_D": 0.3, MONETARY: 0.4}
    universe = tuple(name for name in UNIVERSE if name != "S_D")
    target = strategy.decide(decision(strategy, written, held, universe=universe))
    assert not target.hold_positions
    assert target.kept == {"S_A", MONETARY}
    assert dict(target.weights) == pytest.approx({"S_A": 0.3, MONETARY: 0.4})


def test_without_a_target_the_risk_is_not_read(decision) -> None:
    strategy = candidate().controls()["no_volatility_target"]
    written = scores(strategy, S_A=1.0, S_B=0.5, S_C=2.0, S_D=-1.0, S_E=0.0)
    plan = strategy.plan(decision(strategy, written))
    assert plan.volatility is None
    assert plan.exposure == 1.0


def test_equal_weight_volatility_matches_numpy_and_the_basket_s_own_variance(rng_seed) -> None:
    rng = np.random.default_rng(rng_seed)
    returns = rng.normal(0.0, 0.01, (4, 63)) + rng.normal(0.0, 0.01, 63)
    weights = np.full(4, 0.25)
    covariance = weights @ np.cov(returns, ddof=1) @ weights
    computed = equal_weight_volatility([list(row) for row in returns], 252)
    assert computed == pytest.approx(math.sqrt(252.0 * covariance), rel=1e-12)
    basket = returns.mean(axis=0)
    assert computed == pytest.approx(math.sqrt(252.0 * basket.var(ddof=1)), rel=1e-12)
    assert equal_weight_volatility([[0.01, 0.01, 0.01]], 252) == 0.0


@pytest.mark.parametrize("returns", [[], [[0.01, 0.02], [0.01]], [[0.01]]])
def test_equal_weight_volatility_refuses_what_is_not_a_basket(returns) -> None:
    with pytest.raises(ValueError):
        equal_weight_volatility(returns, 252)


def test_simple_returns_refuse_a_price_that_is_not_positive() -> None:
    assert simple_returns([100.0, 110.0, 99.0]) == pytest.approx([0.1, -0.1])
    assert simple_returns([100.0, 0.0]) is None
    assert simple_returns([100.0, float("nan")]) is None


# -- the real monthly signal ----------------------------------------------------------------


def real_plan(
    strategy: SA17SectorResidualMomentum,
    reader: MarketDataReader,
    decided: date,
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
    evening: Callable[[date], datetime],
) -> SectorPlan:
    """Return the plan of one evening, every signal computed by the engine."""
    context = make_context(reader, evening(decided))
    requests = [item for item in strategy.required_signals() if isinstance(item, SignalRequest)]
    snapshot = SignalEngine().compute(context, requests, list(UNIVERSE))
    return strategy.plan(make_decision(context, snapshot, universe=UNIVERSE))


@pytest.mark.parametrize("ranking", list(SectorRanking))
def test_real_signals_ignore_future_prices(
    build_market, make_context, make_decision, evening, ranking
) -> None:
    strategy = candidate(estimation_months=5, score_months=3, skip_months=1, risk_returns=20)
    if ranking is not SectorRanking.RESIDUAL:
        strategy = dataclasses.replace(strategy, ranking=ranking)  # the market is a gate
    decided = date(2026, 9, 30)
    before = real_plan(strategy, build_market(), decided, make_context, make_decision, evening)
    after = real_plan(
        strategy, build_market(future_after=decided), decided, make_context, make_decision, evening
    )
    assert before.complete
    assert before == after
    assert len(before.scores) == len(SECTORS)
    assert 0.0 < before.exposure <= 1.0


def test_real_residual_scores_are_read_against_the_declared_market(
    build_market, make_context, make_decision, evening
) -> None:
    strategy = candidate(estimation_months=5, score_months=3, skip_months=1, risk_returns=20)
    assert strategy.momentum().signal_id == "sa17_residual_vs_mkt_5m_3m_skip1"
    plan = real_plan(
        strategy, build_market(), date(2026, 9, 30), make_context, make_decision, evening
    )
    ranked = sorted(plan.scores, key=lambda name: (-plan.scores[name], name))
    assert plan.selected == tuple(ranked[:3])


# -- configuration ------------------------------------------------------------------------


def test_the_controls_remove_one_mechanism_each() -> None:
    base = candidate(top_n=2, estimation_months=24)
    controls = base.controls()
    assert set(controls) == {
        "total_momentum",
        "no_volatility_target",
        "equal_sectors",
        "equal_sectors_volatility_target",
    }
    assert controls["total_momentum"].ranking is SectorRanking.TOTAL
    assert controls["total_momentum"].target_volatility == base.target_volatility
    assert controls["no_volatility_target"].ranking is SectorRanking.RESIDUAL
    assert controls["no_volatility_target"].target_volatility is None
    assert controls["equal_sectors"].target_volatility is None
    assert controls["equal_sectors_volatility_target"].target_volatility == 0.15
    for control in controls.values():
        assert control.top_n == 2
        assert control.estimation_months == 24
        assert control.sector_ids == SECTORS
        assert control.monetary_id == MONETARY
        # The market gates every control, so a sector is eligible on the same dates.
        assert control.market_id == MARKET
        assert control.momentum().definition()["market_role"] in ("REGRESSOR", "GATE")
    ids = {control.strategy_id for control in controls.values()} | {base.strategy_id}
    assert len(ids) == 5
    with pytest.raises(ValueError, match="around a residual ranking"):
        controls["total_momentum"].controls()


def test_definition_is_serialisable_and_names_the_proposal_s_parameters() -> None:
    strategy = candidate()
    definition = strategy.definition()
    json.dumps(definition)
    parameters = definition["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["ranking"] == "RESIDUAL"
    assert (parameters["top_n"], parameters["estimation_months"]) == (3, 36)
    assert (parameters["score_months"], parameters["skip_months"]) == (11, 1)
    assert (parameters["risk_returns"], parameters["target_volatility"]) == (63, 0.15)
    assert strategy.fingerprint() != candidate(target_volatility=0.12).fingerprint()


def test_signal_inputs_score_one_series_and_hold_another(decision) -> None:
    inputs = tuple(f"{name}_INDEX" for name in SECTORS)
    strategy = candidate(signal_input_ids=inputs, target_volatility=None)
    requests = strategy.required_signals()
    assert isinstance(requests[0], SignalRequest)
    assert requests[0].names() == inputs


@pytest.mark.parametrize(
    "changes",
    [
        {"sector_ids": ()},
        {"sector_ids": ("S_A", "S_A", "S_B")},
        {"sector_ids": ("S_A", "S_B")},
        {"market_id": None},
        {"ranking": "RESIDUAL"},
        {"monetary_id": "S_A"},
        {"monetary_id": MARKET},
        {"market_id": "S_A"},
        {"signal_input_ids": ("X", "Y")},
        {"top_n": 0},
        {"risk_returns": 1},
        {"target_volatility": 0.0},
        {"target_volatility": float("inf")},
        {"score_months": 36},
        {"skip_months": -1},
        {"strategy_id": ""},
    ],
)
def test_invalid_configurations_are_refused(changes) -> None:
    with pytest.raises(ValueError):
        candidate(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"signal_input_ids": ()},
        {"risk_input_ids": ()},
        {"usd_per_eur_fx_id": None},
        {"risk_input_currency": "GBP"},
        {"signal_input_ids": SECTORS},
        {"risk_input_ids": SECTORS},
        {"ranking": SectorRanking.TOTAL, "market_id": None},
    ],
)
def test_explicit_nav_and_fx_contract_is_required(changes) -> None:
    with pytest.raises(ValueError):
        candidate(**changes)


def test_level_month_ends_use_explicit_cutoff_not_the_new_decision_month(
    market,
    make_context,
    evening,
) -> None:
    context = make_context(market, evening(date(2026, 10, 2)))
    window = load_month_end_window(
        context,
        "S_A_NAV",
        months=3,
        basis=PriceBasis.ADJUSTED,
        max_age_sessions=0,
        observation_calendar_id="XNYS",
        observation_cutoff=date(2026, 9, 30),
        nav=True,
    )
    assert window.status is SignalStatus.OK
    assert window.dates == (
        date(2026, 6, 30),
        date(2026, 7, 31),
        date(2026, 8, 31),
        date(2026, 9, 30),
    )


def test_same_day_nav_at_2300_is_missing_even_if_upstream_claims_early_publication(
    market,
    repository,
    make_levels,
    xnys,
    make_context,
    evening,
) -> None:
    frame = make_levels("S_A_NAV", drawn("S_A", xnys))
    # Deliberately false availability: the signal still enforces valuation's lower bound.
    frame["available_at_utc"] -= pd.Timedelta(hours=4)
    repository.save_levels("S_A_NAV", frame)
    context = make_context(market, evening(date(2026, 9, 30)))
    window = load_month_end_window(
        context,
        "S_A_NAV",
        months=3,
        basis=PriceBasis.RAW,
        max_age_sessions=1,
        observation_calendar_id="XNYS",
        observation_cutoff=date(2026, 9, 30),
        nav=True,
    )
    assert window.status is SignalStatus.MISSING_INPUT


@pytest.mark.parametrize(
    "name, changes",
    [
        ("S_A_NAV", {"currency": "EUR"}),
        (MARKET, {"currency": "EUR"}),
        (MARKET, {"calendar_id": "XPAR"}),
    ],
)
def test_sa17_rejects_currency_or_market_calendar_mismatch(context, name, changes) -> None:
    # A registry entry contradicting the signal is a configuration mistake: it
    # stops the run instead of leaving every decision in cash.
    changed = [
        dataclasses.replace(i, **changes) if i.id == name else i for i in context.instruments
    ]
    context = dataclasses.replace(context, instruments=InstrumentRegistry(changed))
    with pytest.raises(ValueError):
        candidate(**SHORT).momentum().compute(context, ["S_A_NAV"])


def test_a_tradable_or_bar_sector_input_is_refused_as_a_nav(context) -> None:
    changed = [
        dataclasses.replace(i, tradable=True) if i.id == "S_A_NAV" else i
        for i in context.instruments
    ]
    context = dataclasses.replace(context, instruments=InstrumentRegistry(changed))
    with pytest.raises(ValueError, match="not one"):
        candidate(**SHORT).momentum().compute(context, ["S_A_NAV"])


def test_a_cutoff_before_its_months_first_session_does_not_repeat_a_month_end(
    market,
    make_context,
    evening,
) -> None:
    # Sunday 1 November: the last session on or before it is Friday 30 October.
    # Anchored on the 1st itself, the window ended on 30 October twice - a flat
    # month nobody observed, one month short, and still OK.
    context = make_context(market, evening(date(2026, 11, 2)))
    window = load_month_end_window(
        context,
        "S_A_NAV",
        months=4,
        basis=PriceBasis.ADJUSTED,
        max_age_sessions=0,
        observation_calendar_id="XNYS",
        observation_cutoff=date(2026, 11, 1),
        nav=True,
    )
    assert window.status is SignalStatus.OK
    assert window.dates == (
        date(2026, 6, 30),
        date(2026, 7, 31),
        date(2026, 8, 31),
        date(2026, 9, 30),
        date(2026, 10, 30),
    )
    signal = dataclasses.replace(
        candidate(**SHORT).momentum(), observation_cutoff=date(2026, 11, 1)
    )
    computed = signal.compute(context, ["S_A_NAV"])
    assert computed.status("S_A_NAV") is SignalStatus.OK
    assert computed.frame.loc["S_A_NAV", "input_end_date"] == date(2026, 10, 30)


def test_sa17_holds_no_fixed_cutoff() -> None:
    # Each decision reads the month before its own; a date in the strategy's
    # configuration would be the same at every decision of a run.
    with pytest.raises(TypeError):
        candidate(observation_cutoff=date(2026, 9, 30))
    assert candidate(**SHORT).momentum().completed_months_only
    assert candidate(**SHORT).momentum().observation_cutoff is None
    assert candidate(**SHORT).risk_signal().observation_cutoff is None


@pytest.mark.parametrize(
    "cutoff, decided",
    [
        (date(2026, 8, 31), date(2026, 10, 30)),  # two months back: a frozen window
        (date(2026, 9, 15), date(2026, 9, 30)),  # the decision's own month: partial
        # The month before, but mid-month: August 31 -> September 15 would be
        # scored as September's completed return.
        (date(2026, 9, 15), date(2026, 10, 30)),
        (date(2026, 9, 29), date(2026, 10, 30)),  # one session short is still short
    ],
)
def test_a_completed_months_cutoff_must_end_the_month_before(
    market,
    make_context,
    evening,
    cutoff,
    decided,
) -> None:
    context = make_context(market, evening(decided))
    momentum = dataclasses.replace(candidate(**SHORT).momentum(), observation_cutoff=cutoff)
    risk = dataclasses.replace(candidate(**SHORT).risk_signal(), observation_cutoff=cutoff)
    with pytest.raises(ValueError, match="the month before the decision"):
        momentum.compute(context, ["S_A_NAV"])
    with pytest.raises(ValueError, match="the month before the decision"):
        risk.compute(context, ["S_A_NAV"])


def test_a_cutoff_in_the_month_before_is_read(market, make_context, evening) -> None:
    context = make_context(market, evening(date(2026, 10, 30)))
    momentum = dataclasses.replace(
        candidate(**SHORT).momentum(), observation_cutoff=date(2026, 9, 30)
    )
    result = momentum.compute(context, ["S_A_NAV"])
    assert result.status("S_A_NAV") is SignalStatus.OK
    assert result.frame.loc["S_A_NAV", "input_end_date"] == date(2026, 9, 30)


def test_a_cutoff_after_the_last_session_resolves_to_it(market, make_context, evening) -> None:
    # Saturday 31 October: the last session on or before it is Friday 30
    # October, October's last - the same window as the computed cutoff.
    context = make_context(market, evening(date(2026, 11, 2)))
    explicit = dataclasses.replace(
        candidate(**SHORT).momentum(), observation_cutoff=date(2026, 10, 31)
    )
    computed = candidate(**SHORT).momentum()
    result = explicit.compute(context, ["S_A_NAV"])
    assert result.status("S_A_NAV") is SignalStatus.OK
    assert result.frame.loc["S_A_NAV", "input_end_date"] == date(2026, 10, 30)
    assert result.frame.loc["S_A_NAV", "value"] == pytest.approx(
        computed.compute(context, ["S_A_NAV"]).frame.loc["S_A_NAV", "value"]
    )


def test_an_analysis_of_one_past_window_keeps_the_loaders_contract(
    market,
    make_context,
    evening,
) -> None:
    # Outside completed-months mode a fixed cutoff may be any day up to the
    # decision: a completed month can be read long after its end.
    context = make_context(market, evening(date(2026, 10, 30)))
    momentum = dataclasses.replace(
        candidate(**SHORT).momentum(),
        observation_cutoff=date(2026, 8, 31),
        completed_months_only=False,
    )
    result = momentum.compute(context, ["S_A_NAV"])
    assert result.status("S_A_NAV") is SignalStatus.OK
    assert result.frame.loc["S_A_NAV", "input_end_date"] == date(2026, 8, 31)


def test_a_delisted_nav_is_not_listed_rather_than_missing(context) -> None:
    # Delisted before the cutoff's month end: a sector that no longer exists,
    # which the plan leaves out, not a hole that keeps the book forever.
    changed = [
        dataclasses.replace(i, last_session=date(2026, 8, 28)) if i.id == "S_A_NAV" else i
        for i in context.instruments
    ]
    context = dataclasses.replace(context, instruments=InstrumentRegistry(changed))
    result = candidate(**SHORT).momentum().compute(context, ["S_A_NAV"])
    assert result.status("S_A_NAV") is SignalStatus.NOT_LISTED
    risk = candidate(risk_returns=3).risk_signal().compute(context, ["S_A_NAV"])
    assert risk.status("S_A_NAV") is SignalStatus.NOT_LISTED


def test_signals_declare_the_market_and_the_fx_they_read() -> None:
    strategy = candidate(**SHORT)
    assert strategy.momentum().referenced_instruments() == (MARKET,)
    assert strategy.risk_signal().referenced_instruments() == ("FX",)
    eur = candidate(risk_input_currency="EUR", usd_per_eur_fx_id=None).risk_signal()
    assert eur.referenced_instruments() == ()


@pytest.mark.parametrize("missing", [date(2026, 7, 31), date(2026, 8, 31)])
def test_missing_month_end_cannot_backfill_to_previous_available_nav(
    market,
    repository,
    make_levels,
    xnys,
    context,
    missing,
) -> None:
    values = drawn("S_A", xnys)
    del values[missing]
    repository.save_levels("S_A_NAV", make_levels("S_A_NAV", values))
    result = candidate(**SHORT).momentum().compute(context, ["S_A_NAV"])
    assert result.status("S_A_NAV") is SignalStatus.MISSING_INPUT


@pytest.mark.parametrize("name", ["S_A_NAV", "FX"])
def test_future_published_nav_or_fx_cancels_risk(
    context,
    repository,
    make_levels,
    xnys,
    name,
) -> None:
    values = (
        drawn("S_A", xnys)
        if name == "S_A_NAV"
        else {s.session_date: 1.2 for s in xnys.sessions(FIRST, LAST)}
    )
    frame = make_levels(name, values)
    frame.loc[frame["observation_date"] == date(2026, 8, 31), "available_at_utc"] = pd.Timestamp(
        "2026-11-07T12:00:00Z"
    )
    repository.save_levels(name, frame)
    result = candidate(risk_returns=3).risk_signal().compute(context, ["S_A_NAV"])
    assert result.status("S_A_NAV") is SignalStatus.MISSING_INPUT


def test_fx_divides_nav_before_returns_and_changes_risk(
    context,
    repository,
    make_levels,
    xnys,
) -> None:
    dates = [date(2026, 8, 26), date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 31)]
    rates = dict(zip(dates, [1.0, 1.1, 1.0, 1.25], strict=True))
    repository.save_levels("FX", make_levels("FX", rates))
    result = candidate(risk_returns=3).risk_signal().compute(context, ["S_A_NAV"])
    nav = drawn("S_A", xnys)
    expected = simple_returns([nav[day] / rates[day] for day in dates])
    assert result.status("S_A_NAV") is SignalStatus.OK
    assert result.frame.loc["S_A_NAV", "returns"] == pytest.approx(expected)


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "EUR"},
        {"primary_source": "ECB"},
        {"asset_type": AssetType.INDEX},
    ],
)
def test_wrong_fx_currency_and_ecb_fixings_are_refused(context, changes) -> None:
    changed = [
        dataclasses.replace(i, **changes) if i.id == "FX" else i for i in context.instruments
    ]
    context = dataclasses.replace(context, instruments=InstrumentRegistry(changed))
    with pytest.raises(ValueError, match="cannot convert"):
        candidate(risk_returns=3).risk_signal().compute(context, ["S_A_NAV"])


def test_retrieval_only_publication_cannot_admit_historical_nav(
    market,
    repository,
    make_levels,
    xnys,
    make_context,
    make_decision,
    evening,
) -> None:
    for name in SECTORS:
        frame = make_levels(f"{name}_NAV", drawn(name, xnys))
        frame["available_at_utc"] = pd.Timestamp("2026-11-07T12:00:00Z")
        repository.save_levels(f"{name}_NAV", frame)
    strategy = candidate(**SHORT)
    plan = real_plan(strategy, market, date(2026, 9, 30), make_context, make_decision, evening)
    assert not plan.complete
    assert plan.weights == {}
    assert plan.unusable == dict.fromkeys(SECTORS, SignalStatus.MISSING_INPUT)


@pytest.mark.parametrize("mode", ["missing", "shifted_date", "zero"])
def test_fx_must_exist_and_match_each_nav_date(
    context,
    repository,
    make_levels,
    mode,
) -> None:
    values = {
        date(2026, 8, 26): 1.0,
        date(2026, 8, 27): 1.1,
        date(2026, 8, 28): 1.0,
        date(2026, 8, 31): 1.25,
    }
    if mode == "missing":
        del values[date(2026, 8, 28)]
    elif mode == "shifted_date":
        values[date(2026, 8, 29)] = values.pop(date(2026, 8, 28))
    else:
        values[date(2026, 8, 28)] = 0.0
    repository.save_levels("FX", make_levels("FX", dict(sorted(values.items()))))
    result = candidate(risk_returns=3).risk_signal().compute(context, ["S_A_NAV"])
    expected = SignalStatus.INVALID_INPUT if mode == "zero" else SignalStatus.MISSING_INPUT
    assert result.status("S_A_NAV") is expected


def test_explicit_validated_eur_nav_needs_no_fx(context, xnys) -> None:
    changed = [
        dataclasses.replace(i, currency="EUR") if i.id == "S_A_NAV" else i
        for i in context.instruments
    ]
    context = dataclasses.replace(context, instruments=InstrumentRegistry(changed))
    signal = candidate(
        risk_returns=3,
        risk_input_currency="EUR",
        usd_per_eur_fx_id=None,
    ).risk_signal()
    result = signal.compute(context, ["S_A_NAV"])
    dates = result.frame.loc["S_A_NAV", "dates"]
    nav = drawn("S_A", xnys)
    assert result.status("S_A_NAV") is SignalStatus.OK
    assert result.frame.loc["S_A_NAV", "returns"] == pytest.approx(
        simple_returns([nav[day] for day in dates])
    )


def test_risk_rejects_unconverted_currency_mismatch(context) -> None:
    signal = candidate(risk_input_currency="EUR", usd_per_eur_fx_id=None).risk_signal()
    with pytest.raises(ValueError, match="EUR fund NAVs"):
        signal.compute(context, ["S_A_NAV"])


def test_future_cutoff_is_rejected(context) -> None:
    strategy = candidate(**SHORT)
    for signal in (strategy.momentum(), strategy.risk_signal()):
        future = dataclasses.replace(signal, observation_cutoff=date(2026, 9, 30))
        with pytest.raises(ValueError, match="after the decision"):
            future.compute(context, ["S_A_NAV"])


# -- through the engine -------------------------------------------------------------------


@pytest.fixture
def runner(market: MarketDataReader, calendars: CalendarRegistry) -> StrategyRunner:
    """Return a EUR runner over the drawn market, deciding at month ends."""
    return StrategyRunner(
        reader=market,
        calendars=calendars,
        reference_calendar_id="XPAR",
        base_currency="EUR",
        analytics=AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0),
        execution=ExecutionModel(
            costs=CostModel(
                commission_rate=0.0005,
                minimum_commission=1.0,
                half_spread_rate=0.0003,
                slippage_rate=0.0002,
            ),
            sizing=Sizing.AT_DECISION,
        ),
        initial_cash=100_000.0,
        schedule=Monthly(),
    )


SHORT = {"estimation_months": 4, "score_months": 2, "skip_months": 1, "risk_returns": 20}
"""A window the synthetic year can warm up: decisions from the end of June."""


def assert_invested_with_only_cash_trims(result: StrategyResult, name: str = "candidate") -> None:
    """Assert the book is invested from the first fill, short only of what the fill left.

    Quantities are fixed at the decision's closes and filled at the next open.
    A target of the whole book cannot be bought whole when the open is dearer
    or the fees are paid: the engine trims the last purchases and records the
    trim as an ``INSUFFICIENT_CASH`` reject on the buy side (SA16's study
    counts eleven). Any other reject would be a rule asking for something the
    book cannot do. The synthetic bars open at their own close, so a whole
    session's move falls between sizing and fill: the bound is loose.
    """
    rejects = result.rejects()
    assert set(rejects["reason"]) <= {"INSUFFICIENT_CASH"}, name
    assert set(rejects["side"]) <= {"BUY"}, name
    invested = result.weights().sum(axis=1)
    assert float(invested.loc[date(2026, 7, 1) :].min()) > 0.95, name


@pytest.mark.slow
def test_the_candidate_runs_through_the_engine_at_month_ends(runner) -> None:
    strategy = candidate(**SHORT)
    result = runner.run(strategy, UNIVERSE, "2026-06-01", "2026-12-31")
    decided = [record.session_date for record in result.records() if record.decision is not None]
    assert decided == [
        date(2026, 6, 30),
        date(2026, 7, 31),
        date(2026, 8, 31),
        date(2026, 9, 30),
        date(2026, 10, 30),
        date(2026, 11, 30),
    ]
    targets = result.target_weights().loc[decided]
    for _, row in targets.iterrows():
        sectors = row[list(SECTORS)]
        assert (sectors > 0.0).sum() == 3
        held = sectors[sectors > 0.0]
        assert float(held.max()) == pytest.approx(float(held.min()))  # equal parts
        assert float(row.sum()) == pytest.approx(1.0)
    assert_invested_with_only_cash_trims(result)
    # The market and the FX are read inside the signals, never asked about:
    # the report still names their history.
    basis = result.configuration["history_basis"]
    assert isinstance(basis, Mapping)
    assert {MARKET, "FX"} <= set(basis)
    again = runner.run(strategy, UNIVERSE, "2026-06-01", "2026-12-31")
    assert result.equity().equals(again.equity())


@pytest.mark.slow
def test_every_control_runs_through_the_engine(runner) -> None:
    for name, control in candidate(**SHORT).controls().items():
        result = runner.run(control, UNIVERSE, "2026-06-01", "2026-12-31")
        targets = result.target_weights()
        held = targets.loc[date(2026, 11, 30), list(SECTORS)]
        expected = 5 if name.startswith("equal_sectors") else 3
        assert int((held > 0.0).sum()) == expected, name
        assert_invested_with_only_cash_trims(result, name)
