"""Run SA16's long-history study exactly as ``research/SA16/long_history.toml`` froze it.

Run from the repository root, after ``scripts/SA16_acquire_long_history.py``::

    uv run python scripts/SA16_run_long_history.py

It refuses to run unless the checkout is committed (generated output apart)
and every archived file hashes to the committed coverage record,
``research/SA16/long_history_inputs.json``. It performs no network
I/O. It then holds four books over 1975-01 to 2018-07, at declared and
doubled costs: SA16_it2's rule on monthly series, the growth portfolio and
the Nasdaq Composite bought and held, and it2's constant-weight control.

The comparisons follow the frozen inference: a paired stationary bootstrap of
the Sharpe difference against each reference, Holm over the two, and SA16's
criterion. Other block lengths, volatility windows, the uncorrected gold
variance, the regimes and the months SA16 was developed on are reported and
decide nothing.

Outputs, under ``results/SA16/long_history/``: ``study.md``, ``verdict.json``
and ``metrics.csv``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quant_backtester.analytics.config import AnalyticsConfig
from quant_backtester.analytics.uncertainty import (
    PairedStatistic,
    holm_adjusted,
    paired_stationary_bootstrap,
)
from quant_backtester.data.sources.ken_french import KenFrenchDataset, MonthlyReturns
from quant_backtester.data.sources.world_bank import parse_pink_sheet_monthly
from quant_backtester.provenance import git_source_state
from quant_backtester.research.sa16_long_history import (
    GOLD,
    GROWTH,
    BookMonth,
    MonthlyPanel,
    average_changes,
    beats,
    budget_target,
    build_panel,
    fixed_target,
    month_end_changes,
    reading,
    run_book,
)
from quant_backtester.research.sa17_mechanism import (
    compound_annual_growth,
    excess_curve,
    max_drawdown,
    replay_monthly_returns,
    sharpe_ratio,
)

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research" / "SA16" / "long_history.toml"
OUTPUT = ROOT / "results" / "SA16" / "long_history"
CANDIDATE = "SA16_IT2_MONTHLY"
GROWTH_HELD = "GROWTH_BUY_HOLD"
NASDAQ_HELD = "NASDAQ_COMPOSITE_PRICE"
CONTROL = "C1_CONSTANT_TWO_THIRDS"
BOOKS = (CANDIDATE, GROWTH_HELD, NASDAQ_HELD, CONTROL)
COSTS = ("declared", "stressed")
NASDAQ_FILE = "NASDAQCOM.csv"
GOLD_FILE = "CMO-Historical-Data-Monthly.xlsx"


def load_study(path: Path = STUDY) -> dict[str, Any]:
    """Return the frozen study configuration."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def checked_source(output: Path) -> str:
    """Return the commit, refused unless everything but generated output is committed."""
    source = git_source_state(ROOT)
    if source.dirty is None:
        raise SystemExit("refused: the checkout has no recorded commit")
    if source.dirty:
        changed: set[Path] = set()
        for arguments in (
            ["diff", "HEAD", "--no-renames", "--name-only", "-z"],
            ["ls-files", "--others", "--exclude-standard", "-z"],
        ):
            result = subprocess.run(
                ["git", "-C", str(ROOT), *arguments], check=True, capture_output=True
            )
            changed.update(
                (ROOT / name.decode()).resolve() for name in result.stdout.split(b"\0") if name
            )
        if any(not path.is_relative_to(output.resolve()) for path in changed):
            raise SystemExit("refused: commit the design and the code before the run")
    return str(source.git_commit)


def load_panel(
    archive: Path, coverage: Sequence[Mapping[str, Any]], study: Mapping[str, Any]
) -> MonthlyPanel:
    """Replay the archived files, refused unless each hashes to its coverage record."""
    recorded = {entry["file"]: entry for entry in coverage}
    series = study["series"]

    def checked(name: str) -> bytes:
        payload = (archive / name).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != recorded[name]["sha256"]:
            raise ValueError(f"{name}: archived bytes hash to {digest}, not to the record")
        return payload

    def french(dataset: KenFrenchDataset) -> MonthlyReturns:
        entry = recorded[f"{dataset.value}.zip"]
        first, last = entry["first_month"], entry["last_month"]
        return replay_monthly_returns(
            checked(f"{dataset.value}.zip"),
            dataset,
            sha256=entry["sha256"],
            retrieved_at_utc=datetime.fromisoformat(entry["retrieved_at_utc"]),
            start=date(int(first[:4]), int(first[4:]), 1),
            end=date(int(last[:4]), int(last[4:]), 1),
        )

    months, values, _updated = parse_pink_sheet_monthly(
        checked(GOLD_FILE), series["gold_column"], series["gold_unit"]
    )
    nasdaq = month_end_changes(checked(NASDAQ_FILE).decode("utf-8"), series["nasdaq_series"])
    needed = study["strategy"]["volatility_months"]
    needed = max(needed, *study["sensitivities"]["volatility_months"])
    first = study["window"]["first_holding_month"]
    start = date(first.year - (needed + 11) // 12, first.month, 1)
    return build_panel(
        french(KenFrenchDataset[series["growth_dataset"]]),
        series["growth_column"],
        french(KenFrenchDataset.FACTORS),
        average_changes(months, values),
        nasdaq,
        start,
        study["replication"]["last_holding_month"],
    )


def _deviation(values: Sequence[float]) -> float:
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1))


def measures(
    net: Sequence[float], risk_free: Sequence[float], periods: int
) -> dict[str, float | None]:
    """Return CAGR, volatility, Sharpe of excess returns and maximum drawdown."""
    excess = [value - rate for value, rate in zip(net, risk_free, strict=True)]
    return {
        "months": float(len(net)),
        "cagr": compound_annual_growth(net, periods),
        "volatility": _deviation(net) * math.sqrt(periods),
        "sharpe": sharpe_ratio(excess, periods),
        "max_drawdown": max_drawdown(net),
    }


def held_returns(
    panel: MonthlyPanel,
    study: Mapping[str, Any],
    first: date,
    last: date,
    rate: float,
    volatility_months: int | None = None,
    gold_variance_scale: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Hold the four books over a run of months at one cost rate.

    Returns, per book, its net and gross monthly returns and, for the two
    traded books, the records of :func:`run_book`.
    """
    strategy, series = study["strategy"], study["series"]
    target = budget_target(
        panel,
        strategy["volatility_months"] if volatility_months is None else volatility_months,
        strategy["growth_risk_budget"],
        strategy["volatility_floor"],
        strategy["gold_variance_scale"] if gold_variance_scale is None else gold_variance_scale,
        series["periods_per_year"],
    )
    control = fixed_target(
        {GROWTH: study["control"]["growth_weight"], GOLD: study["control"]["gold_weight"]}
    )
    start, stop = panel.position(first), panel.position(last)
    books: dict[str, dict[str, Any]] = {}
    rules: tuple[tuple[str, Callable[[int], Mapping[str, float]]], ...] = (
        (CANDIDATE, target),
        (CONTROL, control),
    )
    for name, rule in rules:
        records = run_book(panel, first, last, rule, strategy["rebalance_band"], rate)
        books[name] = {
            "net": [record.net for record in records],
            "gross": [record.gross for record in records],
            "records": records,
        }
    for name, values in ((GROWTH_HELD, panel.growth), (NASDAQ_HELD, panel.nasdaq)):
        held = list(values[start : stop + 1])
        books[name] = {"net": held, "gross": held, "records": None}
    return books


def book_table(
    books: Mapping[str, Mapping[str, Any]], risk_free: Sequence[float], periods: int
) -> dict[str, dict[str, float | None]]:
    """Return every book's net measures, with gross CAGR and Sharpe and its trading."""
    table: dict[str, dict[str, float | None]] = {}
    for name, book in books.items():
        values = measures(book["net"], risk_free, periods)
        gross = measures(book["gross"], risk_free, periods)
        values["cagr_gross"] = gross["cagr"]
        values["sharpe_gross"] = gross["sharpe"]
        records: Sequence[BookMonth] | None = book["records"]
        if records is not None:
            years = len(records) / periods
            values["trades"] = float(sum(1 for record in records if record.traded))
            values["turnover_per_year"] = math.fsum(r.turnover for r in records) / years
            values["mean_growth_weight"] = math.fsum(r.weights[GROWTH] for r in records) / len(
                records
            )
            values["min_growth_weight"] = min(r.weights[GROWTH] for r in records)
            values["max_growth_weight"] = max(r.weights[GROWTH] for r in records)
        table[name] = values
    return table


def compare(
    candidate: Sequence[float],
    reference: Sequence[float],
    risk_free: Sequence[float],
    inference: Mapping[str, Any],
    mean_block: int,
    periods: int,
) -> dict[str, Any]:
    """Bootstrap the Sharpe difference of excess returns between two books."""

    def excess(values: Sequence[float]) -> list[float]:
        return [value - rate for value, rate in zip(values, risk_free, strict=True)]

    result = paired_stationary_bootstrap(
        excess_curve(excess(candidate)),
        excess_curve(excess(reference)),
        statistic=PairedStatistic[inference["statistic"]],
        mean_block=mean_block,
        draws=inference["draws"],
        seed=inference["seed"],
        level=inference["level"],
        config=AnalyticsConfig(sessions_per_year=periods, risk_free_rate=0.0),
    )
    return dict(result.definition())


def study_report(panel: MonthlyPanel, study: Mapping[str, Any]) -> dict[str, Any]:
    """Run the frozen design and everything it says is reported beside it."""
    periods = study["series"]["periods_per_year"]
    inference = study["inference"]
    window = study["window"]
    first, last = window["first_holding_month"], window["last_holding_month"]
    rate = study["costs"]["declared_rate"]
    rates = {"declared": rate, "stressed": rate * study["costs"]["stress_multiplier"]}

    def risk_free(start: date, end: date) -> list[float]:
        return list(panel.risk_free[panel.position(start) : panel.position(end) + 1])

    free = risk_free(first, last)
    runs = {cost: held_returns(panel, study, first, last, rates[cost]) for cost in COSTS}
    tables = {cost: book_table(runs[cost], free, periods) for cost in COSTS}
    family = list(inference["family"])
    blocks = [inference["mean_block_months"], *inference["sensitivity_mean_block_months"]]
    tests = {
        name: {
            f"block{block}": compare(
                runs["declared"][CANDIDATE]["net"],
                runs["declared"][name]["net"],
                free,
                inference,
                block,
                periods,
            )
            for block in blocks
        }
        for name in family
    }
    primary = f"block{inference['mean_block_months']}"
    holm = holm_adjusted({name: tests[name][primary]["p_value"] for name in family})
    tolerance = inference["max_drawdown_tolerance"]
    readings = {}
    for name in family:
        at = {cost: beats(tables[cost][CANDIDATE], tables[cost][name], tolerance) for cost in COSTS}
        readings[name] = {
            "beats_declared": at["declared"],
            "beats_stressed": at["stressed"],
            "sharpe_difference": tests[name][primary]["estimate"],
            "holm_p": holm[name],
            "reading": reading(
                at["declared"], at["stressed"], holm[name], inference["alpha"]
            ).value,
        }

    def sliced(start: date, end: date) -> dict[str, dict[str, float | None]]:
        low = panel.position(start) - panel.position(first)
        high = panel.position(end) - panel.position(first) + 1
        return {
            name: measures(runs["declared"][name]["net"][low:high], free[low:high], periods)
            for name in BOOKS
        }

    regimes = {
        regime["name"]: sliced(regime["first"], regime["last"]) for regime in study["regimes"]
    }
    sensitivities: dict[str, dict[str, dict[str, float | None]]] = {}
    for months in study["sensitivities"]["volatility_months"]:
        books = held_returns(panel, study, first, last, rate, volatility_months=months)
        sensitivities[f"volatility_months={months}"] = book_table(
            {CANDIDATE: books[CANDIDATE]}, free, periods
        )
    for scale in study["sensitivities"]["gold_variance_scale"]:
        books = held_returns(panel, study, first, last, rate, gold_variance_scale=scale)
        sensitivities[f"gold_variance_scale={scale:g}"] = book_table(
            {CANDIDATE: books[CANDIDATE]}, free, periods
        )
    replication = study["replication"]
    later_first, later_last = replication["first_holding_month"], replication["last_holding_month"]
    later = held_returns(panel, study, later_first, later_last, rate)
    weights = [
        {"month": record.month, "growth": record.weights[GROWTH], "traded": record.traded}
        for record in runs["declared"][CANDIDATE]["records"]
    ]
    return {
        "hypothesis_id": study["hypothesis_id"],
        "window": [first, last],
        "months": len(free),
        "books": tables,
        "tests": tests,
        "holm": holm,
        "readings": readings,
        "regimes": regimes,
        "sensitivities": sensitivities,
        "replication": {
            "window": [later_first, later_last],
            "books": book_table(later, risk_free(later_first, later_last), periods),
        },
        "weights": weights,
    }


def pct(value: float | None, digits: int = 1) -> str:
    """Format a fraction as a percentage."""
    return "—" if value is None else f"{value * 100:.{digits}f} %"


def num(value: float | None, digits: int = 2) -> str:
    """Format a number."""
    return "—" if value is None else f"{value:.{digits}f}"


def _rows(table: Mapping[str, Mapping[str, float | None]], names: Sequence[str]) -> list[str]:
    return [
        f"| {name} | {pct(table[name]['cagr'])} | {pct(table[name]['volatility'])} | "
        f"{num(table[name]['sharpe'])} | {pct(table[name]['max_drawdown'])} |"
        for name in names
    ]


def markdown(report: Mapping[str, Any], study: Mapping[str, Any], commit: str) -> str:
    """Return the factual report of the run."""
    declared, stressed = report["books"]["declared"], report["books"]["stressed"]
    first, last = report["window"]
    inference = study["inference"]
    lines = [
        "# SA16_it2 on a long history (retrospective, monthly, US dollars)",
        "",
        f"Hypothesis `{report['hypothesis_id']}`. Frozen in "
        "[research/SA16/long_history.md](../../../research/SA16/long_history.md) and "
        "[long_history.toml](../../../research/SA16/long_history.toml) before any return was "
        f"computed. Generated by `scripts/SA16_run_long_history.py` at `{commit[:7]}`.",
        "",
        "A test of the rule on research series, not of the funds SA16_it2 trades. Gold is a "
        "monthly average and the Nasdaq Composite has no dividends: see the design.",
        "",
        f"## Out of sample: {first:%Y-%m} to {last:%Y-%m} ({report['months']} months), net",
        "",
        "| Book | Net CAGR | Gross CAGR | Volatility | Net Sharpe | Max drawdown "
        "| Net CAGR x2 | Net Sharpe x2 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in BOOKS:
        one, two = declared[name], stressed[name]
        lines.append(
            f"| {name} | {pct(one['cagr'])} | {pct(one['cagr_gross'])} | "
            f"{pct(one['volatility'])} | {num(one['sharpe'])} | {pct(one['max_drawdown'])} | "
            f"{pct(two['cagr'])} | {num(two['sharpe'])} |"
        )
    lines += [
        "",
        "## Trading (declared costs)",
        "",
        "| Book | Trades | Turnover/yr | Mean growth weight | Min | Max |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in (CANDIDATE, CONTROL):
        one = declared[name]
        lines.append(
            f"| {name} | {one['trades']:.0f} | {num(one['turnover_per_year'])} | "
            f"{pct(one['mean_growth_weight'])} | {pct(one['min_growth_weight'])} | "
            f"{pct(one['max_growth_weight'])} |"
        )
    main = f"block{inference['mean_block_months']}"
    others = [f"block{block}" for block in inference["sensitivity_mean_block_months"]]
    lines += [
        "",
        "## Candidate against each reference (paired stationary bootstrap, Sharpe difference)",
        "",
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
    ]
    for regime, table in report["regimes"].items():
        lines += [
            f"**{regime}**",
            "",
            "| Book | CAGR | Volatility | Sharpe | Max drawdown |",
            "| --- | ---: | ---: | ---: | ---: |",
            *_rows(table, BOOKS),
            "",
        ]
    lines += [
        "## Sensitivities of the candidate (declared costs, decide nothing)",
        "",
        "| Variant | CAGR | Volatility | Sharpe | Max drawdown |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| frozen design | {pct(declared[CANDIDATE]['cagr'])} | "
        f"{pct(declared[CANDIDATE]['volatility'])} | {num(declared[CANDIDATE]['sharpe'])} | "
        f"{pct(declared[CANDIDATE]['max_drawdown'])} |",
    ]
    for variant, table in report["sensitivities"].items():
        one = table[CANDIDATE]
        lines.append(
            f"| {variant} | {pct(one['cagr'])} | {pct(one['volatility'])} | "
            f"{num(one['sharpe'])} | {pct(one['max_drawdown'])} |"
        )
    later = report["replication"]
    lines += [
        "",
        f"## The months SA16 was developed on: {later['window'][0]:%Y-%m} to "
        f"{later['window'][1]:%Y-%m} (not part of the test)",
        "",
        "| Book | CAGR | Volatility | Sharpe | Max drawdown |",
        "| --- | ---: | ---: | ---: | ---: |",
        *_rows(later["books"], BOOKS),
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    output: Path, report: Mapping[str, Any], study: Mapping[str, Any], commit: str
) -> None:
    """Write the report, the verdict and the table of measures."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "study.md").write_text(markdown(report, study, commit), encoding="utf-8")
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
            ("out_of_sample_declared", report["books"]["declared"]),
            ("out_of_sample_stressed", report["books"]["stressed"]),
            ("development_months", report["replication"]["books"]),
        ]
        scopes += [(f"regime_{name}", table) for name, table in report["regimes"].items()]
        scopes += [
            (f"sensitivity_{name}", table) for name, table in report["sensitivities"].items()
        ]
        for scope, table in scopes:
            for book, values in table.items():
                for measure, value in values.items():
                    writer.writerow([scope, book, measure, "" if value is None else repr(value)])
    with (output / "weights.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["month", "growth_weight", "traded"])
        for row in report["weights"]:
            writer.writerow([row["month"], repr(row["growth"]), row["traded"]])


def main(arguments: list[str] | None = None) -> int:
    """Check the frozen inputs, run the study once, then report."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parsed = parser.parse_args(arguments)
    output = parsed.output if parsed.output.is_absolute() else ROOT / parsed.output
    study = load_study()
    commit = checked_source(output)
    archive = ROOT / study["archive"]
    coverage = json.loads((ROOT / study["inputs"]).read_text(encoding="utf-8"))
    panel = load_panel(archive, coverage, study)
    report = study_report(panel, study)
    write_outputs(output, report, study, commit)
    for name, values in report["readings"].items():
        print(f"{name}: {values['reading']}", flush=True)
    print(f"report: {output / 'study.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
