"""The per-strategy reports: their measured facts, their three sections and their names."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

pytest.importorskip("arch")

REPOSITORY = Path(__file__).resolve().parents[2]


def load_script() -> ModuleType:
    """Import ``scripts/write_strategy_reports.py``, its folder on the path as when run."""
    scripts = REPOSITORY / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "write_strategy_reports.py"
    spec = importlib.util.spec_from_file_location("write_strategy_reports", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()
DAYS = [
    date(2026, 1, 29),
    date(2026, 1, 30),
    date(2026, 2, 2),
    date(2026, 2, 3),
    date(2026, 2, 4),
    date(2026, 3, 2),
]


def curve(values: list[float]) -> pd.Series:
    """Return a curve over the six sessions."""
    return pd.Series(values, index=pd.Index(DAYS, dtype="object"), dtype="float64")


def history() -> pd.DataFrame:
    """Return the history of a book that held half the fund, then all of it."""
    return pd.DataFrame(
        {
            "close_ETF_WORLD": [100.0, 110.0, 88.0, 99.0, 132.0, 120.0],
            "close_ETF_SP500_PEA": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "volatility_20r[ETF_WORLD]": [float("nan"), 0.2, 0.24, 0.2, 0.1, 0.1],
            "target_ETF_WORLD": [0.5, 0.5, 0.5, 1.0, 1.0, 1.0],
            "held_ETF_WORLD": [float("nan"), 0.5, 0.5, 0.5, 1.0, 1.0],
            "net_equity": [100.0, 105.0, 94.5, 100.0, 133.0, 121.0],
            "gross_equity": [100.0, 105.1, 94.6, 100.2, 133.4, 121.5],
        },
        index=pd.Index(DAYS, dtype="object", name="session_date"),
    )


def test_the_deepest_fall_runs_from_a_peak_to_the_trough_after_it() -> None:
    fall = SCRIPT.deepest_fall(curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0]))

    assert (fall.start, fall.end) == (DAYS[1], DAYS[2])
    assert fall.change == pytest.approx(-0.20)


def test_the_largest_rise_runs_from_a_trough_to_the_peak_after_it() -> None:
    rise = SCRIPT.largest_rise(curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0]))

    assert (rise.start, rise.end) == (DAYS[2], DAYS[4])
    assert rise.change == pytest.approx(0.50)


def test_the_extreme_windows_are_the_fixed_length_stretches_that_changed_most() -> None:
    values = curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0])

    worst = SCRIPT.extreme_window(values, 1, best=False)
    best = SCRIPT.extreme_window(values, 2, best=True)
    whole = SCRIPT.extreme_window(values, 63, best=True)

    assert (worst.start, worst.end, worst.change) == (DAYS[1], DAYS[2], pytest.approx(-0.20))
    assert (best.start, best.end, best.change) == (DAYS[2], DAYS[4], pytest.approx(0.50))
    # A curve shorter than the window is measured whole.
    assert (whole.start, whole.end, whole.change) == (DAYS[0], DAYS[5], pytest.approx(0.20))


def test_a_curve_that_only_rises_has_no_fall() -> None:
    fall = SCRIPT.deepest_fall(curve([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))

    assert fall.change == 0.0 and fall.start == fall.end == DAYS[0]


def test_a_month_is_measured_from_the_last_value_of_the_month_before() -> None:
    months = SCRIPT.monthly_returns(curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0]))

    assert list(months.index) == ["2026-01", "2026-02", "2026-03"]
    assert months["2026-01"] == pytest.approx(0.10)  # from the first value of the curve
    assert months["2026-02"] == pytest.approx(0.20)
    assert months["2026-03"] == pytest.approx(120.0 / 132.0 - 1.0)


def test_the_facts_give_the_book_the_fund_and_the_exposure_over_each_stretch() -> None:
    market = curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0])

    facts = SCRIPT.facts_table(history(), market).set_index("Période")

    worst = facts.loc["Plus forte baisse de la stratégie"]
    assert (worst["Du"], worst["Au"], worst["Séances"]) == (DAYS[1], DAYS[2], 2)
    assert worst["Stratégie"] == pytest.approx(-0.10)
    assert worst["ETF_WORLD (clôture)"] == pytest.approx(-0.20)
    assert worst["Exposition moyenne"] == pytest.approx(0.5)
    best = facts.loc["Plus forte hausse de la stratégie"]
    assert (best["Du"], best["Au"]) == (DAYS[2], DAYS[4])
    assert best["Exposition max."] == 1.0
    assert len(facts) == 8
    text = SCRIPT.facts_markdown(facts.reset_index())
    assert "-10.00%" in text and "| 50% |" in text


def test_the_global_table_shows_the_strategy_beside_the_fund_and_never_a_zero_for_nothing() -> None:
    row = {
        "rank": 6.0,
        "quality": 0.486,
        "net_return": 0.66,
        "sharpe": 0.87,
        "max_drawdown": -0.165,
        "first_session": "2021-04-01",
        "last_session": "2026-10-09",
        "sessions": 1416,
        "diagnostics": float("nan"),
    }
    market = {"net_return": 0.948, "sharpe": 0.93, "quality": float("nan")}

    text = SCRIPT.global_table(row, market, {"net_return": 0.61, "sharpe": 0.82})

    assert "| Période mesurée | 2021-04-01 → 2026-10-09 (1416 séances) | idem |" in text
    assert "| Score de qualité QUALITY_V1 (0-100 %) | 48.6% | n/a |" in text
    assert "| Rendement net total | +66.00% | +94.80% |" in text
    assert "| Rendement net, coûts doublés (second run réel) | +61.00% | n/a |" in text
    assert "| Coûts payés (EUR) | n/a | n/a |" in text
    assert text.count("\n") == 2 + len(SCRIPT.GLOBAL_ROWS)


def test_the_history_has_a_row_per_session_and_hides_what_the_strategy_does_not_use() -> None:
    lines = SCRIPT.history_markdown(history()).splitlines()

    assert len(lines) == 2 + len(DAYS)
    assert lines[0] == (
        "| Séance | Clôture ETF_WORLD | `volatility_20r[ETF_WORLD]` | Poids cible ETF_WORLD | "
        "Poids détenu ETF_WORLD | Valeur nette (EUR) |"
    )
    # No value for the signal on the first day; no position is a weight of zero.
    assert lines[2] == "| 2026-01-29 | 100.00 |  | 50.0% | 0.0% | 100.00 |"
    assert lines[3] == "| 2026-01-30 | 110.00 | 0.2000 | 50.0% | 50.0% | 105.00 |"
    assert "gross" not in lines[0] and "SP500" not in lines[0]


def test_the_second_fund_is_shown_when_the_strategy_reads_or_holds_it() -> None:
    frame = history()
    frame["held_ETF_SP500_PEA"] = 0.25

    header = SCRIPT.history_markdown(frame).splitlines()[0]

    assert "Clôture ETF_SP500_PEA" in header and "Poids détenu ETF_SP500_PEA" in header


def test_the_commentary_is_written_or_said_to_be_missing() -> None:
    notes = {
        "summary": "Une phrase.",
        "strengths": ["a", "b"],
        "weaknesses": ["c"],
        "worst": "La baisse.",
        "best": "La hausse.",
        "risks": ["d"],
    }

    text = SCRIPT.commentary_markdown(notes)

    assert text.index("### Points forts") < text.index("### Points faibles")
    assert "- a\n- b" in text and "La baisse." in text
    assert "Situations de marché les plus risquées" in text
    assert "Aucun commentaire" in SCRIPT.commentary_markdown(None)
    assert "Aucun commentaire" in SCRIPT.commentary_markdown({})


def test_a_report_has_its_three_sections_with_the_analysis_above_the_history() -> None:
    market = curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0])
    yearly = pd.DataFrame(
        {"2026": {"SA6 - vol control": 0.21, "buy & hold World": 0.20, "sessions": 6.0}}
    )
    row = {"first_session": "2026-01-29", "last_session": "2026-03-02", "sessions": 6}

    text = SCRIPT.report(
        "SA6 - vol control", row, {}, None, history(), market, yearly, None, ["Provenance."]
    )

    assert text.startswith("# SA6 - vol control — résultats et analyse")
    first = text.index("## 1. Indicateurs de résultat globaux")
    second = text.index("## 2. Analyse")
    third = text.index("## 3. Historique")
    assert first < second < third
    assert "| 2026 | +21.00% | +20.00% | 6 |" in text
    assert "Pire mois : **2026-03**" in text
    assert text[third:].count("\n| 2026-0") == len(DAYS)


def test_a_report_is_named_by_its_code_and_its_date() -> None:
    assert SCRIPT.file_name("SA11", "10102026") == "strategySA11_ResultsAndAnalysis_10102026.md"
