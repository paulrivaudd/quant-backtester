"""Run SA18's trend-filter study exactly as ``research/SA18/trend_long_history.toml`` froze it.

Run from the repository root, on the archive ``scripts/SA16_acquire_long_history.py``
wrote::

    uv run python scripts/SA18_run_trend_long_history.py

It refuses to run unless the checkout is committed (generated output apart)
and every archived file it reads hashes to the committed coverage record,
``research/SA16/long_history_inputs.json``. It performs no network I/O.

One book is added to the two references of SA16's long-history tests: the
growth portfolio held over a month when its total-return level ended the
month before strictly above the simple average of its last month-end levels,
the one-month Treasury bill otherwise. Declared and doubled costs.

The comparisons follow the frozen inference: a paired stationary bootstrap of
the Sharpe difference against each reference, Holm over the two, and SA16's
criterion. Other block lengths, other averages, the signal read on the Nasdaq
Composite, the regimes, and the months before and after the test window are
reported and decide nothing.

Outputs, under ``results/SA18/trend_long_history/``: ``study.md``,
``verdict.json``, ``metrics.csv`` and ``positions.csv``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from SA16_run_long_history import (  # noqa: E402
    GROWTH_HELD,
    NASDAQ_FILE,
    NASDAQ_HELD,
    checked_bytes,
    checked_source,
    compare,
    measures,
    num,
    pct,
    record_month,
    replay_french,
)

from quant_backtester.analytics.uncertainty import holm_adjusted  # noqa: E402
from quant_backtester.data.sources.ken_french import KenFrenchDataset, MonthlyReturns  # noqa: E402
from quant_backtester.research.sa16_long_history import (  # noqa: E402
    beats,
    month_end_changes,
    reading,
)
from quant_backtester.research.sa18_trend import (  # noqa: E402
    SwitchMonth,
    above_average,
    levels,
    run_switch_book,
)

STUDY = ROOT / "research" / "SA18" / "trend_long_history.toml"
OUTPUT = ROOT / "results" / "SA18" / "trend_long_history"
CANDIDATE = "SA18_TREND_FILTER"
BOOKS = (CANDIDATE, GROWTH_HELD, NASDAQ_HELD)
COSTS = ("declared", "stressed")
RULE = "LEVEL_ABOVE_SIMPLE_AVERAGE"
GROWTH_SIGNAL = "GROWTH_TOTAL_RETURN"
NASDAQ_SIGNAL = "NASDAQ_PRICE"


@dataclass(frozen=True, slots=True)
class TrendSeries:
    """The monthly series of the study, by the month they describe.

    Attributes
    ----------
    months : tuple[date, ...]
        First days of consecutive months, from the first month of the French
        tables to the last month the study reports.
    growth : tuple[float, ...]
        Total return of the growth portfolio over each month, as a fraction.
    risk_free : tuple[float, ...]
        One-month Treasury bill return of each month.
    nasdaq : Mapping[date, float]
        Change of the Nasdaq Composite between the last closes of the month
        before and of the month, dividends excluded; only the months it has.
    """

    months: tuple[date, ...]
    growth: tuple[float, ...]
    risk_free: tuple[float, ...]
    nasdaq: Mapping[date, float]

    def span(self, first: date, last: date) -> slice:
        """Return the slice of the months from ``first`` to ``last``, inclusive."""
        return slice(self.months.index(first), self.months.index(last) + 1)


def load_study(path: Path = STUDY) -> dict[str, Any]:
    """Return the frozen study configuration, refused if it names another rule."""
    with path.open("rb") as stream:
        study = tomllib.load(stream)
    strategy = study["strategy"]
    if strategy["rule"] != RULE or strategy["signal"] != GROWTH_SIGNAL:
        raise ValueError(f"the only rule written is {RULE} on {GROWTH_SIGNAL}")
    if set(study["sensitivities"]["signal"]) - {NASDAQ_SIGNAL}:
        raise ValueError(f"the only other signal written is {NASDAQ_SIGNAL}")
    return study


def _next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def load_series(
    archive: Path, coverage: Sequence[Mapping[str, Any]], study: Mapping[str, Any]
) -> TrendSeries:
    """Replay the archived files, refused unless each hashes to its coverage record.

    Raises
    ------
    ValueError
        If a file's bytes are not the recorded ones, or the growth portfolio
        or the bill has no value for a month up to the last one reported: a
        hole is refused, never filled.
    """
    recorded = {entry["file"]: entry for entry in coverage}
    series = study["series"]

    def french(dataset: KenFrenchDataset) -> tuple[MonthlyReturns, date]:
        table = replay_french(archive, recorded, dataset)
        return table, record_month(recorded[f"{dataset.value}.zip"]["first_month"])

    def column(table: MonthlyReturns, name: str) -> dict[date, float | None]:
        if name not in table.columns:
            raise ValueError(f"the table has no column {name!r}")
        index = table.columns.index(name)
        return {month: row[index] for month, row in zip(table.months, table.values, strict=True)}

    industries, first_industry = french(KenFrenchDataset[series["growth_dataset"]])
    factors, first_factor = french(KenFrenchDataset.FACTORS)
    sources = {
        "growth": column(industries, series["growth_column"]),
        "risk_free": column(factors, "RF"),
    }
    months, values = [], {name: [] for name in sources}
    month = max(first_industry, first_factor)
    while month <= study["later"]["last_holding_month"]:
        months.append(month)
        for name, source in sources.items():
            value = source.get(month)
            if value is None:
                raise ValueError(f"{name} has no value for {month:%Y-%m}")
            values[name].append(value)
        month = _next_month(month)
    nasdaq = month_end_changes(
        checked_bytes(archive, recorded, NASDAQ_FILE).decode("utf-8"), series["nasdaq_series"]
    )
    return TrendSeries(tuple(months), tuple(values["growth"]), tuple(values["risk_free"]), nasdaq)


def nasdaq_returns(series: TrendSeries, first: date, last: date) -> list[float]:
    """Return the Nasdaq Composite's change of every month of a run, refusing a hole."""
    held = []
    for month in series.months[series.span(first, last)]:
        if month not in series.nasdaq:
            raise ValueError(f"the Nasdaq Composite has no change for {month:%Y-%m}")
        held.append(series.nasdaq[month])
    return held


def trend_records(
    series: TrendSeries,
    average_months: int,
    signal: str,
    first: date,
    last: date,
    rate: float,
) -> list[SwitchMonth]:
    """Hold the growth portfolio or the bill over a run of months, by one signal.

    ``GROWTH_TOTAL_RETURN`` reads the growth portfolio's compounded level from
    the first month of the series. ``NASDAQ_PRICE`` reads the Nasdaq
    Composite's month-end closes from its first change, on the consecutive
    months it has up to ``last``; the growth portfolio is still what is held.
    """
    stop = series.months.index(last) + 1
    if signal == GROWTH_SIGNAL:
        low = 0
        changes: Sequence[float] = series.growth[:stop]
    elif signal == NASDAQ_SIGNAL:
        low = series.months.index(min(series.nasdaq))
        changes = nasdaq_returns(series, series.months[low], last)
    else:
        raise ValueError(f"unknown signal {signal!r}")
    return run_switch_book(
        series.months[low:stop],
        series.growth[low:stop],
        series.risk_free[low:stop],
        above_average(levels(changes), average_months),
        first,
        last,
        rate,
    )


def candidate_measures(
    records: Sequence[SwitchMonth], risk_free: Sequence[float], periods: int
) -> dict[str, float | None]:
    """Return the candidate's net and gross measures, its switches and its time invested."""
    values = measures([record.net for record in records], risk_free, periods)
    gross = measures([record.gross for record in records], risk_free, periods)
    values.update(
        {
            "cagr_gross": gross["cagr"],
            "sharpe_gross": gross["sharpe"],
            "switches": float(sum(1 for record in records if record.traded)),
            "share_invested": sum(1 for record in records if record.invested) / len(records),
        }
    )
    return values


def study_report(series: TrendSeries, study: Mapping[str, Any]) -> dict[str, Any]:
    """Run the frozen design and everything it says is reported beside it."""
    periods = study["series"]["periods_per_year"]
    inference, strategy = study["inference"], study["strategy"]
    first = study["window"]["first_holding_month"]
    last = study["window"]["last_holding_month"]
    months, signal = strategy["average_months"], strategy["signal"]
    rate = study["costs"]["declared_rate"]
    rates = {"declared": rate, "stressed": rate * study["costs"]["stress_multiplier"]}
    span = series.span(first, last)
    free = list(series.risk_free[span])
    references = {
        GROWTH_HELD: list(series.growth[span]),
        NASDAQ_HELD: nasdaq_returns(series, first, last),
    }
    records = {
        cost: trend_records(series, months, signal, first, last, rates[cost]) for cost in COSTS
    }
    nets = {CANDIDATE: [record.net for record in records["declared"]], **references}
    tables: dict[str, dict[str, dict[str, float | None]]] = {
        cost: {
            CANDIDATE: candidate_measures(records[cost], free, periods),
            **{name: measures(held, free, periods) for name, held in references.items()},
        }
        for cost in COSTS
    }
    family = list(inference["family"])
    blocks = [inference["mean_block_months"], *inference["sensitivity_mean_block_months"]]
    tests = {
        name: {
            f"block{block}": compare(nets[CANDIDATE], nets[name], free, inference, block, periods)
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
    regimes = {}
    for regime in study["regimes"]:
        low = series.months.index(regime["first"]) - span.start
        high = series.months.index(regime["last"]) - span.start + 1
        regimes[regime["name"]] = {
            name: measures(nets[name][low:high], free[low:high], periods) for name in BOOKS
        }
    sensitivities = {}
    for other in study["sensitivities"]["average_months"]:
        sensitivities[f"average_months={other}"] = candidate_measures(
            trend_records(series, other, signal, first, last, rate), free, periods
        )
    for other in study["sensitivities"]["signal"]:
        sensitivities[f"signal={other}"] = candidate_measures(
            trend_records(series, months, other, first, last, rate), free, periods
        )

    def outside(section: str, names: Sequence[str]) -> dict[str, Any]:
        start = study[section]["first_holding_month"]
        end = study[section]["last_holding_month"]
        bills = list(series.risk_free[series.span(start, end)])
        held = trend_records(series, months, signal, start, end, rate)
        books: dict[str, dict[str, float | None]] = {
            CANDIDATE: candidate_measures(held, bills, periods)
        }
        if GROWTH_HELD in names:
            growth = list(series.growth[series.span(start, end)])
            books[GROWTH_HELD] = measures(growth, bills, periods)
        if NASDAQ_HELD in names:
            books[NASDAQ_HELD] = measures(nasdaq_returns(series, start, end), bills, periods)
        result: dict[str, Any] = {"window": [start, end], "months": len(bills), "books": books}
        if section == "earlier":
            result["test"] = compare(
                [record.net for record in held],
                list(series.growth[series.span(start, end)]),
                bills,
                inference,
                inference["mean_block_months"],
                periods,
            )
            result["beats"] = beats(books[CANDIDATE], books[GROWTH_HELD], tolerance)
        return result

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
        "earlier": outside("earlier", (GROWTH_HELD,)),
        "later": outside("later", (GROWTH_HELD, NASDAQ_HELD)),
        "positions": [
            {"month": record.month, "invested": record.invested, "traded": record.traded}
            for record in records["declared"]
        ],
    }


def _rows(table: Mapping[str, Mapping[str, float | None]]) -> list[str]:
    return [
        f"| {name} | {pct(values['cagr'])} | {pct(values['volatility'])} | "
        f"{num(values['sharpe'])} | {pct(values['max_drawdown'])} |"
        for name, values in table.items()
    ]


def markdown(report: Mapping[str, Any], study: Mapping[str, Any], commit: str) -> str:
    """Return the factual report of the run."""
    declared, stressed = report["books"]["declared"], report["books"]["stressed"]
    first, last = report["window"]
    inference, strategy = study["inference"], study["strategy"]
    one = declared[CANDIDATE]
    lines = [
        "# SA18: a trend filter on the growth portfolio, on the long history (retrospective)",
        "",
        f"Hypothesis `{report['hypothesis_id']}`. Frozen in "
        "[research/SA18/trend_long_history.md](../../../research/SA18/trend_long_history.md) and "
        "[trend_long_history.toml](../../../research/SA18/trend_long_history.toml) before any "
        "level, average or return of the rule was computed. Generated by "
        f"`scripts/SA18_run_trend_long_history.py` at `{commit[:7]}`.",
        "",
        "**Not a blind test**: the third hypothesis read on these months, and a published rule. "
        "Research series, not funds. The Nasdaq Composite has no dividends.",
        "",
        f"Rule: the growth portfolio is held over a month when its total-return level ended the "
        f"month before strictly above the average of its last {strategy['average_months']} "
        "month-end levels; the one-month Treasury bill otherwise.",
        "",
        f"## {first:%Y-%m} to {last:%Y-%m} ({report['months']} months), net",
        "",
        "| Book | Net CAGR | Gross CAGR | Volatility | Net Sharpe | Max drawdown "
        "| Net CAGR x2 | Net Sharpe x2 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in BOOKS:
        row, two = declared[name], stressed[name]
        gross = row.get("cagr_gross", row["cagr"])
        lines.append(
            f"| {name} | {pct(row['cagr'])} | {pct(gross)} | {pct(row['volatility'])} | "
            f"{num(row['sharpe'])} | {pct(row['max_drawdown'])} | {pct(two['cagr'])} | "
            f"{num(two['sharpe'])} |"
        )
    main = f"block{inference['mean_block_months']}"
    others = [f"block{block}" for block in inference["sensitivity_mean_block_months"]]
    lines += [
        "",
        f"The candidate held the growth portfolio in {pct(one['share_invested'])} of months and "
        f"switched {one['switches']:.0f} times.",
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
            *_rows(table),
            "",
        ]
    lines += [
        "## Sensitivities of the candidate (declared costs, decide nothing)",
        "",
        "| Variant | CAGR | Volatility | Sharpe | Max drawdown | Invested | Switches |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant, values in {"frozen design": one, **report["sensitivities"]}.items():
        lines.append(
            f"| {variant} | {pct(values['cagr'])} | {pct(values['volatility'])} | "
            f"{num(values['sharpe'])} | {pct(values['max_drawdown'])} | "
            f"{pct(values['share_invested'])} | {values['switches']:.0f} |"
        )
    earlier, later = report["earlier"], report["later"]
    test = earlier["test"]
    lines += [
        "",
        f"## Earlier months: {earlier['window'][0]:%Y-%m} to {earlier['window'][1]:%Y-%m} "
        f"({earlier['months']} months; decide nothing)",
        "",
        "Before the Nasdaq Composite existed: the growth portfolio is the only reference. No "
        "hypothesis of this project had read these months on this portfolio.",
        "",
        "| Book | CAGR | Volatility | Sharpe | Max drawdown |",
        "| --- | ---: | ---: | ---: | ---: |",
        *_rows(earlier["books"]),
        "",
        f"Sharpe difference {num(test['estimate'], 3)}, {inference['level'] * 100:g} % interval "
        f"[{num(test['low'], 3)}, {num(test['high'], 3)}], p {num(test['p_value'], 3)} "
        f"(unadjusted). Beats the growth portfolio by the criterion: {earlier['beats']}. "
        f"Invested in {pct(earlier['books'][CANDIDATE]['share_invested'])} of months, "
        f"{earlier['books'][CANDIDATE]['switches']:.0f} switches.",
        "",
        f"## Later months: {later['window'][0]:%Y-%m} to {later['window'][1]:%Y-%m} "
        f"({later['months']} months; the window SA15 to SA17 were developed on)",
        "",
        "| Book | CAGR | Volatility | Sharpe | Max drawdown |",
        "| --- | ---: | ---: | ---: | ---: |",
        *_rows(later["books"]),
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    output: Path, report: Mapping[str, Any], study: Mapping[str, Any], commit: str
) -> None:
    """Write the report, the verdict, the table of measures and the positions."""
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
        "earlier": {key: report["earlier"][key] for key in ("window", "months", "test", "beats")},
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
            ("earlier_months", report["earlier"]["books"]),
            ("later_months", report["later"]["books"]),
        ]
        scopes += [(f"regime_{name}", table) for name, table in report["regimes"].items()]
        for scope, table in scopes:
            for book, values in table.items():
                for measure, value in values.items():
                    writer.writerow([scope, book, measure, "" if value is None else repr(value)])
    with (output / "positions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["month", "invested", "traded"])
        for row in report["positions"]:
            writer.writerow([row["month"], row["invested"], row["traded"]])


def main(arguments: list[str] | None = None) -> int:
    """Check the frozen inputs, run the study once, then report."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parsed = parser.parse_args(arguments)
    output = parsed.output if parsed.output.is_absolute() else ROOT / parsed.output
    study = load_study()
    commit = checked_source(output)
    coverage = json.loads((ROOT / study["inputs"]).read_text(encoding="utf-8"))
    series = load_series(ROOT / study["archive"], coverage, study)
    report = study_report(series, study)
    write_outputs(output, report, study, commit)
    for name, values in report["readings"].items():
        print(f"{name}: {values['reading']}", flush=True)
    print(f"report: {output / 'study.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
