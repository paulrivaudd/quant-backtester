"""Run SA17's mechanism study on Ken French industries, as frozen before any score.

Run under WSL/POSIX from the repository root, on the archive acquired by
``scripts/SA17_acquire_research_inputs.py --ken-french``::

    uv run python scripts/SA17_run_mechanism_study.py
    uv run python scripts/SA17_run_mechanism_study.py --output results/SA17/mechanism_rerun

Every parameter comes from ``research/SA17/mechanism.toml``, frozen in
``research/SA17/protocol.md`` ("Mechanism study: frozen design") before this
script existed. The script replays the archived ZIPs offline, refuses them if
their SHA-256 differs from the archive's ``coverage.json``, and writes into a
new folder:

- ``study.md``, the report;
- ``metrics.csv``, every book's statistics per universe and cost;
- ``verdict.json``, the comparisons, their bootstrap, the verdicts, and the
  provenance (input hashes, the configuration's hash, the commit);
- ``books_<universe>.csv`` and ``weights_<universe>.csv``, the monthly
  returns and holdings (not committed: raw exports).

It refuses to run from a checkout with uncommitted changes, so the commit it
records is the code that produced the numbers. No wall-clock time is written:
the same inputs give the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tomllib
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.uncertainty import (
    PairedStatistic,
    holm_adjusted,
    paired_stationary_bootstrap,
)
from quant_backtester.data.sources.ken_french import KenFrenchDataset, MonthlyReturns
from quant_backtester.provenance import SourceState, SourceStatus, git_source_state
from quant_backtester.research.sa17_mechanism import (
    BookMonth,
    BookName,
    IndustryPanel,
    ScoreWindow,
    active_statistics,
    build_panel,
    compound_annual_growth,
    excess_curve,
    excess_returns,
    holding_formations,
    market_returns,
    max_drawdown,
    replay_monthly_returns,
    run_book,
    sharpe_ratio,
    verdict,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "research" / "SA17" / "mechanism.toml"
OUTPUT = ROOT / "results" / "SA17" / "mechanism"
MARKET = "MARKET"
COSTS = ("declared", "stressed")


def sha256(path: Path) -> str:
    """Return the SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_panels(
    archive: Path, coverage: Sequence[Mapping[str, Any]], universes: Sequence[str]
) -> dict[str, IndustryPanel]:
    """Replay the archived ZIPs and align each industry table with the factors."""
    recorded = {entry["dataset"]: entry for entry in coverage}

    def replay(dataset: KenFrenchDataset) -> MonthlyReturns:
        entry = recorded[dataset.value]
        first, last = entry["first_month"], entry["last_month"]
        return replay_monthly_returns(
            (archive / f"{dataset.value}.zip").read_bytes(),
            dataset,
            sha256=entry["sha256"],
            retrieved_at_utc=datetime.fromisoformat(entry["retrieved_at_utc"]),
            start=date(int(first[:4]), int(first[4:]), 1),
            end=date(int(last[:4]), int(last[4:]), 1),
        )

    factors = replay(KenFrenchDataset.FACTORS)
    return {name: build_panel(replay(KenFrenchDataset[name]), factors) for name in universes}


def book_metrics(
    net: Sequence[float],
    gross: Sequence[float] | None,
    panel: IndustryPanel,
    first: date,
    periods: int,
) -> dict[str, float | None]:
    """Return one book's statistics over a run of holding months."""
    excess = excess_returns(net, panel, first)
    values: dict[str, float | None] = {
        "months": float(len(net)),
        "sharpe_excess": sharpe_ratio(excess, periods),
        "mean_excess": math.fsum(excess) / len(excess) * periods,
        "volatility": _deviation(net) * math.sqrt(periods),
        "cagr": compound_annual_growth(net, periods),
        "max_drawdown": max_drawdown(net),
    }
    if gross is not None:
        values["sharpe_excess_gross"] = sharpe_ratio(excess_returns(gross, panel, first), periods)
        values["cagr_gross"] = compound_annual_growth(gross, periods)
    return values


def _deviation(values: Sequence[float]) -> float:
    """Return the sample standard deviation."""
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1))


def run_universe(
    panel: IndustryPanel, config: Mapping[str, Any], held: int
) -> tuple[dict[str, dict[BookName, tuple[BookMonth, ...]]], list[float], tuple]:
    """Form and hold every book of one universe, at declared and doubled costs."""
    window = ScoreWindow(**config["score"])
    first, last = config["first_holding_month"], config["last_holding_month"]
    formations = holding_formations(panel, window, held, first, last)
    rate = config["costs"]["declared_rate"]
    books = {
        cost: {book: run_book(panel, formations, book, rate * multiplier) for book in BookName}
        for cost, multiplier in zip(COSTS, (1.0, config["costs"]["stress_multiplier"]), strict=True)
    }
    return books, market_returns(panel, first, last), formations


def compare(
    panel: IndustryPanel,
    candidate: Sequence[float],
    control: Sequence[float],
    first: date,
    inference: Mapping[str, Any],
    mean_block: int,
    statistic: PairedStatistic,
) -> dict[str, object]:
    """Bootstrap one difference of excess returns between the candidate and a control."""
    result = paired_stationary_bootstrap(
        excess_curve(excess_returns(candidate, panel, first)),
        excess_curve(excess_returns(control, panel, first)),
        statistic=statistic,
        mean_block=mean_block,
        draws=inference["draws"],
        seed=inference["seed"],
        level=inference["level"],
        config=AnalyticsConfig(sessions_per_year=inference["periods_per_year"], risk_free_rate=0.0),
    )
    return result.definition()


def study(
    archive: Path,
    config: Mapping[str, Any],
    output: Path,
    source: SourceState,
    config_sha256: str,
) -> dict[str, Any]:
    """Run the frozen study and write its outputs into ``output``, a new folder.

    Returns
    -------
    dict[str, Any]
        What ``verdict.json`` holds.
    """
    output.mkdir(parents=True, exist_ok=False)
    coverage_path = archive / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    universes = list(config["universes"])
    panels = load_panels(archive, coverage, universes)
    inference = config["inference"]
    periods = inference["periods_per_year"]
    first, last = config["first_holding_month"], config["last_holding_month"]
    metrics_rows: list[dict[str, object]] = []
    report: dict[str, Any] = {
        "study": "SA17 mechanism study on Ken French industries",
        "hypothesis_id": "sa17_mechanism_ken_french",
        "provenance": {
            **source.definition(),
            "configuration_sha256": config_sha256,
            "archive": str(archive.relative_to(ROOT))
            if archive.is_relative_to(ROOT)
            else str(archive),
            "coverage_sha256": sha256(coverage_path),
            "inputs": [
                {
                    key: entry[key]
                    for key in ("dataset", "sha256", "retrieved_at_utc", "history_basis")
                }
                for entry in coverage
            ],
        },
        "window": {
            "first_holding_month": first.isoformat(),
            "last_holding_month": last.isoformat(),
        },
        "universes": {},
    }
    for name in universes:
        panel = panels[name]
        held = config["universes"][name]["held"]
        role = config["universes"][name]["role"]
        books, market, formations = run_universe(panel, config, held)
        months = [m.month for m in books["declared"][BookName.RESIDUAL]]
        # Raw exports: monthly returns and holdings.
        columns: dict[str, Sequence[object]] = {"month": [m.isoformat() for m in months]}
        for cost in COSTS:
            for book in BookName:
                held_months = books[cost][book]
                columns[f"{book.value}_{cost}_net"] = [m.net for m in held_months]
                columns[f"{book.value}_{cost}_gross"] = [m.gross for m in held_months]
                columns[f"{book.value}_{cost}_turnover"] = [m.turnover for m in held_months]
        columns[MARKET] = market
        columns["RF"] = list(panel.risk_free[panel.position(first) : panel.position(last) + 1])
        pd.DataFrame(columns).to_csv(output / f"books_{name}.csv", index=False)
        pd.DataFrame(
            {
                "month": [m.isoformat() for m in months],
                **{
                    book.value: [";".join(m.weights) for m in books["declared"][book]]
                    for book in (BookName.RESIDUAL, BookName.C1_MOMENTUM_12_1)
                },
                "eligible": [len(f.eligible) for f in formations],
                "refused_fits": [";".join(f.refused_fits) for f in formations],
            }
        ).to_csv(output / f"weights_{name}.csv", index=False)

        # Statistics of every book, over the window and per regime.
        per_book: dict[str, Any] = {}
        for cost in COSTS:
            for book in BookName:
                held_months = books[cost][book]
                net = [m.net for m in held_months]
                gross = [m.gross for m in held_months]
                values = book_metrics(net, gross, panel, first, periods)
                values["turnover_per_year"] = (
                    math.fsum(m.turnover for m in held_months) / len(held_months) * periods
                )
                values["cost_per_year"] = (
                    math.fsum(m.cost for m in held_months) / len(held_months) * periods
                )
                values["months_at_risk_free"] = float(sum(1 for m in held_months if not m.weights))
                values["missing_held_returns"] = float(
                    sum(len(m.missing_held) for m in held_months)
                )
                per_book[f"{book.value}/{cost}"] = values
                metrics_rows.append(
                    {
                        "universe": name,
                        "book": book.value,
                        "costs": cost,
                        "period": "window",
                        **values,
                    }
                )
        market_values = book_metrics(market, None, panel, first, periods)
        per_book[f"{MARKET}/none"] = market_values
        metrics_rows.append(
            {"universe": name, "book": MARKET, "costs": "none", "period": "window", **market_values}
        )
        regimes: dict[str, Any] = {}
        for regime in config["regimes"]:
            start = months.index(regime["first"])
            stop = months.index(regime["last"]) + 1
            regime_values: dict[str, Any] = {}
            for book in BookName:
                held_months = books["declared"][book][start:stop]
                regime_values[book.value] = book_metrics(
                    [m.net for m in held_months], None, panel, regime["first"], periods
                )
                metrics_rows.append(
                    {
                        "universe": name,
                        "book": book.value,
                        "costs": "declared",
                        "period": regime["name"],
                        **regime_values[book.value],
                    }
                )
            regime_values[MARKET] = book_metrics(
                market[start:stop], None, panel, regime["first"], periods
            )
            regimes[regime["name"]] = regime_values

        # The comparisons of the frozen family, and the market as description.
        candidate = {cost: [m.net for m in books[cost][BookName.RESIDUAL]] for cost in COSTS}
        controls = {
            cost: {
                book.value: [m.net for m in books[cost][book]]
                for book in (BookName.C1_MOMENTUM_12_1, BookName.C2_EQUAL_WEIGHT)
            }
            for cost in COSTS
        }
        comparisons: dict[str, Any] = {}
        for control in inference["family"]:
            difference = {}
            for cost in COSTS:
                a = sharpe_ratio(excess_returns(candidate[cost], panel, first), periods)
                b = sharpe_ratio(excess_returns(controls[cost][control], panel, first), periods)
                difference[cost] = None if a is None or b is None else a - b
            bootstraps = {
                f"{statistic.value}/block{block}": compare(
                    panel,
                    candidate["declared"],
                    controls["declared"][control],
                    first,
                    inference,
                    block,
                    statistic,
                )
                for block in (
                    inference["mean_block_months"],
                    *inference["sensitivity_mean_block_months"],
                )
                for statistic in (PairedStatistic.SHARPE, PairedStatistic.MEAN_RETURN)
            }
            comparisons[control] = {
                "sharpe_difference": difference,
                "active": {
                    cost: active_statistics(candidate[cost], controls[cost][control], periods)
                    for cost in COSTS
                },
                "bootstrap": bootstraps,
            }
        primary = f"{PairedStatistic.SHARPE.value}/block{inference['mean_block_months']}"
        adjusted = holm_adjusted(
            {
                control: comparisons[control]["bootstrap"][primary]["p_value"]
                for control in inference["family"]
            }
        )
        for control in inference["family"]:
            comparisons[control]["holm_p_value"] = adjusted[control]
            if role == "primary":
                comparisons[control]["verdict"] = verdict(
                    comparisons[control]["sharpe_difference"]["declared"],
                    adjusted[control],
                    comparisons[control]["sharpe_difference"]["stressed"],
                    inference["alpha"],
                ).value
        comparisons[MARKET] = {
            "description_only": True,
            "active": active_statistics(candidate["declared"], market, periods),
        }
        report["universes"][name] = {
            "role": role,
            "held": held,
            "industries": len(panel.industries),
            "formations": len(formations),
            "eligible_min": min(len(f.eligible) for f in formations),
            "eligible_max": max(len(f.eligible) for f in formations),
            "refused_fits": sum(len(f.refused_fits) for f in formations),
            "books": per_book,
            "regimes": regimes,
            "comparisons": comparisons,
        }
    pd.DataFrame(metrics_rows).to_csv(output / "metrics.csv", index=False)
    (output / "verdict.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "study.md").write_text(markdown(report, config), encoding="utf-8")
    return report


def number(value: float | None, digits: int = 2, percent: bool = False) -> str:
    """Format a statistic for the report; ``n/a`` when it does not exist."""
    if value is None:
        return "n/a"
    return f"{value * 100:.{digits}f}%" if percent else f"{value:.{digits}f}"


def markdown(report: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    """Write the report from what ``verdict.json`` holds."""
    inference = config["inference"]
    primary = f"SHARPE/block{inference['mean_block_months']}"
    lines = [
        "# SA17 — mechanism study on Ken French industries",
        "",
        "Run from the design frozen in [protocol.md](../../../research/SA17/protocol.md)",
        '("Mechanism study: frozen design") and',
        "[mechanism.toml](../../../research/SA17/mechanism.toml), committed before any",
        "score was computed on these files. Retrospective replication on heavily",
        "studied research portfolios: not an executable ETF result, not a discovery.",
        "",
        f"- Commit: `{report['provenance']['git_commit']}`"
        f" ({report['provenance']['source_state']}); configuration sha256"
        f" `{report['provenance']['configuration_sha256'][:16]}…`",
        f"- Holding months: {report['window']['first_holding_month'][:7]} to"
        f" {report['window']['last_holding_month'][:7]}",
        f"- Costs: {config['costs']['declared_rate'] * 1e4:.0f} bp one way (declared),"
        f" x{config['costs']['stress_multiplier']:g} (stressed); hypothetical",
        f"- Inference: paired stationary bootstrap of monthly excess returns, mean block"
        f" {inference['mean_block_months']} months, {inference['draws']:,} draws,"
        f" seed {inference['seed']}, {inference['level']:.0%} percentile intervals;"
        " Holm within {vs C1, vs C2}",
        "",
    ]
    primary_universe = next(
        name for name, values in report["universes"].items() if values["role"] == "primary"
    )
    lines += ["## Verdicts", "", "| Comparison | Question | Verdict |", "| --- | --- | --- |"]
    questions = {
        "C1_MOMENTUM_12_1": "Does the market adjustment beat plain 12-1 momentum?",
        "C2_EQUAL_WEIGHT": "Does the selection beat holding every industry?",
    }
    for control in inference["family"]:
        verdict_value = report["universes"][primary_universe]["comparisons"][control]["verdict"]
        lines.append(f"| RESIDUAL vs {control} | {questions[control]} | **{verdict_value}** |")
    lines.append("")
    lines.append(
        f"Read on {primary_universe} at declared costs. Everything below that is not this"
        " table is reported in full and changes no verdict."
    )
    lines.append("")
    for name, values in report["universes"].items():
        lines += [
            f"## {name} ({values['role']}, top {values['held']} of {values['industries']})",
            "",
            f"{values['formations']} formations; eligible industries per month"
            f" {values['eligible_min']} to {values['eligible_max']}; fits refused"
            f" {values['refused_fits']}.",
            "",
            "| Book | Costs | Sharpe (excess) | Sharpe gross | CAGR | CAGR gross | Vol | Max DD"
            " | Turnover/yr | Cost/yr | Months at RF | Missing held |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for key, book in values["books"].items():
            label, cost = key.split("/")
            lines.append(
                f"| {label} | {cost} | {number(book['sharpe_excess'])}"
                f" | {number(book.get('sharpe_excess_gross'))}"
                f" | {number(book['cagr'], percent=True)}"
                f" | {number(book.get('cagr_gross'), percent=True)}"
                f" | {number(book['volatility'], percent=True)}"
                f" | {number(book['max_drawdown'], percent=True)}"
                f" | {number(book.get('turnover_per_year'))}"
                f" | {number(book.get('cost_per_year'), percent=True)}"
                f" | {number(book.get('months_at_risk_free'), 0)}"
                f" | {number(book.get('missing_held_returns'), 0)} |"
            )
        lines += [
            "",
            "### The candidate against its controls (declared costs)",
            "",
            "| Control | Sharpe diff | 95% interval | p | Holm p | Sharpe diff x2 | Active mean"
            " | Tracking error | IR |" + (" Verdict |" if values["role"] == "primary" else ""),
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"
            + (" --- |" if values["role"] == "primary" else ""),
        ]
        for control in inference["family"]:
            comparison = values["comparisons"][control]
            boot = comparison["bootstrap"][primary]
            active = comparison["active"]["declared"]
            lines.append(
                f"| {control} | {number(boot['estimate'], 3)}"
                f" | [{number(boot['low'], 3)}, {number(boot['high'], 3)}]"
                f" | {number(boot['p_value'], 4)} | {number(comparison['holm_p_value'], 4)}"
                f" | {number(comparison['sharpe_difference']['stressed'], 3)}"
                f" | {number(active['active_mean'], percent=True)}"
                f" | {number(active['tracking_error'], percent=True)}"
                f" | {number(active['information_ratio'])} |"
                + (f" {comparison['verdict']} |" if values["role"] == "primary" else "")
            )
        market = values["comparisons"][MARKET]["active"]
        lines += [
            f"| {MARKET} (description) | | | | | | {number(market['active_mean'], percent=True)}"
            f" | {number(market['tracking_error'], percent=True)}"
            f" | {number(market['information_ratio'])} |"
            + (" — |" if values["role"] == "primary" else ""),
            "",
            "### Sensitivities, never selected",
            "",
            "| Control | Statistic | Mean block | Estimate | 95% interval | p |",
            "| --- | --- | ---: | ---: | --- | ---: |",
        ]
        for control in inference["family"]:
            for key, boot in values["comparisons"][control]["bootstrap"].items():
                statistic, block = key.split("/block")
                percent = statistic == "MEAN_RETURN"
                lines.append(
                    f"| {control} | {statistic} | {block}"
                    f" | {number(boot['estimate'], 3, percent)}"
                    f" | [{number(boot['low'], 3, percent)}, {number(boot['high'], 3, percent)}]"
                    f" | {number(boot['p_value'], 4)} |"
                )
        lines += [
            "",
            "### Regimes (declared costs, descriptive)",
            "",
            "| Regime | Book | Sharpe (excess) | CAGR | Max DD |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for regime, books in values["regimes"].items():
            for book, stats in books.items():
                lines.append(
                    f"| {regime} | {book} | {number(stats['sharpe_excess'])}"
                    f" | {number(stats['cagr'], percent=True)}"
                    f" | {number(stats['max_drawdown'], percent=True)} |"
                )
        lines.append("")
    lines += [
        "## What this does not show",
        "",
        "- These are SIC research portfolios of the broad CRSP market, restated, not",
        "  point-in-time and not tradable. The costs are a declared hypothesis.",
        "- Industry momentum and residual momentum are published; the 10 and 49",
        "  industries are among the most used series in finance. This tests whether",
        "  SA17's score behaves as the literature says on this data, not a new edge.",
        "- It tests monthly selection only, not SA17's daily volatility sizing, and",
        "  says nothing about the executable ETF book, which has its own gates.",
        "",
    ]
    return "\n".join(lines)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the study from the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parsed = parser.parse_args(arguments)
    source = git_source_state(ROOT)
    if source.status is not SourceStatus.CLEAN:
        print(
            f"refused: the checkout is {source.status.value}; commit first so the recorded"
            " commit is the code that ran",
            file=sys.stderr,
        )
        return 2
    with CONFIG.open("rb") as stream:
        config = tomllib.load(stream)
    output = parsed.output if parsed.output.is_absolute() else ROOT / parsed.output
    report = study(ROOT / config["archive"], config, output, source, sha256(CONFIG))
    for name, values in report["universes"].items():
        for control, comparison in values["comparisons"].items():
            if "verdict" in comparison:
                print(f"{name} RESIDUAL vs {control}: {comparison['verdict']}")
    print(f"written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
