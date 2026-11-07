"""SA17's mechanism study: formation, holding, costs and the look-ahead guard."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from zipfile import ZipFile

import numpy as np
import pytest

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.uncertainty import PairedStatistic, paired_stationary_bootstrap
from quant_backtester.data.sources.ken_french import KenFrenchDataset
from quant_backtester.research.sa17_mechanism import (
    BookName,
    IndustryPanel,
    ScoreWindow,
    Verdict,
    active_statistics,
    build_panel,
    compound_annual_growth,
    excess_curve,
    form,
    holding_formations,
    max_drawdown,
    replay_monthly_returns,
    run_book,
    sharpe_ratio,
    verdict,
)
from quant_backtester.signals.cross_asset.residual_momentum import residual_fit

SMALL = ScoreWindow(estimation_months=6, score_months=3, skip_months=1)
FROZEN = ScoreWindow(estimation_months=36, score_months=11, skip_months=1)


def months(count: int, start: date = date(2000, 1, 1)) -> tuple[date, ...]:
    ordinal = start.year * 12 + start.month - 1
    return tuple(date((ordinal + i) // 12, (ordinal + i) % 12 + 1, 1) for i in range(count))


def panel(
    returns: Mapping[str, Sequence[float | None]],
    market: Sequence[float],
    risk_free: Sequence[float] | None = None,
) -> IndustryPanel:
    count = len(market)
    return IndustryPanel(
        months=months(count),
        industries=tuple(returns),
        returns={name: tuple(values) for name, values in returns.items()},
        market=tuple(market),
        risk_free=tuple(risk_free if risk_free is not None else [0.001] * count),
    )


def random_panel(count: int, names: int, seed: int, holes: int = 0) -> IndustryPanel:
    generator = np.random.default_rng(seed)
    market = list(generator.normal(0.008, 0.045, count))
    returns: dict[str, list[float | None]] = {}
    for index in range(names):
        beta = 0.6 + 0.1 * index
        noise = generator.normal(0.0, 0.03, count)
        returns[f"I{index}"] = [beta * m + e for m, e in zip(market, noise, strict=True)]
    for _ in range(holes):
        name = f"I{int(generator.integers(0, names))}"
        returns[name][int(generator.integers(0, count))] = None
    risk_free = list(generator.uniform(0.0, 0.004, count))
    return panel(returns, market, risk_free)


# --- Formation ------------------------------------------------------------------


def test_the_residual_ranking_sets_beta_aside_where_plain_momentum_does_not() -> None:
    # The market rises in the scored months (positions 2-4). HIGH_BETA moves
    # twice as much with no residual of note; ALPHA beats the market by a
    # steady margin in the scored months. Plain momentum prefers HIGH_BETA,
    # the residual score prefers ALPHA.
    market = [0.01, -0.03, 0.04, 0.05, 0.04, -0.02]
    high_beta = [
        2 * m + e for m, e in zip(market, [1e-3, -1e-3, 2e-3, -2e-3, 1e-3, -1e-3], strict=True)
    ]
    alpha = [m + e for m, e in zip(market, [-0.02, -0.015, 0.01, 0.012, 0.011, -0.01], strict=True)]
    flat = [m + e for m, e in zip(market, [0.002, -0.001, -0.004, 0.001, 0.0, 0.002], strict=True)]
    data = panel({"FLAT": flat, "HIGH_BETA": high_beta, "ALPHA": alpha}, market)

    formed = form(data, 5, SMALL, held=1)

    assert formed.targets[BookName.RESIDUAL] == {"ALPHA": 1.0}
    assert formed.targets[BookName.C1_MOMENTUM_12_1] == {"HIGH_BETA": 1.0}
    assert formed.targets[BookName.C2_EQUAL_WEIGHT] == pytest.approx(
        {"FLAT": 1 / 3, "HIGH_BETA": 1 / 3, "ALPHA": 1 / 3}
    )
    # The scores are residual_fit's on the window, the momentum compounds by hand.
    expected = residual_fit(alpha, market, score_months=3, skip_months=1)
    assert expected is not None
    assert formed.residual_scores["ALPHA"] == expected.score
    assert formed.momentum["HIGH_BETA"] == pytest.approx(
        (1 + high_beta[2]) * (1 + high_beta[3]) * (1 + high_beta[4]) - 1
    )


def test_the_score_is_the_least_squares_residual_score_of_the_frozen_window() -> None:
    data = random_panel(48, 5, seed=3)
    formed = form(data, 40, FROZEN, held=2)
    market = np.array(data.market[5:41])
    design = np.column_stack([np.ones(36), market])
    for name in data.industries:
        values = np.array(data.returns[name][5:41], dtype=float)
        coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
        residuals = values - design @ coefficients
        scored = residuals[24:35]  # months t-11..t-1: the latest one skipped
        assert formed.residual_scores[name] == pytest.approx(
            scored.mean() / scored.std(ddof=1), rel=1e-9
        )
        assert formed.momentum[name] == pytest.approx(float(np.prod(1 + values[24:35]) - 1))


def test_a_missing_month_in_the_window_makes_an_industry_ineligible() -> None:
    data = random_panel(40, 4, seed=4)
    holed = dict(data.returns)
    series = list(holed["I1"])
    series[30] = None
    holed["I1"] = tuple(series)
    formed = form(dataclasses.replace(data, returns=holed), 37, FROZEN, held=2)
    assert "I1" not in formed.eligible
    assert all("I1" not in weights for weights in formed.targets.values())


def test_a_fit_residual_fit_refuses_is_counted_and_ineligible() -> None:
    market = [0.01, -0.03, 0.04, 0.05, 0.04, -0.02]
    exact = [2 * m for m in market]  # no residual at all
    other = [m + e for m, e in zip(market, [0.01, -0.01, 0.02, 0.0, -0.01, 0.0], strict=True)]
    formed = form(panel({"EXACT": exact, "OTHER": other}, market), 5, SMALL, held=1)
    assert formed.refused_fits == ("EXACT",)
    assert formed.eligible == ("OTHER",)


def test_ties_go_to_the_earlier_column() -> None:
    market = [0.01, -0.03, 0.04, 0.05, 0.04, -0.02]
    twin = [m + e for m, e in zip(market, [0.01, -0.01, 0.02, 0.0, -0.01, 0.0], strict=True)]
    formed = form(panel({"B": list(twin), "A": list(twin)}, market), 5, SMALL, held=1)
    assert formed.targets[BookName.RESIDUAL] == {"B": 1.0}
    assert formed.targets[BookName.C1_MOMENTUM_12_1] == {"B": 1.0}


def test_too_few_eligible_industries_hold_the_risk_free_rate() -> None:
    data = random_panel(40, 2, seed=5)
    formed = form(data, 37, FROZEN, held=3)
    assert formed.targets[BookName.RESIDUAL] == {}
    assert formed.targets[BookName.C1_MOMENTUM_12_1] == {}
    assert formed.targets[BookName.C2_EQUAL_WEIGHT] == pytest.approx({"I0": 0.5, "I1": 0.5})
    months_held = run_book(data, [formed], BookName.RESIDUAL, cost_rate=0.001)
    assert months_held[0].gross == pytest.approx(data.risk_free[38])
    assert months_held[0].turnover == 0.0


def test_a_window_that_does_not_fit_is_refused() -> None:
    data = random_panel(40, 3, seed=6)
    with pytest.raises(ValueError, match="does not fit"):
        form(data, 34, FROZEN, held=1)
    with pytest.raises(ValueError, match="does not fit"):
        holding_formations(data, FROZEN, 1, data.months[35], data.months[39])


# --- The look-ahead guard ---------------------------------------------------------


def test_returns_after_the_formation_month_change_nothing_it_decides() -> None:
    data = random_panel(60, 6, seed=7, holes=4)
    formation = 45
    future = {
        name: tuple(
            value if index <= formation or value is None else value + 0.5
            for index, value in enumerate(series)
        )
        for name, series in data.returns.items()
    }
    altered = dataclasses.replace(
        data,
        returns=future,
        market=tuple(v if i <= formation else v - 0.3 for i, v in enumerate(data.market)),
        risk_free=tuple(v if i <= formation else 0.05 for i, v in enumerate(data.risk_free)),
    )
    assert form(altered, formation, FROZEN, 3) == form(data, formation, FROZEN, 3)

    first, last = data.months[36], data.months[59]
    for book in BookName:
        before = run_book(data, holding_formations(data, FROZEN, 3, first, last), book, 0.001)
        after = run_book(altered, holding_formations(altered, FROZEN, 3, first, last), book, 0.001)
        known = [m for m in before if m.month <= data.months[formation]]
        assert known == [m for m in after if m.month <= data.months[formation]]
        assert len(known) == formation - 36 + 1


# --- Holding and costs --------------------------------------------------------------


def naive_book(
    data: IndustryPanel, formations: list, book: BookName, cost_rate: float
) -> list[float]:
    """Hold the book in money: positions drift, the rebalancing pays on what it trades."""
    holdings: dict[str, float] = {}
    cash = 1.0
    nets: list[float] = []
    for formation in formations:
        position = data.months.index(formation.month)
        total = cash + sum(holdings.values())
        target = formation.targets[book]
        traded = sum(
            abs(total * target.get(name, 0.0) - holdings.get(name, 0.0))
            for name in set(target) | set(holdings)
        )
        invested = total - cost_rate * traded
        holdings = {name: invested * weight for name, weight in target.items()}
        cash = invested - sum(holdings.values())
        rate = data.risk_free[position + 1]
        for name in holdings:
            value = data.returns[name][position + 1]
            holdings[name] *= 1.0 + (rate if value is None else value)
        cash *= 1.0 + rate
        nets.append((cash + sum(holdings.values())) / total - 1.0)
    return nets


@pytest.mark.parametrize("book", list(BookName))
def test_the_weight_formula_matches_a_book_held_in_money(book: BookName) -> None:
    data = random_panel(90, 8, seed=8, holes=6)
    formations = list(holding_formations(data, FROZEN, 3, data.months[36], data.months[89]))
    held = run_book(data, formations, book, cost_rate=0.001)
    assert [m.net for m in held] == pytest.approx(
        naive_book(data, formations, book, 0.001), abs=1e-12
    )


def test_the_first_formation_buys_from_cash_and_costs_scale() -> None:
    data = random_panel(40, 5, seed=9)
    formations = holding_formations(data, FROZEN, 2, data.months[36], data.months[39])
    once = run_book(data, formations, BookName.RESIDUAL, cost_rate=0.001)
    twice = run_book(data, formations, BookName.RESIDUAL, cost_rate=0.002)
    assert once[0].turnover == pytest.approx(1.0)
    assert once[0].cost == pytest.approx(0.001)
    assert [m.cost for m in twice] == pytest.approx([2 * m.cost for m in once])
    assert [m.gross for m in twice] == [m.gross for m in once]
    assert all(t.net <= o.net for t, o in zip(twice, once, strict=True))


def test_a_held_industry_without_a_return_earns_the_risk_free_rate() -> None:
    data = random_panel(40, 3, seed=10)
    formed = form(data, 37, FROZEN, held=1)
    (name,) = formed.targets[BookName.RESIDUAL]
    holed = dict(data.returns)
    series = list(holed[name])
    series[38] = None
    holed[name] = tuple(series)
    altered = dataclasses.replace(data, returns=holed)
    (held,) = run_book(altered, [form(altered, 37, FROZEN, 1)], BookName.RESIDUAL, 0.0)
    assert held.missing_held == (name,)
    assert held.gross == pytest.approx(data.risk_free[38])


def test_formations_must_be_consecutive() -> None:
    data = random_panel(42, 3, seed=11)
    formations = [form(data, 36, FROZEN, 1), form(data, 38, FROZEN, 1)]
    with pytest.raises(ValueError, match="consecutive"):
        run_book(data, formations, BookName.RESIDUAL, 0.001)


# --- Statistics and verdict -----------------------------------------------------------


def test_the_sharpe_ratio_is_the_one_the_bootstrap_resamples() -> None:
    generator = np.random.default_rng(12)
    first = list(generator.normal(0.006, 0.04, 240))
    second = list(generator.normal(0.004, 0.05, 240))
    result = paired_stationary_bootstrap(
        excess_curve(first),
        excess_curve(second),
        statistic=PairedStatistic.SHARPE,
        mean_block=12,
        draws=200,
        seed=1,
        level=0.95,
        config=AnalyticsConfig(sessions_per_year=12, risk_free_rate=0.0),
    )
    expected = sharpe_ratio(first, 12) - sharpe_ratio(second, 12)  # type: ignore[operator]
    assert result.estimate == pytest.approx(expected, rel=1e-9)


def test_growth_drawdown_and_active_statistics_by_hand() -> None:
    returns = [0.10, -0.20, 0.05]
    assert compound_annual_growth(returns, 12) == pytest.approx((1.1 * 0.8 * 1.05) ** 4 - 1)
    assert max_drawdown(returns) == pytest.approx(-0.20)
    active = active_statistics([0.02, 0.00, 0.01], [0.01, 0.01, 0.00], 12)
    assert active["active_mean"] == pytest.approx(0.01 / 3 * 12)
    deviation = math.sqrt(
        ((0.01 - 1 / 300) ** 2 + (-0.01 - 1 / 300) ** 2 + (0.01 - 1 / 300) ** 2) / 2
    )
    assert active["tracking_error"] == pytest.approx(deviation * math.sqrt(12))
    assert sharpe_ratio([0.01, 0.01, 0.01], 12) is None


@pytest.mark.parametrize(
    "difference, holm_p, stressed, expected",
    [
        (0.2, 0.01, 0.1, Verdict.SUPPORTED_RETROSPECTIVE),
        (0.2, 0.01, -0.01, Verdict.UNCERTAIN),
        (0.2, 0.06, 0.1, Verdict.UNCERTAIN),
        (0.0, 0.01, 0.1, Verdict.NOT_SUPPORTED),
        (-0.1, 0.01, 0.1, Verdict.NOT_SUPPORTED),
    ],
)
def test_the_frozen_verdict_rule(
    difference: float, holm_p: float, stressed: float, expected: Verdict
) -> None:
    assert verdict(difference, holm_p, stressed, alpha=0.05) is expected


# --- Replaying the archive ------------------------------------------------------------


def zipped(text: str, dataset: KenFrenchDataset) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(f"{dataset.value}.csv", text)
    return buffer.getvalue()


def industry_zip(rows: list[str]) -> bytes:
    header = "," + ",".join(f"I{i}" for i in range(10)) + "\n"
    return zipped(
        "Synthetic\n\nAverage Value Weighted Returns -- Monthly\n" + header + "".join(rows),
        KenFrenchDataset.INDUSTRY_10,
    )


def factor_zip(rows: list[str]) -> bytes:
    return zipped("Preamble\n\n,Mkt-RF,SMB,HML,RF\n" + "".join(rows), KenFrenchDataset.FACTORS)


RETRIEVED = datetime(2026, 11, 7, 16, 1, tzinfo=UTC)


def replay(payload: bytes, dataset: KenFrenchDataset, end: date = date(1926, 8, 1)):
    return replay_monthly_returns(
        payload,
        dataset,
        sha256=hashlib.sha256(payload).hexdigest(),
        retrieved_at_utc=RETRIEVED,
        start=date(1926, 7, 1),
        end=end,
    )


def test_the_archive_is_replayed_into_a_panel_in_fractions() -> None:
    industries = replay(
        industry_zip(
            [
                "192607," + ",".join(["1.5"] * 9) + ",-99.99\n",
                "192608," + ",".join(["-2"] * 10) + "\n",
            ]
        ),
        KenFrenchDataset.INDUSTRY_10,
    )
    factors = replay(
        factor_zip(["192607,2.96,0,0,0.22\n", "192608,2.64,0,0,0.25\n"]), KenFrenchDataset.FACTORS
    )
    built = build_panel(industries, factors)
    assert built.months == (date(1926, 7, 1), date(1926, 8, 1))
    assert built.industries == tuple(f"I{i}" for i in range(10))
    assert built.returns["I0"] == (0.015, -0.02)
    assert built.returns["I9"] == (None, -0.02)
    assert built.market == pytest.approx((0.0318, 0.0289))
    assert built.risk_free == pytest.approx((0.0022, 0.0025))


def test_bytes_that_are_not_the_archived_ones_are_refused() -> None:
    payload = factor_zip(["192607,2.96,0,0,0.22\n", "192608,2.64,0,0,0.25\n"])
    with pytest.raises(ValueError, match="hash"):
        replay_monthly_returns(
            payload,
            KenFrenchDataset.FACTORS,
            sha256="0" * 64,
            retrieved_at_utc=RETRIEVED,
            start=date(1926, 7, 1),
            end=date(1926, 8, 1),
        )


def test_tables_over_other_months_or_without_the_market_are_refused() -> None:
    industries = replay(
        industry_zip(
            ["192607," + ",".join(["1"] * 10) + "\n", "192608," + ",".join(["1"] * 10) + "\n"]
        ),
        KenFrenchDataset.INDUSTRY_10,
    )
    shorter = replay(
        factor_zip(["192607,2.96,0,0,0.22\n", "192608,2.64,0,0,0.25\n"]),
        KenFrenchDataset.FACTORS,
        end=date(1926, 7, 1),
    )
    with pytest.raises(ValueError, match="same months"):
        build_panel(industries, shorter)
    holed = replay(
        factor_zip(["192607,-99.99,0,0,0.22\n", "192608,2.64,0,0,0.25\n"]), KenFrenchDataset.FACTORS
    )
    with pytest.raises(ValueError, match="misses Mkt"):
        build_panel(industries, holed)


def test_a_panel_whose_months_do_not_follow_is_refused() -> None:
    with pytest.raises(ValueError, match="consecutive"):
        IndustryPanel(
            months=(date(2000, 1, 1), date(2000, 3, 1)),
            industries=("A",),
            returns={"A": (0.01, 0.02)},
            market=(0.01, 0.02),
            risk_free=(0.0, 0.0),
        )
