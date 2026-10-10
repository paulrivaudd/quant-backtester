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

    worst = facts.loc["Plus forte baisse (sommet → creux)"]
    assert (worst["Du"], worst["Au"]) == (DAYS[1], DAYS[2])
    # Two valuations are one return: the two are never confused.
    assert (worst["Valorisations"], worst["Rendements"]) == (2, 1)
    assert worst["Stratégie"] == pytest.approx(-0.10)
    assert worst["ETF_WORLD (clôture)"] == pytest.approx(-0.20)
    # The relative return is geometric: 0.90 / 0.80 - 1, not -10% + 20%.
    assert worst["Écart relatif"] == pytest.approx(0.125)
    assert worst["Poids de clôture moyen"] == pytest.approx(0.5)
    best = facts.loc["Plus forte hausse (creux → sommet ultérieur, durée libre)"]
    assert (best["Du"], best["Au"]) == (DAYS[2], DAYS[4])
    assert best["Poids de clôture max."] == 1.0
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
    assert "| Rendement net, second run réel à coûts doublés | +61.00% | n/a |" in text
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
        "to_test": ["e"],
    }

    text = SCRIPT.commentary_markdown(notes)

    assert text.index("### Points forts") < text.index("### Points faibles")
    assert "- a\n- b" in text and "La baisse." in text
    assert "Situations de marché les plus risquées" in text
    assert text.index("Situations de marché") < text.index("Ce que ces résultats n'établissent pas")
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
    assert "| 2026 (partielle, depuis le 2026-01-29) (partielle, au 2026-03-02) | +21.00% " in text
    assert "Pire mois : **2026-03**" in text
    assert "moyenne géométrique pondérée" in text and "stress approché" in text
    assert text.index("### Faits mesurés") < text.index("### Baisses sous un sommet") < third
    assert text[third:].count("\n| 2026-0") == len(DAYS)


def test_a_report_is_named_by_its_code_and_its_date() -> None:
    assert SCRIPT.file_name("SA11", "10102026") == "strategySA11_ResultsAndAnalysis_10102026.md"


def test_a_drawdown_is_reported_with_the_day_its_peak_was_reached_again() -> None:
    values = curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0])

    first, second = SCRIPT.underwater_episodes(values)
    text = SCRIPT.drawdown_markdown(values)

    assert (first.peak, first.trough, first.recovery) == (DAYS[1], DAYS[2], DAYS[4])
    assert first.depth == pytest.approx(-0.20)
    # The last fall is not recovered when the curve ends: censored, not closed.
    assert (second.peak, second.trough, second.recovery) == (DAYS[4], DAYS[5], None)
    assert "| 1 | 2026-01-30 | 2026-02-02 | -20.00% | 2026-02-04 | 5 |" in text
    assert (
        "| 2 | 2026-02-04 | 2026-03-02 | -9.09% | non récupéré au 2026-03-02 | 26 (en cours) |"
        in text
    )
    assert "Drawdown au 2026-03-02 : **-9.09%**" in text
    assert "Plus longue période sous un sommet : **26 jours calendaires**" in text
    assert "(en cours" in text


def test_a_curve_that_never_falls_has_no_drawdown_to_recover() -> None:
    text = SCRIPT.drawdown_markdown(curve([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))

    assert SCRIPT.underwater_episodes(curve([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])) == []
    assert "aucune baisse sous un sommet" in text and "**0.00%**" in text


def test_months_are_counted_by_sign_and_an_idle_month_is_not_a_losing_one() -> None:
    flat = curve([100.0, 100.0, 100.0, 100.0, 100.0, 90.0])
    market = curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0])
    yearly = pd.DataFrame(
        {"2026": {"a": -0.10, "buy & hold World": 0.20, "50/50 rebalanced": 0.25, "sessions": 6.0}}
    )

    text = SCRIPT.calendar_markdown(flat, market, yearly, "a", "50/50 rebalanced")

    assert "**0 positifs, 1 négatifs, 2 sans variation** sur 3" in text
    assert (
        "mois incomplets : 2026-01 commence le 2026-01-29 ; 2026-03 s'arrête au 2026-03-02" in text
    )
    assert "| Année | Stratégie | Fonds détenu | 50/50 rebalancé | Séances |" in text
    assert "| -10.00% | +20.00% | +25.00% | 6 |" in text
    # The even split is not shown beside itself.
    own = SCRIPT.calendar_markdown(flat, market, yearly, "50/50 rebalanced", "50/50 rebalanced")
    assert "50/50 rebalancé" not in own


def test_the_activity_says_how_often_anything_was_held() -> None:
    text = SCRIPT.activity_markdown(history())
    idle = history()
    idle["held_ETF_WORLD"] = 0.0

    assert "**5 valorisations sur 6**" in text and "de 50.0% à 100.0%" in text
    assert "aucune position détenue" in SCRIPT.activity_markdown(idle)


def test_the_control_and_the_references_get_a_report_under_a_name_of_their_own() -> None:
    assert SCRIPT.UNCATALOGUED == {
        "EWMA 0.94 control": "EWMA94control",
        "buy & hold World": "REF_WorldBuyHold",
        "50/50 rebalanced": "REF_5050Rebalanced",
    }
