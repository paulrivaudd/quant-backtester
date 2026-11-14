"""Run SA16's levered long-history study as ``research/SA16/levered_long_history.toml`` froze it.

Run from the repository root, after ``scripts/SA16_acquire_long_history.py``::

    uv run python scripts/SA16_run_levered_long_history.py

The series, the window, the weights, the costs and the inference are those of
``scripts/SA16_run_long_history.py`` and its design. This adds one book: the
same weights held at a leverage that matches the book's volatility to its
growth asset's, month by month, the loan paying the Treasury bill plus a
declared spread. The stressed run doubles the trading cost and the spread.

It refuses an uncommitted checkout and archived files that do not hash to the
committed record, and performs no network I/O.

Outputs, under ``results/SA16/levered_long_history/``: ``study.md``,
``verdict.json`` and ``metrics.csv``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import tomllib
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from SA16_run_long_history import (  # noqa: E402
    CANDIDATE,
    GROWTH_HELD,
    NASDAQ_HELD,
    checked_source,
    compare,
    held_returns,
    load_panel,
    measures,
    num,
    pct,
)

from quant_backtester.analytics.uncertainty import holm_adjusted  # noqa: E402
from quant_backtester.research.sa16_long_history import (  # noqa: E402
    LeveredMonth,
    MonthlyPanel,
    beats,
    budget_target,
    matched_leverage,
    reading,
    run_levered_book,
)

DESIGN = ROOT / "research" / "SA16" / "levered_long_history.toml"
OUTPUT = ROOT / "results" / "SA16" / "levered_long_history"
LEVERED = "SA16_IT2_LEVERED"
BOOKS = (LEVERED, CANDIDATE, GROWTH_HELD, NASDAQ_HELD)
COSTS = ("declared", "stressed")
RULE = "MATCH_GROWTH_VOLATILITY"


def load_designs(path: Path = DESIGN) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the levered design and the base design it names."""
    with path.open("rb") as stream:
        design = tomllib.load(stream)
    with (ROOT / design["base"]).open("rb") as stream:
        base = tomllib.load(stream)
    if design["leverage"]["rule"] != RULE:
        raise ValueError(f"the only leverage rule written is {RULE}")
    return design, base


def levered_records(
    panel: MonthlyPanel,
    base: Mapping[str, Any],
    first: date,
    last: date,
    cost_rate: float,
    cap: float,
    annual_spread: float,
) -> list[LeveredMonth]:
    """Hold the base design's weights at the matched leverage over a run of months."""
    strategy, periods = base["strategy"], base["series"]["periods_per_year"]
    target = budget_target(
        panel,
        strategy["volatility_months"],
        strategy["growth_risk_budget"],
        strategy["volatility_floor"],
        strategy["gold_variance_scale"],
        periods,
    )
    leverage = matched_leverage(
        panel, strategy["volatility_months"], strategy["gold_variance_scale"], cap
    )
    return run_levered_book(
        panel,
        first,
        last,
        target,
        leverage,
        strategy["rebalance_band"],
        cost_rate,
        annual_spread / periods,
    )


def levered_measures(
    records: Sequence[LeveredMonth], risk_free: Sequence[float], periods: int, cap: float
) -> dict[str, float | None]:
    """Return a levered book's net and gross measures, its trading and its leverage."""
    values = measures([record.net for record in records], risk_free, periods)
    gross = measures([record.gross for record in records], risk_free, periods)
    held = [math.fsum(record.exposures.values()) for record in records]
    values.update(
        {
            "cagr_gross": gross["cagr"],
            "sharpe_gross": gross["sharpe"],
            "trades": float(sum(1 for record in records if record.traded)),
            "turnover_per_year": math.fsum(r.turnover for r in records) / (len(records) / periods),
            "mean_leverage": math.fsum(held) / len(held),
            "min_leverage": min(held),
            "max_leverage": max(held),
            "share_at_cap": sum(1 for r in records if r.leverage >= cap) / len(records),
            "share_below_one": sum(1 for r in records if r.leverage < 1.0) / len(records),
        }
    )
    return values


def study_report(
    panel: MonthlyPanel, design: Mapping[str, Any], base: Mapping[str, Any]
) -> dict[str, Any]:
    """Run the frozen levered design and what it says is reported beside it."""
    periods = base["series"]["periods_per_year"]
    inference, leverage = base["inference"], design["leverage"]
    first = base["window"]["first_holding_month"]
    last = base["window"]["last_holding_month"]
    low, high = panel.position(first), panel.position(last) + 1
    free = list(panel.risk_free[low:high])
    stress = base["costs"]["stress_multiplier"]
    rates = {
        "declared": (base["costs"]["declared_rate"], leverage["borrowing_spread"]),
        "stressed": (
            base["costs"]["declared_rate"] * stress,
            leverage["borrowing_spread"] * leverage["stress_multiplier"],
        ),
    }
    tables: dict[str, dict[str, dict[str, float | None]]] = {}
    nets: dict[str, dict[str, list[float]]] = {}
    for cost in COSTS:
        rate, spread = rates[cost]
        records = levered_records(panel, base, first, last, rate, leverage["cap"], spread)
        others = held_returns(panel, base, first, last, rate)
        nets[cost] = {LEVERED: [record.net for record in records]}
        tables[cost] = {LEVERED: levered_measures(records, free, periods, leverage["cap"])}
        for name in (CANDIDATE, GROWTH_HELD, NASDAQ_HELD):
            nets[cost][name] = others[name]["net"]
            tables[cost][name] = measures(others[name]["net"], free, periods)
    family = list(inference["family"])
    blocks = [inference["mean_block_months"], *inference["sensitivity_mean_block_months"]]
    tests = {
        name: {
            f"block{block}": compare(
                nets["declared"][LEVERED], nets["declared"][name], free, inference, block, periods
            )
            for block in blocks
        }
        for name in family
    }
    primary = f"block{inference['mean_block_months']}"
    holm = holm_adjusted({name: tests[name][primary]["p_value"] for name in family})
    readings = {}
    for name in family:
        at = {
            cost: beats(
                tables[cost][LEVERED], tables[cost][name], inference["max_drawdown_tolerance"]
            )
            for cost in COSTS
        }
        readings[name] = {
            "beats_declared": at["declared"],
            "beats_stressed": at["stressed"],
            "sharpe_difference": tests[name][primary]["estimate"],
            "holm_p": holm[name],
            "reading": reading(
                at["declared"], at["stressed"], holm[name], inference["alpha"]
            ).value,
        }
    regimes = {}
    for regime in base["regimes"]:
        start = panel.position(regime["first"]) - low
        stop = panel.position(regime["last"]) - low + 1
        regimes[regime["name"]] = {
            name: measures(nets["declared"][name][start:stop], free[start:stop], periods)
            for name in BOOKS
        }
    rate, spread = rates["declared"]
    sensitivities = {}
    for cap in design["sensitivities"]["cap"]:
        records = levered_records(panel, base, first, last, rate, cap, spread)
        sensitivities[f"cap={cap:g}"] = levered_measures(records, free, periods, cap)
    for other in design["sensitivities"]["borrowing_spread"]:
        records = levered_records(panel, base, first, last, rate, leverage["cap"], other)
        sensitivities[f"borrowing_spread={other:g}"] = levered_measures(
            records, free, periods, leverage["cap"]
        )
    return {
        "hypothesis_id": design["hypothesis_id"],
        "window": [first, last],
        "months": len(free),
        "books": tables,
        "tests": tests,
        "holm": holm,
        "readings": readings,
        "regimes": regimes,
        "sensitivities": sensitivities,
    }


def markdown(
    report: Mapping[str, Any], design: Mapping[str, Any], base: Mapping[str, Any], commit: str
) -> str:
    """Return the factual report of the run."""
    declared, stressed = report["books"]["declared"], report["books"]["stressed"]
    first, last = report["window"]
    inference, leverage = base["inference"], design["leverage"]
    lines = [
        "# SA16_it2's rule with leverage, on the long history (retrospective)",
        "",
        f"Hypothesis `{report['hypothesis_id']}`. Frozen in "
        "[research/SA16/levered_long_history.md]"
        "(../../../research/SA16/levered_long_history.md) before any levered return was "
        f"computed. Generated by `scripts/SA16_run_levered_long_history.py` at `{commit[:7]}`.",
        "",
        "**Not a blind test**: the same months were read once for the unlevered rule. Margin "
        "calls within a month are not modelled. Gold is a monthly average and the Nasdaq "
        "Composite has no dividends.",
        "",
        f"Leverage: the growth asset's volatility over the book's, at most {leverage['cap']:g}; "
        f"the loan pays the Treasury bill plus {leverage['borrowing_spread'] * 100:g} % a year.",
        "",
        f"## {first:%Y-%m} to {last:%Y-%m} ({report['months']} months), net",
        "",
        "| Book | Net CAGR | Volatility | Net Sharpe | Max drawdown | Net CAGR x2 "
        "| Net Sharpe x2 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in BOOKS:
        one, two = declared[name], stressed[name]
        lines.append(
            f"| {name} | {pct(one['cagr'])} | {pct(one['volatility'])} | {num(one['sharpe'])} | "
            f"{pct(one['max_drawdown'])} | {pct(two['cagr'])} | {num(two['sharpe'])} |"
        )
    one = declared[LEVERED]
    lines += [
        "",
        "x2 doubles the trading cost and the loan's spread.",
        "",
        f"Levered book: gross CAGR {pct(one['cagr_gross'])} before trading costs; "
        f"{one['trades']:.0f} trades, turnover {num(one['turnover_per_year'])} a year. "
        f"Leverage held: mean {num(one['mean_leverage'])}, from {num(one['min_leverage'])} to "
        f"{num(one['max_leverage'])}; asked at the cap in {pct(one['share_at_cap'])} of months, "
        f"below one in {pct(one['share_below_one'])}.",
        "",
        "## Levered book against each reference (paired stationary bootstrap, Sharpe difference)",
        "",
    ]
    main = f"block{inference['mean_block_months']}"
    others = [f"block{block}" for block in inference["sensitivity_mean_block_months"]]
    lines += [
        f"| Against | Sharpe diff | {inference['level'] * 100:g} % interval | p | Holm p | "
        + "".join(f"{key} interval | " for key in others)
        + "Beats | Beats x2 | Reading |",
        "| --- | ---: | --- | ---: | ---: | " + "--- | " * len(others) + "--- | --- | --- |",
    ]
    for name, values in report["readings"].items():
        test = report["tests"][name]
        intervals = "".join(
            f"[{num(test[key]['low'], 3)}, {num(test[key]['high'], 3)}] | " for key in others
        )
        lines.append(
            f"| {name} | {num(test[main]['estimate'], 3)} | "
            f"[{num(test[main]['low'], 3)}, {num(test[main]['high'], 3)}] | "
            f"{num(test[main]['p_value'], 3)} | {num(values['holm_p'], 3)} | {intervals}"
            f"{values['beats_declared']} | {values['beats_stressed']} | "
            f"**{values['reading']}** |"
        )
    lines += [
        "",
        '"Beats" is SA16\'s criterion: net CAGR and net Sharpe both higher, maximum drawdown at '
        "most 2 points deeper.",
        "",
        "## Regimes (declared costs, descriptive)",
        "",
        "| Period | " + " | ".join(f"{name} CAGR | {name} max DD" for name in BOOKS) + " |",
        "| --- | " + " | ".join("---: | ---:" for _ in BOOKS) + " |",
    ]
    for regime, table in report["regimes"].items():
        cells = " | ".join(
            f"{pct(table[name]['cagr'])} | {pct(table[name]['max_drawdown'])}" for name in BOOKS
        )
        lines.append(f"| {regime} | {cells} |")
    lines += [
        "",
        "## Sensitivities of the levered book (declared costs, decide nothing)",
        "",
        "| Variant | CAGR | Volatility | Sharpe | Max drawdown | Mean leverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| frozen design | {pct(one['cagr'])} | {pct(one['volatility'])} | "
        f"{num(one['sharpe'])} | {pct(one['max_drawdown'])} | {num(one['mean_leverage'])} |",
    ]
    for variant, values in report["sensitivities"].items():
        lines.append(
            f"| {variant} | {pct(values['cagr'])} | {pct(values['volatility'])} | "
            f"{num(values['sharpe'])} | {pct(values['max_drawdown'])} | "
            f"{num(values['mean_leverage'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    output: Path,
    report: Mapping[str, Any],
    design: Mapping[str, Any],
    base: Mapping[str, Any],
    commit: str,
) -> None:
    """Write the report, the verdict and the table of measures."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "study.md").write_text(markdown(report, design, base, commit), encoding="utf-8")
    verdict = {
        "hypothesis_id": report["hypothesis_id"],
        "commit": commit,
        "window": report["window"],
        "months": report["months"],
        "readings": report["readings"],
        "holm": report["holm"],
        "tests": report["tests"],
    }
    (output / "verdict.json").write_text(
        json.dumps(verdict, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8"
    )
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["scope", "book", "measure", "value"])
        scopes: list[tuple[str, Mapping[str, Mapping[str, float | None]]]] = [
            ("declared", report["books"]["declared"]),
            ("stressed", report["books"]["stressed"]),
            ("sensitivities", report["sensitivities"]),
        ]
        scopes += [(f"regime_{name}", table) for name, table in report["regimes"].items()]
        for scope, table in scopes:
            for book, values in table.items():
                for measure, value in values.items():
                    writer.writerow([scope, book, measure, "" if value is None else repr(value)])


def main(arguments: list[str] | None = None) -> int:
    """Check the frozen inputs, run the levered study once, then report."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parsed = parser.parse_args(arguments)
    output = parsed.output if parsed.output.is_absolute() else ROOT / parsed.output
    design, base = load_designs()
    commit = checked_source(output)
    archive = ROOT / base["archive"]
    coverage = json.loads((ROOT / base["inputs"]).read_text(encoding="utf-8"))
    panel = load_panel(archive, coverage, base)
    report = study_report(panel, design, base)
    write_outputs(output, report, design, base, commit)
    for name, values in report["readings"].items():
        print(f"{name}: {values['reading']}", flush=True)
    print(f"report: {output / 'study.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
