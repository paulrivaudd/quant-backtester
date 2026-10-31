"""Draw the figures of the SA16 study from its saved exports; no backtest is run.

Run after ``scripts/SA16_run_study.py finalise``::

    uv run python scripts/SA16_report.py

Writes ``results/SA16/comparison.png`` (net value on a log scale and the
drawdown below each book's own peak, the retained SA16 beside the two
references and technology held) and ``results/SA16/weights.png`` (what the
retained book actually held). Colours follow the book, in a fixed order;
text stays in neutral ink.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "SA16"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
"""Categorical slots 1 to 4 of the reference palette, in fixed order."""


def curve(folder: Path) -> pd.Series:  # type: ignore[type-arg]
    """Read a saved net curve, indexed by session date."""
    frame = pd.read_csv(folder / "equity.csv")
    index = pd.DatetimeIndex([date.fromisoformat(value) for value in frame["session_date"]])
    return pd.Series(frame.iloc[:, 1].to_numpy(dtype=float), index=index)


def style(axis: plt.Axes) -> None:
    """Keep grid and spines recessive, text neutral."""
    axis.set_facecolor(SURFACE)
    axis.grid(color=GRID, linewidth=1.0)
    axis.tick_params(colors=MUTED, labelsize=9)
    for spine in axis.spines.values():
        spine.set_visible(False)


def comparison(output: Path) -> None:
    """Draw net value and drawdown of the retained book and its comparators."""
    selected = json.loads((output / "selected.json").read_text(encoding="utf-8"))
    name = selected["candidate"]["id"]
    books = {
        f"{name} (retenue)": output / "final" / "x1" / name,
        "Nasdaq conservé": output / "references" / "x1" / "Nasdaq_buy_hold",
        "SA15 essai 71": output / "references" / "x1" / "SA15_R4_trial71",
        "Technologie conservée": output / "references" / "x1" / "Tech_buy_hold",
    }
    figure, (top, bottom) = plt.subplots(
        2, 1, figsize=(11, 7.5), sharex=True, gridspec_kw={"height_ratios": [2, 1]}
    )
    figure.patch.set_facecolor(SURFACE)
    for (label, folder), colour in zip(books.items(), SERIES, strict=True):
        values = curve(folder)
        base = values / values.iloc[0] * 100.0
        top.plot(base.index, base, color=colour, linewidth=2.0, label=label)
        top.annotate(
            f"{base.iloc[-1]:.0f}",
            (base.index[-1], base.iloc[-1]),
            xytext=(4, 0),
            textcoords="offset points",
            color=INK,
            fontsize=9,
            va="center",
        )
        drawdown = values / values.cummax() - 1.0
        bottom.plot(drawdown.index, 100.0 * drawdown, color=colour, linewidth=1.5)
    top.set_yscale("log")
    top.set_ylabel("Valeur nette, base 100 (échelle log)", color=MUTED, fontsize=9)
    bottom.set_ylabel("Baisse sous le sommet (%)", color=MUTED, fontsize=9)
    for axis in (top, bottom):
        style(axis)
    top.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left")
    top.set_title(
        "SA16 : net de coûts, 2018-08-01 → 2026-10-30, 100 000 EUR",
        color=INK,
        fontsize=11,
        loc="left",
    )
    figure.tight_layout()
    figure.savefig(output / "comparison.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)


def weights(output: Path) -> None:
    """Draw the weights the retained book held, session by session."""
    selected = json.loads((output / "selected.json").read_text(encoding="utf-8"))
    name = selected["candidate"]["id"]
    frame = pd.read_csv(output / "final" / "x1" / name / "weights.csv")
    index = pd.DatetimeIndex([date.fromisoformat(value) for value in frame["session_date"]])
    held = frame.drop(columns="session_date").set_index(index)
    held = held.loc[:, held.sum() > 0]
    labels = {"ETF_US_TECH": "Technologie (QDVE)", "ETF_GOLD": "Or (4GLD)"}
    figure, axis = plt.subplots(figsize=(11, 3.2))
    figure.patch.set_facecolor(SURFACE)
    bottom = pd.Series(0.0, index=held.index)
    for column, colour in zip(held.columns, SERIES, strict=False):
        top = bottom + 100.0 * held[column]
        axis.fill_between(
            held.index,
            bottom,
            top,
            color=colour,
            alpha=0.85,
            linewidth=0,
            label=labels.get(column, column),
        )
        bottom = top
    style(axis)
    axis.set_ylim(0, 100)
    axis.set_ylabel("Poids détenu (%)", color=MUTED, fontsize=9)
    axis.legend(frameon=False, fontsize=9, labelcolor=INK, loc="lower left", ncols=2)
    axis.set_title(f"{name} : poids détenus", color=INK, fontsize=11, loc="left")
    figure.tight_layout()
    figure.savefig(output / "weights.png", dpi=130, facecolor=SURFACE)
    plt.close(figure)


def main() -> None:
    """Write both figures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    options = parser.parse_args()
    comparison(options.output)
    weights(options.output)


if __name__ == "__main__":
    main()
