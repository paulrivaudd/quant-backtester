"""The nine single-rule strategies: what each declares, decides and does without data.

Decisions are taken on signals of written value (see ``conftest.py``), on the
synthetic market's two Paris funds and its published rate standing in for the
volatility index. The band is tested once, on ``settle``. The benchmark, the
momentum and the volatility control are then run through the engine on the
offline demo market, with the windows of the specification.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

import pytest

from quant_backtester.analytics import AnalyticsConfig, alpha_vs_benchmark
from quant_backtester.backtest.context import StrategyContext
from quant_backtester.backtest.runner import StrategyRunner
from quant_backtester.demo import demo_runner
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.engine import SignalRequest
from quant_backtester.signals.types import SignalStatus
from quant_backtester.strategies.adaptive.rebalance import RuleStrategy, settle
from quant_backtester.strategies.examples import (
    BufferedDualMomentum,
    FactorETFBlend,
    MonetaryCarry,
    RealizedVolControl,
    RelativeResidualTilt,
    SmoothMovingAverage,
    TrendFilteredPullback,
    VixReliefEntry,
    WorldMA20Benchmark,
)

WORLD, SP500, THIRD, VIX = "ETF_EU", "ETF_OTHER", "ETF_LATE", "RATE_US"
"""The synthetic market's stand-ins for the two core funds, a third fund and the index."""

UNIVERSE = (WORLD, SP500, THIRD)
STALE = SignalStatus.STALE_INPUT

BENCHMARK = WorldMA20Benchmark(instrument_id=WORLD)
MOMENTUM = BufferedDualMomentum(first_id=WORLD, second_id=SP500)
TREND = SmoothMovingAverage(instrument_id=WORLD)
PULLBACK = TrendFilteredPullback(instrument_id=WORLD)
RELATIVE = RelativeResidualTilt(first_id=WORLD, second_id=SP500)
VOL_CONTROL = RealizedVolControl(instrument_id=WORLD)
FACTORS = FactorETFBlend(instrument_ids=UNIVERSE)
MONETARY = MonetaryCarry(instrument_id=THIRD)
RELIEF = VixReliefEntry(instrument_id=SP500, vix_id=VIX)

EVERY_RULE: tuple[RuleStrategy, ...] = (
    BENCHMARK,
    MOMENTUM,
    TREND,
    PULLBACK,
    RELATIVE,
    VOL_CONTROL,
    FACTORS,
    MONETARY,
    RELIEF,
)

Written = Mapping[tuple[str, str], float | SignalStatus]
Decide = Callable[..., TargetAllocation]


@pytest.fixture
def decide(written_decision: Callable[..., StrategyContext]) -> Decide:
    """Return what a strategy decides on written signal values, from a given book."""

    def run(
        strategy: RuleStrategy, values: Written, held: Mapping[str, float] | None = None
    ) -> TargetAllocation:
        return strategy.decide(written_decision(strategy, values, universe=UNIVERSE, held=held))

    return run


def weights_of(allocation: TargetAllocation) -> dict[str, float]:
    """Return the weights of a target that is not a hold."""
    assert not allocation.hold_positions
    return dict(allocation.weights)


# --- what each strategy declares -------------------------------------------------------


def declared(strategy: RuleStrategy) -> list[tuple[str, tuple[str, ...]]]:
    """Return ``(signal_id, instruments)`` for every signal a strategy declares."""
    pairs = []
    for item in strategy.required_signals():
        assert isinstance(item, SignalRequest)
        names = item.names()
        assert names is not None
        pairs.append((item.signal.signal_id, tuple(names)))
    return pairs


def test_each_strategy_declares_the_signals_of_its_specification() -> None:
    assert declared(WorldMA20Benchmark()) == [("world_above_ma20", ("ETF_WORLD",))]
    assert declared(BufferedDualMomentum()) == [
        ("momentum_126s_skip21", ("ETF_WORLD", "ETF_SP500_PEA")),
        ("momentum_252s_skip21", ("ETF_WORLD", "ETF_SP500_PEA")),
    ]
    assert declared(SmoothMovingAverage()) == [("ma50_over_ma200", ("ETF_WORLD",))]
    assert declared(TrendFilteredPullback()) == [
        ("pullback_5s_over_60r", ("ETF_WORLD",)),
        ("price_over_ma200", ("ETF_WORLD",)),
    ]
    assert declared(RelativeResidualTilt()) == [
        ("residual_vs_etf_sp500_pea_126r_5r", ("ETF_WORLD",))
    ]
    assert declared(RealizedVolControl()) == [
        ("volatility_20r", ("ETF_WORLD",)),
        ("volatility_60r", ("ETF_WORLD",)),
    ]
    assert declared(FACTORS) == [("volatility_60r", UNIVERSE)]
    assert declared(MONETARY) == [("momentum_63s_skip0", (THIRD,)), ("volatility_60r", (THIRD,))]
    assert declared(VixReliefEntry()) == [
        ("relief_20o", ("VIX",)),
        ("momentum_5s_skip0", ("ETF_SP500_PEA",)),
    ]


def test_the_price_signals_read_adjusted_closes_of_the_decided_session() -> None:
    for strategy in EVERY_RULE:
        for item in strategy.required_signals():
            assert isinstance(item, SignalRequest)
            definition = item.signal.definition()
            if definition["window_mode"] == "CONSECUTIVE_SESSIONS":
                assert definition["price_basis"] == "ADJUSTED"
                assert definition["bar_field"] == "close"
                assert definition["max_age_sessions"] == 0


def test_the_specified_windows_are_the_ones_computed() -> None:
    definitions = {
        item.signal.signal_id: item.signal.definition()
        for strategy in (*EVERY_RULE, WorldMA20Benchmark())
        for item in strategy.required_signals()
        if isinstance(item, SignalRequest)
    }

    assert definitions["world_above_ma20"]["window_sessions"] == 20
    assert definitions["momentum_252s_skip21"]["lookback_sessions"] == 252
    assert definitions["momentum_252s_skip21"]["skip_recent_sessions"] == 21
    assert definitions["momentum_126s_skip21"]["lookback_sessions"] == 126
    assert definitions["ma50_over_ma200"]["first_sessions"] == 50
    assert definitions["ma50_over_ma200"]["second_sessions"] == 200
    assert definitions["pullback_5s_over_60r"]["reference_returns"] == 60
    assert definitions["residual_vs_etf_other_126r_5r"]["estimation_returns"] == 126
    assert definitions["volatility_60r"]["annualization"] == 252
    assert definitions["volatility_60r"]["ddof"] == 1
    assert definitions["relief_20o"]["peak_minimum"] == 30.0
    assert definitions["relief_20o"]["relief_ratio"] == 0.80
    assert definitions["relief_20o"]["max_age_sessions"] == 1


def test_every_strategy_is_a_frozen_record_of_its_parameters() -> None:
    for strategy in EVERY_RULE:
        strategy.validate()
        assert len(strategy.fingerprint()) == 64
        assert strategy.parameters()["rebalance_band"] == 0.03
        with pytest.raises(AttributeError):
            strategy.rebalance_band = 0.5  # type: ignore[misc]


# --- the band --------------------------------------------------------------------------


@pytest.fixture
def book(written_decision: Callable[..., StrategyContext]) -> Callable[..., StrategyContext]:
    """Return a decision whose book holds the given weights."""

    def build(held: Mapping[str, float]) -> StrategyContext:
        return written_decision(
            BENCHMARK, {("world_above_ma20", WORLD): 0.01}, universe=UNIVERSE, held=held
        )

    return build


def test_a_book_within_three_points_of_its_target_is_kept(book) -> None:
    allocation = settle(book({WORLD: 0.48, SP500: 0.30}), {WORLD: 0.50, SP500: 0.28}, band=0.03)

    assert allocation.hold_positions
    assert dict(allocation.weights) == pytest.approx({WORLD: 0.48, SP500: 0.30})


def test_a_gap_of_three_points_sends_the_complete_target(book) -> None:
    allocation = settle(book({WORLD: 0.47, SP500: 0.30}), {WORLD: 0.50, SP500: 0.29}, band=0.03)

    assert weights_of(allocation) == {WORLD: 0.50, SP500: 0.29}


def test_the_band_never_holds_back_a_complete_exit(book) -> None:
    """A line of one point whose target is zero is sold."""
    allocation = settle(book({WORLD: 0.50, SP500: 0.01}), {WORLD: 0.50}, band=0.03)

    assert weights_of(allocation) == {WORLD: 0.50}


def test_an_empty_target_is_cash(book) -> None:
    allocation = settle(book({WORLD: 0.01}), {}, band=0.03)

    assert weights_of(allocation) == {}


def test_a_weight_above_its_cap_is_traded_back_inside_the_band(book) -> None:
    held, target = {WORLD: 0.41}, {WORLD: 0.40}

    assert settle(book(held), target, band=0.03).hold_positions
    assert weights_of(settle(book(held), target, band=0.03, caps={WORLD: 0.40})) == target


def test_a_forced_target_is_sent_inside_the_band(book) -> None:
    allocation = settle(book({WORLD: 0.49}), {WORLD: 0.50}, band=0.03, force=True)

    assert weights_of(allocation) == {WORLD: 0.50}


def test_a_small_entry_from_cash_waits_inside_the_band(book) -> None:
    allocation = settle(book({}), {WORLD: 0.02}, band=0.03)

    assert allocation.hold_positions
    assert dict(allocation.weights) == {}


def test_what_could_not_be_read_is_recorded_on_the_decision(book) -> None:
    allocation = settle(book({}), {WORLD: 0.50}, band=0.03, unusable={VIX: STALE, WORLD: STALE})

    assert dict(allocation.skipped) == {VIX: STALE}
    assert dict(settle(book({}), {}, band=0.03, unusable={VIX: STALE}).skipped) == {VIX: STALE}


# --- strategy 0 ------------------------------------------------------------------------

MA20 = ("world_above_ma20", WORLD)


def test_the_benchmark_buys_above_its_average_without_waiting_for_a_crossing(decide) -> None:
    assert weights_of(decide(BENCHMARK, {MA20: 0.004})) == {WORLD: 1.0}


def test_the_benchmark_sells_on_its_average_and_below(decide) -> None:
    assert weights_of(decide(BENCHMARK, {MA20: 0.0}, {WORLD: 0.99})) == {}
    assert weights_of(decide(BENCHMARK, {MA20: -0.03}, {WORLD: 0.99})) == {}


def test_the_benchmark_does_not_top_up_a_position_for_its_cash_residue(decide) -> None:
    assert decide(BENCHMARK, {MA20: 0.02}, {WORLD: 0.985}).hold_positions


def test_the_benchmark_without_a_window_is_cash_and_says_why(decide) -> None:
    allocation = decide(BENCHMARK, {MA20: SignalStatus.INSUFFICIENT_HISTORY}, {WORLD: 0.99})

    assert weights_of(allocation) == {}
    assert dict(allocation.skipped) == {WORLD: SignalStatus.INSUFFICIENT_HISTORY}


# --- strategy 1 ------------------------------------------------------------------------


def momenta(
    world: tuple[float | SignalStatus, float | SignalStatus],
    sp500: tuple[float | SignalStatus, float | SignalStatus],
) -> dict[tuple[str, str], float | SignalStatus]:
    """Return the written ``(medium, long)`` momenta of the two funds."""
    return {
        ("momentum_126s_skip21", WORLD): world[0],
        ("momentum_252s_skip21", WORLD): world[1],
        ("momentum_126s_skip21", SP500): sp500[0],
        ("momentum_252s_skip21", SP500): sp500[1],
    }


def test_momentum_leans_towards_the_stronger_fund(decide) -> None:
    allocation = decide(MOMENTUM, momenta((0.20, 0.10), (0.10, 0.10)))

    assert weights_of(allocation) == pytest.approx({WORLD: 0.75, SP500: 0.25})


def test_momentum_holds_three_quarters_of_the_only_rising_fund(decide) -> None:
    allocation = decide(MOMENTUM, momenta((0.20, -0.01), (0.10, 0.10)), {WORLD: 0.5, SP500: 0.5})

    assert weights_of(allocation) == {SP500: 0.75}


def test_momentum_missing_on_one_fund_puts_the_whole_rule_in_cash(decide) -> None:
    allocation = decide(MOMENTUM, momenta((0.20, 0.10), (0.10, STALE)), {WORLD: 0.5, SP500: 0.5})

    assert weights_of(allocation) == {}
    assert dict(allocation.skipped) == {SP500: STALE}


# --- strategies 2 and 3 ----------------------------------------------------------------


def test_the_smooth_average_is_half_invested_at_half_the_gap(decide) -> None:
    assert weights_of(decide(TREND, {("ma50_over_ma200", WORLD): 0.01})) == {WORLD: 0.5}
    assert weights_of(decide(TREND, {("ma50_over_ma200", WORLD): 0.05})) == {WORLD: 1.0}
    assert weights_of(decide(TREND, {("ma50_over_ma200", WORLD): -0.01}, {WORLD: 0.5})) == {}
    assert weights_of(decide(TREND, {("ma50_over_ma200", WORLD): STALE}, {WORLD: 0.5})) == {}


def test_the_pullback_is_bought_above_the_long_average_only(decide) -> None:
    fall, trend = ("pullback_5s_over_60r", WORLD), ("price_over_ma200", WORLD)

    assert weights_of(decide(PULLBACK, {fall: 1.0, trend: 0.04})) == {WORLD: 0.25}
    assert weights_of(decide(PULLBACK, {fall: 5.0, trend: 0.04})) == {WORLD: 0.50}
    assert weights_of(decide(PULLBACK, {fall: 5.0, trend: -0.01}, {WORLD: 0.5})) == {}
    assert weights_of(decide(PULLBACK, {fall: 0.2, trend: 0.04}, {WORLD: 0.5})) == {}
    assert weights_of(decide(PULLBACK, {fall: 5.0, trend: STALE}, {WORLD: 0.5})) == {}


def test_a_pullback_position_above_its_cap_is_cut_back(decide) -> None:
    values = {("pullback_5s_over_60r", WORLD): 5.0, ("price_over_ma200", WORLD): 0.04}

    assert weights_of(decide(PULLBACK, values, {WORLD: 0.52})) == {WORLD: 0.50}
    assert decide(PULLBACK, values, {WORLD: 0.49}).hold_positions


# --- strategy 4 ------------------------------------------------------------------------

RESIDUAL = ("residual_vs_etf_other_126r_5r", WORLD)


def test_the_tilt_overweights_the_fund_that_lagged(decide) -> None:
    assert weights_of(decide(RELATIVE, {RESIDUAL: 2.0})) == pytest.approx(
        {WORLD: 0.75, SP500: 0.25}
    )
    assert weights_of(decide(RELATIVE, {RESIDUAL: -1.0})) == pytest.approx(
        {WORLD: 0.375, SP500: 0.625}
    )


def test_the_tilt_is_neutral_on_a_residual_of_zero_and_cash_without_one(decide) -> None:
    assert weights_of(decide(RELATIVE, {RESIDUAL: 0.0})) == {WORLD: 0.5, SP500: 0.5}
    held = {WORLD: 0.5, SP500: 0.5}
    assert weights_of(decide(RELATIVE, {RESIDUAL: SignalStatus.INVALID_INPUT}, held)) == {}


# --- strategy 5 ------------------------------------------------------------------------


def test_the_volatility_control_scales_to_the_larger_estimate(decide) -> None:
    short, long = ("volatility_20r", WORLD), ("volatility_60r", WORLD)

    assert weights_of(decide(VOL_CONTROL, {short: 0.24, long: 0.15})) == {WORLD: 0.5}
    assert weights_of(decide(VOL_CONTROL, {short: 0.08, long: 0.10})) == {WORLD: 1.0}
    assert weights_of(decide(VOL_CONTROL, {short: STALE, long: 0.10}, {WORLD: 0.9})) == {}


# --- strategy 6 ------------------------------------------------------------------------


def test_the_blend_weights_three_funds_and_never_renormalises(decide) -> None:
    levels = zip(UNIVERSE, (0.2, 0.2, 0.1), strict=True)
    volatility = {("volatility_60r", name): value for name, value in levels}

    allocation = weights_of(decide(FACTORS, volatility))

    assert allocation[THIRD] == pytest.approx(0.40)
    assert allocation[WORLD] == pytest.approx(0.5 / 3 + 0.125)
    assert sum(allocation.values()) < 1.0


def test_the_blend_without_one_fund_holds_none(decide) -> None:
    volatility: dict[tuple[str, str], float | SignalStatus] = {
        ("volatility_60r", WORLD): 0.2,
        ("volatility_60r", SP500): 0.2,
        ("volatility_60r", THIRD): SignalStatus.NOT_LISTED,
    }

    allocation = decide(FACTORS, volatility, {WORLD: 0.3, SP500: 0.3})

    assert weights_of(allocation) == {}
    assert dict(allocation.skipped) == {THIRD: SignalStatus.NOT_LISTED}


@pytest.mark.parametrize("names", [(WORLD, SP500), (WORLD, SP500, WORLD), (WORLD, SP500, "")])
def test_the_blend_takes_exactly_three_distinct_funds(names: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        FactorETFBlend(instrument_ids=names)


# --- strategy 7 ------------------------------------------------------------------------


def test_the_money_market_fund_is_held_when_its_carry_covers_the_round_trip(decide) -> None:
    carry, volatility = ("momentum_63s_skip0", THIRD), ("volatility_60r", THIRD)

    assert weights_of(decide(MONETARY, {carry: 0.004, volatility: 0.005})) == {THIRD: 1.0}
    assert weights_of(decide(MONETARY, {carry: 0.001, volatility: 0.005}, {THIRD: 0.99})) == {}
    assert weights_of(decide(MONETARY, {carry: 0.004, volatility: 0.03}, {THIRD: 0.99})) == {}
    assert weights_of(decide(MONETARY, {carry: STALE, volatility: 0.005}, {THIRD: 0.99})) == {}


# --- strategy 8 ------------------------------------------------------------------------


def test_the_relief_entry_needs_a_relief_and_a_recovery(decide) -> None:
    relief, recovery = ("relief_20o", VIX), ("momentum_5s_skip0", SP500)

    assert weights_of(decide(RELIEF, {relief: 1.0, recovery: 0.02})) == {SP500: 0.50}
    assert weights_of(decide(RELIEF, {relief: 0.0, recovery: 0.02}, {SP500: 0.5})) == {}
    assert weights_of(decide(RELIEF, {relief: 1.0, recovery: -0.02}, {SP500: 0.5})) == {}


def test_a_stale_index_is_cash_and_is_named(decide) -> None:
    allocation = decide(
        RELIEF, {("relief_20o", VIX): STALE, ("momentum_5s_skip0", SP500): 0.02}, {SP500: 0.5}
    )

    assert weights_of(allocation) == {}
    assert dict(allocation.skipped) == {VIX: STALE}


# --- configurations refused ------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: WorldMA20Benchmark(window_sessions=1),
        lambda: WorldMA20Benchmark(rebalance_band=1.5),
        lambda: BufferedDualMomentum(first_id=WORLD, second_id=WORLD),
        lambda: BufferedDualMomentum(tilt=0.6),
        lambda: BufferedDualMomentum(skip_recent_sessions=126),
        lambda: SmoothMovingAverage(fast=200, slow=50),
        lambda: SmoothMovingAverage(full_exposure_gap=0.0),
        lambda: TrendFilteredPullback(maximum_weight=1.5),
        lambda: TrendFilteredPullback(z_range=0.0),
        lambda: RelativeResidualTilt(first_id=SP500, second_id=SP500),
        lambda: RelativeResidualTilt(estimation_returns=5),
        lambda: RealizedVolControl(short_returns=60),
        lambda: RealizedVolControl(target_volatility=float("nan")),
        lambda: MonetaryCarry(instrument_id=""),
        lambda: MonetaryCarry(instrument_id=THIRD, round_trip_cost=-0.1),
        lambda: VixReliefEntry(relief_ratio=1.5),
        lambda: VixReliefEntry(weight=-0.1),
    ],
)
def test_a_configuration_that_cannot_be_computed_is_refused(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        build()


# --- through the engine, on the offline demo market ------------------------------------

DEMO_PERIOD = ("2025-01-02", "2025-12-31")
"""The second year of the demo market: a year of closes sits before it."""


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> StrategyRunner:
    """Return a runner over the offline synthetic market."""
    return demo_runner(tmp_path_factory.mktemp("etf_strategies") / "store", seed=20240101)


@pytest.mark.parametrize(
    "strategy",
    [
        WorldMA20Benchmark(instrument_id="FUND_A"),
        BufferedDualMomentum(first_id="FUND_A", second_id="FUND_B"),
        RealizedVolControl(instrument_id="FUND_A"),
        RelativeResidualTilt(first_id="FUND_A", second_id="FUND_B"),
    ],
    ids=lambda strategy: strategy.strategy_id,
)
def test_a_run_holds_positive_weights_that_never_exceed_the_book(
    demo: StrategyRunner, strategy: RuleStrategy
) -> None:
    result = demo.run(strategy, ("FUND_A", "FUND_B"), *DEMO_PERIOD)

    targets = result.target_weights()
    assert len(result.fills()) >= 1
    assert (targets.to_numpy() >= 0.0).all()
    assert (targets.sum(axis=1) <= 1.0 + 1e-9).all()
    assert math.isfinite(result.backtest.net_return)


def test_the_benchmark_measured_against_itself_has_a_beta_of_one(demo: StrategyRunner) -> None:
    result = demo.run(WorldMA20Benchmark(instrument_id="FUND_A"), ("FUND_A",), *DEMO_PERIOD)
    config = AnalyticsConfig(sessions_per_year=252, risk_free_rate=0.0)

    measured = alpha_vs_benchmark(result.equity(), result.equity(), config)

    assert measured.beta == pytest.approx(1.0)
    assert measured.alpha_annualised == pytest.approx(0.0, abs=1e-12)
    assert measured.outperformance == 0.0
    assert measured.observations == len(result.equity()) - 1
