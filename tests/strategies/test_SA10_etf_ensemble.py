"""ETFEnsemble: budgets, the cap, the risk control, the money-market fund and the band.

Decisions are taken on signals of written value. The registry of this module
adds three style funds and a money-market fund to the synthetic market; the two
Paris funds stand in for the core funds and the published rate for the
volatility index. One last test computes every real signal over a year of
closes, to prove the declared windows are the ones read and that nothing sees
past the decision.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from quant_backtester.backtest.context import StrategyContext
from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import AssetType, DataType, Instrument, InstrumentRegistry
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.engine import SignalEngine, SignalRequest
from quant_backtester.signals.price.momentum import MomentumSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.strategies import ETFEnsemble
from quant_backtester.strategies.adaptive.inputs import merged_requests, volatility
from quant_backtester.strategies.adaptive.rules import MISSING_INPUT

WORLD, SP500, VIX = "ETF_EU", "ETF_OTHER", "RATE_US"
FACTORS = ("FACTOR_VALUE", "FACTOR_QUALITY", "FACTOR_MINVOL")
MONEY = "MONEY_EUR"
UNIVERSE = (WORLD, SP500, *FACTORS, MONEY)
STALE = SignalStatus.STALE_INPUT

Written = dict[tuple[str, str], float | SignalStatus]


@pytest.fixture
def instruments(instruments: InstrumentRegistry) -> InstrumentRegistry:
    """Return the synthetic registry plus three style funds and a money-market fund."""
    added = [
        Instrument(
            id=name,
            name=name,
            asset_type=AssetType.ETF,
            data_type=DataType.BAR,
            currency="EUR",
            primary_source="YAHOO",
            source_symbol=f"{name}.PA",
            tradable=True,
            calendar_id="XPAR",
            first_session=date(2026, 1, 5),
        )
        for name in (*FACTORS, MONEY)
    ]
    return InstrumentRegistry([*instruments, *added])


def ensemble(*, factors: bool = False, monetary: bool = False, **changes: object) -> ETFEnsemble:
    """Return the ensemble on the synthetic market."""
    fields: dict[str, object] = {
        "enable_factors": factors,
        "enable_monetary": monetary,
        "world_id": WORLD,
        "sp500_id": SP500,
        "vix_id": VIX,
        "factor_ids": FACTORS,
        "monetary_id": MONEY,
    }
    return ETFEnsemble(**(fields | changes))  # type: ignore[arg-type]


def quiet(
    strategy: ETFEnsemble, changes: Mapping[tuple[str, str], float | SignalStatus]
) -> Written:
    """Return a value for every declared signal: a calm rising market, then ``changes``.

    Both core funds rise alike (momentum neutral), the trend is fully on, there
    is no pullback, no residual and no relief, every volatility is 10% - 1% for
    the money-market fund, whose carry covers its round trip.
    """
    defaults: dict[str, float] = {
        "momentum_126s_skip21": 0.10,
        "momentum_252s_skip21": 0.10,
        "ma50_over_ma200": 0.03,
        "pullback_5s_over_60r": 0.0,
        "price_over_ma200": 0.05,
        "residual_vs_etf_other_126r_5r": 0.0,
        "relief_20o": 0.0,
        "momentum_5s_skip0": 0.01,
        "momentum_63s_skip0": 0.004,
        "volatility_20r": 0.10,
        "volatility_60r": 0.10,
    }
    values: Written = {}
    for item in strategy.required_signals():
        assert isinstance(item, SignalRequest)
        for name in item.names() or ():
            values[item.signal.signal_id, name] = defaults[item.signal.signal_id]
    if ("volatility_60r", MONEY) in values:
        values["volatility_60r", MONEY] = 0.01
    unknown = set(changes) - set(values)
    assert not unknown, f"not declared: {unknown}"
    return values | dict(changes)


@pytest.fixture
def decision(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Return the decision an ensemble sees on a calm market with some values changed."""

    def build(
        strategy: ETFEnsemble,
        changes: Mapping[tuple[str, str], float | SignalStatus] | None = None,
        held: Mapping[str, float] | None = None,
    ) -> StrategyContext:
        return written_decision(
            strategy, quiet(strategy, changes or {}), universe=UNIVERSE, held=held
        )

    return build


def weights_of(allocation: TargetAllocation) -> dict[str, float]:
    """Return the weights of a target that is not a hold."""
    assert not allocation.hold_positions
    return dict(allocation.weights)


# --- what is declared ------------------------------------------------------------------


def test_the_first_run_declares_the_two_core_funds_and_the_index_only() -> None:
    requests = ensemble().required_signals()
    names = {name for item in requests for name in item.names() or ()}  # type: ignore[union-attr]

    assert names == {WORLD, SP500, VIX}
    ids = [item.signal.signal_id for item in requests]  # type: ignore[union-attr]
    assert len(ids) == len(set(ids))
    assert "momentum_63s_skip0" not in ids
    ensemble().validate()


def test_enabled_parts_declare_their_funds_and_share_a_signal_with_the_others() -> None:
    requests = {
        item.signal.signal_id: tuple(item.names() or ())  # type: ignore[union-attr]
        for item in ensemble(factors=True, monetary=True).required_signals()
    }

    assert requests["volatility_60r"] == (*FACTORS, MONEY, WORLD, SP500)
    assert requests["volatility_20r"] == (WORLD, SP500, *FACTORS)
    assert requests["momentum_63s_skip0"] == (MONEY,)
    assert requests["relief_20o"] == (VIX,)


def test_two_different_signals_cannot_share_a_name() -> None:
    same = [SignalRequest(volatility(60), ("A",)), SignalRequest(volatility(60), ("B", "A"))]
    assert merged_requests(same) == (SignalRequest(volatility(60), ("A", "B")),)

    clash = SignalRequest(
        MomentumSignal(
            signal_id="volatility_60r", lookback_sessions=60, price_basis=PriceBasis.ADJUSTED
        ),
        ("A",),
    )
    with pytest.raises(ValueError, match="both named"):
        merged_requests([same[0], clash])


def test_the_definition_records_the_parameters_of_every_rule() -> None:
    strategy = ensemble(factors=True, monetary=True)
    rules = strategy.parameters()["rules"]

    assert isinstance(rules, dict)
    assert set(rules) == {
        "momentum",
        "trend",
        "pullback",
        "relative",
        "factors",
        "relief",
        "monetary",
    }
    assert rules["momentum"]["full_tilt_gap"] == 0.05
    json.dumps(strategy.definition())
    assert strategy.fingerprint() != ensemble().fingerprint()


@pytest.mark.parametrize(
    "build",
    [
        lambda: ensemble(factors=True, factor_ids=FACTORS[:2]),
        lambda: ensemble(monetary=True, monetary_id=None),
        lambda: ensemble(sp500_id=WORLD),
        lambda: ensemble(factors=True, factor_ids=(WORLD, *FACTORS[:2])),
        lambda: ensemble(monetary=True, monetary_id=SP500),
        lambda: ensemble(momentum_budget=0.70),
        lambda: ensemble(equity_cap=1.5),
        lambda: ensemble(short_returns=60),
        lambda: ensemble(monetary=True, volatility_floor=0.02),
        lambda: ETFEnsemble(enable_factors=1, enable_monetary=False),  # type: ignore[arg-type]
    ],
)
def test_a_configuration_that_cannot_be_held_is_refused(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        build()


# --- budgets and the cap ---------------------------------------------------------------


def test_the_budgets_add_up_fund_by_fund_and_a_silent_rule_leaves_its_share_in_cash(
    decision,
) -> None:
    """World: 0.2 * 0.5 + 0.2 * 1 + 0.1 * 0.5. S&P: 0.2 * 0.5 + 0.1 * 0.5."""
    strategy = ensemble()
    plan = strategy.plan(decision(strategy))

    assert dict(plan.budgeted) == pytest.approx({WORLD: 0.35, SP500: 0.15})
    assert plan.scale == 1.0
    assert dict(plan.weights) == pytest.approx({WORLD: 0.35, SP500: 0.15})
    assert weights_of(strategy.decide(decision(strategy))) == pytest.approx(
        {WORLD: 0.35, SP500: 0.15}
    )


def test_an_inactive_rule_does_not_strengthen_the_others(decision) -> None:
    strategy = ensemble()
    changes: Written = {("ma50_over_ma200", WORLD): SignalStatus.INSUFFICIENT_HISTORY}
    plan = strategy.plan(decision(strategy, changes))

    assert plan.rules["trend"].reason == MISSING_INPUT
    assert dict(plan.weights) == pytest.approx({WORLD: 0.15, SP500: 0.15})


def test_each_equity_fund_is_capped_without_renormalising(decision) -> None:
    """World would hold 0.15 + 0.20 + 0.05 + 0.075 = 0.475."""
    strategy = ensemble()
    changes: Written = {
        ("momentum_126s_skip21", WORLD): 0.30,
        ("pullback_5s_over_60r", WORLD): 3.0,
        ("residual_vs_etf_other_126r_5r", WORLD): 4.0,
        ("volatility_20r", WORLD): 0.05,
        ("volatility_60r", WORLD): 0.05,
        ("volatility_20r", SP500): 0.05,
        ("volatility_60r", SP500): 0.05,
    }
    plan = strategy.plan(decision(strategy, changes))

    assert dict(plan.weights) == pytest.approx({WORLD: 0.40, SP500: 0.05 + 0.025})


def test_the_style_funds_take_their_budget_when_enabled(decision) -> None:
    strategy = ensemble(factors=True)
    plan = strategy.plan(decision(strategy))

    assert [plan.weights[name] for name in FACTORS] == pytest.approx([0.10] * 3)
    assert sum(plan.weights.values()) == pytest.approx(0.80)


def test_the_relief_rule_adds_five_points_of_the_second_fund(decision) -> None:
    strategy = ensemble()
    plan = strategy.plan(decision(strategy, {("relief_20o", VIX): 1.0}))

    assert plan.weights[SP500] == pytest.approx(0.15 + 0.10 * 0.50)


# --- the risk control ------------------------------------------------------------------


def test_the_book_is_scaled_to_twelve_percent_of_estimated_risk(decision) -> None:
    """V = 0.5 at 30%: S = 0.15, lambda = 0.8."""
    strategy = ensemble()
    changes: Written = {("volatility_20r", WORLD): 0.30, ("volatility_20r", SP500): 0.30}
    plan = strategy.plan(decision(strategy, changes))

    assert plan.scale == pytest.approx(0.8)
    assert dict(plan.weights) == pytest.approx({WORLD: 0.28, SP500: 0.12})
    assert sum(plan.weights[name] * plan.volatilities[name] for name in plan.weights) == (
        pytest.approx(0.12)
    )


def test_a_fund_without_a_volatility_is_set_to_zero_before_the_control(decision) -> None:
    strategy = ensemble()
    allocation = strategy.decide(decision(strategy, {("volatility_60r", SP500): STALE}))

    assert weights_of(allocation) == pytest.approx({WORLD: 0.35})
    assert dict(allocation.skipped) == {SP500: STALE}


def test_an_eligible_money_market_fund_takes_the_rest_of_the_book(decision) -> None:
    strategy = ensemble(monetary=True)
    changes: Written = {("volatility_20r", WORLD): 0.30, ("volatility_20r", SP500): 0.30}
    plan = strategy.plan(decision(strategy, changes))

    scale = (0.12 - 0.01) / (0.15 - 0.5 * 0.01)
    assert plan.monetary_volatility == 0.01
    assert plan.scale == pytest.approx(scale)
    assert plan.weights[MONEY] == pytest.approx(1.0 - scale * 0.5)
    assert sum(plan.weights.values()) == pytest.approx(1.0)
    risk = scale * 0.15 + plan.weights[MONEY] * 0.01
    assert risk == pytest.approx(0.12)


def test_a_money_market_fund_that_is_not_eligible_holds_nothing(decision) -> None:
    strategy = ensemble(monetary=True)
    for changes in (
        {("momentum_63s_skip0", MONEY): 0.0005},
        {("volatility_60r", MONEY): 0.03},
        {("momentum_63s_skip0", MONEY): STALE},
    ):
        plan = strategy.plan(decision(strategy, changes))

        assert MONEY not in plan.weights
        assert plan.monetary_volatility == 0.0
        assert dict(plan.weights) == pytest.approx({WORLD: 0.35, SP500: 0.15})


def test_nothing_targeted_and_no_money_market_fund_is_cash(decision) -> None:
    strategy = ensemble()
    changes: Written = {
        ("momentum_252s_skip21", WORLD): -0.1,
        ("momentum_252s_skip21", SP500): -0.1,
        ("ma50_over_ma200", WORLD): -0.02,
        ("residual_vs_etf_other_126r_5r", WORLD): SignalStatus.INVALID_INPUT,
    }
    context = decision(strategy, changes, {WORLD: 0.3})

    assert strategy.plan(context).scale == 0.0
    assert weights_of(strategy.decide(context)) == {}


# --- the band, once --------------------------------------------------------------------


def test_a_book_inside_the_band_is_kept(decision) -> None:
    strategy = ensemble()

    assert strategy.decide(decision(strategy, held={WORLD: 0.34, SP500: 0.16})).hold_positions


def test_a_book_outside_the_band_gets_one_complete_target(decision) -> None:
    strategy = ensemble()
    allocation = strategy.decide(decision(strategy, held={WORLD: 0.30, SP500: 0.16}))

    assert weights_of(allocation) == pytest.approx({WORLD: 0.35, SP500: 0.15})


def test_the_band_is_set_aside_when_the_book_carries_too_much_estimated_risk(decision) -> None:
    """Held 0.29 + 0.13 at 30% is 12.6%: inside the band of the target, above the limit."""
    strategy = ensemble()
    changes: Written = {("volatility_20r", WORLD): 0.30, ("volatility_20r", SP500): 0.30}

    risky = strategy.decide(decision(strategy, changes, {WORLD: 0.29, SP500: 0.13}))
    safe = strategy.decide(decision(strategy, changes, {WORLD: 0.27, SP500: 0.12}))

    assert weights_of(risky) == pytest.approx({WORLD: 0.28, SP500: 0.12})
    assert safe.hold_positions


def test_the_band_is_set_aside_when_an_equity_fund_is_above_its_cap(decision) -> None:
    strategy = ensemble(equity_cap=0.35)
    quiet_vol: Written = {("volatility_20r", WORLD): 0.05, ("volatility_60r", WORLD): 0.05}

    allocation = strategy.decide(decision(strategy, quiet_vol, {WORLD: 0.36, SP500: 0.15}))

    assert weights_of(allocation) == pytest.approx({WORLD: 0.35, SP500: 0.15})


# --- the real signals, over a year -----------------------------------------------------


def test_the_declared_signals_are_the_ones_read_and_none_sees_past_the_decision(
    make_market: Callable[..., MarketDataReader],
    make_bars: Callable[..., pd.DataFrame],
    make_levels: Callable[..., pd.DataFrame],
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    make_decision: Callable[..., StrategyContext],
    xpar: TradingCalendar,
    evening: Callable[[date], datetime],
    rng_seed: int,
) -> None:
    """254 closes behind 30 December 2026; the close of the 31st must change nothing."""
    days = [day.session_date for day in xpar.sessions(date(2026, 1, 5), date(2026, 12, 31))]
    rng = np.random.default_rng(rng_seed)
    common = rng.normal(0.0004, 0.008, len(days))
    closes = {
        WORLD: 100.0 * np.exp(np.cumsum(common + rng.normal(0.0, 0.002, len(days)))),
        SP500: 50.0 * np.exp(np.cumsum(1.1 * common + rng.normal(0.0, 0.002, len(days)))),
    }
    gauge = 18.0 + 4.0 * np.sin(np.arange(len(days)) / 9.0)
    strategy = ensemble()

    def decide(known: int) -> TargetAllocation:
        bars = {
            name: make_bars(name, xpar, dict(zip(days[:known], map(float, path), strict=False)))
            for name, path in closes.items()
        }
        levels = {VIX: make_levels(VIX, dict(zip(days[:known], map(float, gauge), strict=False)))}
        context = make_context(make_market(bars, None, levels), evening(days[-2]))
        requests = [item.resolved(days[-2]) for item in strategy.required_signals()]  # type: ignore[union-attr]
        snapshot = SignalEngine().compute(context, requests, [WORLD, SP500])
        for signal_id in snapshot:
            frame = snapshot.values(signal_id)
            assert (frame["status"] == SignalStatus.OK).all(), signal_id
        return strategy.decide(make_decision(context, snapshot, universe=(WORLD, SP500)))

    seen = decide(len(days) - 1)
    with_future = decide(len(days))

    assert dict(seen.weights) == dict(with_future.weights)
    assert set(seen.weights) <= {WORLD, SP500}
    assert all(0.0 < weight <= 0.40 for weight in seen.weights.values())
    assert math.fsum(seen.weights.values()) <= 1.0
