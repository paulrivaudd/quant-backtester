"""The per-strategy reports: their measured facts, their three sections and their names."""

from __future__ import annotations

import importlib.util
import json
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
    # An indicator only some studies measure is left out, not printed as missing.
    assert "Sortino" not in text
    assert text.count("\n") == 2 + len(SCRIPT.GLOBAL_ROWS) - len(SCRIPT.OPTIONAL_ROWS)
    measured = SCRIPT.global_table({**row, "sortino": 1.19}, market, None)
    assert "| Ratio de Sortino net (taux sans risque 0) | +1.19 | n/a |" in measured


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
        "measured": ["m"],
        "to_test": ["e"],
    }

    text = SCRIPT.commentary_markdown(notes)

    assert text.index("### Points forts") < text.index("### Points faibles")
    assert "- a\n- b" in text and "La baisse." in text
    assert "Situations de marché les plus risquées" in text
    measured = text.index("Mesures complémentaires")
    assert text.index("Situations de marché") < measured
    assert measured < text.index("Ce que ces résultats n'établissent pas")
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


# --- the reports a later study writes for its own strategy ---------------------------------


def test_the_columns_a_study_adds_to_a_history_have_a_heading_and_a_unit() -> None:
    frame = history()
    frame.insert(1, "open_ETF_WORLD", [99.5, 109.0, 90.0, 98.0, 130.0, 121.0])
    frame.insert(2, "model_month", [float("nan"), 202602.0, 202602.0, 202602.0, 202603.0, 202603.0])
    frame.insert(3, "forecast_bp", [float("nan"), 25.4, -3.2, 0.0, 12.0, 8.5])
    frame.insert(4, "price_volume_bp", [float("nan"), 6.0, -1.5, 0.25, 2.0, 1.0])
    frame.insert(5, "gate", [float("nan"), 1.0, 0.0, 0.0, 1.0, 1.0])
    frame.insert(6, "theoretical_weight", [float("nan"), 0.6, 0.0, 0.0, 0.6, 0.6])
    frame.insert(7, "mu_h2_bp", [float("nan"), 21.0, 4.0, 4.0, 22.5, 1.0])
    frame.insert(8, "forecast_volatility", [float("nan"), 0.2, 0.2, 0.2, 0.1, 0.1])
    frame.insert(9, "ewma_fallback", [0.0, 0.0, 1.0, 0.0, 0.0, 0.0])

    lines = SCRIPT.history_markdown(frame).splitlines()

    for heading in (
        "Ouverture ETF_WORLD",
        "Modèle du mois (AAAAMM)",
        "Prévision (pb)",
        "Prix-volume (pb)",
        "Filtre (1 = ouvert)",
        "Poids avant bande",
        "Prévision mu_2 (pb)",
        "Volatilité prévue (annualisée)",
        "Repli EWMA (1 = oui)",
    ):
        assert f"| {heading} |" in lines[0]
    # A day without a model or a forecast is an empty cell, never a zero.
    assert lines[2].startswith("| 2026-01-29 | 100.00 | 99.50 |  |  |  |  |  |  |  | 0 |")
    assert lines[3].startswith(
        "| 2026-01-30 | 110.00 | 109.00 | 202602 | +25.40 | +6.00 | 1 | 60.0% | +21.00 | 20.0% "
    )
    assert set(SCRIPT.HISTORY_COLUMNS) >= {"reference_bp", "order_3_bp", "displacements_bp"}


def test_every_book_of_the_study_is_listed_with_the_strategy_in_bold() -> None:
    summary = pd.DataFrame(
        {
            "rank": [1.0, 2.0, float("nan")],
            "quality": [0.52, 0.0, float("nan")],
            "net_return": [0.61, -0.017, 0.95],
            "sharpe": [0.85, -0.14, 0.93],
            "max_drawdown": [-0.18, -0.07, -0.22],
            "costs_eur": [5788.0, 4022.0, 100.0],
        },
        index=pd.Index(["D0 - same risk no filter", "SA12 - ARIMA GARCH", "buy & hold World"]),
    )
    stressed = summary.assign(net_return=[0.56, -0.057, 0.94])

    text = SCRIPT.peers_markdown(summary, stressed, "SA12 - ARIMA GARCH")
    alone = SCRIPT.peers_markdown(summary, None, "SA12 - ARIMA GARCH")

    lines = text.splitlines()
    assert lines[0].startswith("| Livre | Rang | Score | Net | Net, coûts x2 | Sharpe |")
    assert lines[2].startswith("| D0 - same risk no filter | 1 | 52.0% | +61.00% | +56.00% | +0.85")
    assert lines[3].startswith("| **SA12 - ARIMA GARCH** | 2 | 0.0% | -1.70% | -5.70% | -0.14")
    # A reference has no rank and no score: said, not zero. An unmeasured column too.
    assert lines[4].startswith("| buy & hold World | n/a | n/a | +95.00% | +94.00% |")
    assert "| n/a | n/a | 100 |" in lines[4]
    assert "coûts x2" not in alone and alone.count("\n") == 4


def test_the_section_of_the_study_sits_in_the_analysis_above_the_commentary() -> None:
    market = curve([100.0, 110.0, 88.0, 99.0, 132.0, 120.0])
    yearly = pd.DataFrame(
        {"2026": {"SA12 - ARIMA GARCH": 0.21, "buy & hold World": 0.20, "sessions": 6.0}}
    )
    row = {"first_session": "2026-01-29", "last_session": "2026-03-02", "sessions": 6}
    notes = {"summary": "Une phrase.", "measured": ["m"], "measured_source": "SA12_study.md"}

    text = SCRIPT.report(
        "SA12 - ARIMA GARCH",
        row,
        {},
        None,
        history(),
        market,
        yearly,
        notes,
        ["Provenance."],
        peers="| Livre | Rang |\n|---|---:|\n| **SA12 - ARIMA GARCH** | 10 |",
        extra="### Statut de l'hypothèse préinscrite : **INSUFFICIENT_EVIDENCE**\n",
    )

    peers = text.index("### Classement de tous les livres de l'étude")
    status = text.index("### Statut de l'hypothèse préinscrite")
    assert text.index("## 1. Indicateurs") < peers < text.index("## 2. Analyse")
    assert "ne se comparent pas à ceux d'une autre étude" in text
    assert text.index("### Par année et par mois") < status < text.index("### En résumé")
    assert status < text.index("## 3. Historique")
    assert "### Mesures complémentaires (voir SA12_study.md)" in text
    # Without them a report is what it was before: no empty heading is left behind.
    plain = SCRIPT.report(
        "SA12 - ARIMA GARCH", row, {}, None, history(), market, yearly, None, ["Provenance."]
    )
    assert "Classement de tous les livres" not in plain and "Statut" not in plain


def test_a_study_says_what_its_period_is_and_why() -> None:
    config = {
        "source": {"git_commit": "2b7d147abcdef0123", "source_state": "CLEAN"},
        "period": {"start": "2023-01-02", "end": "2026-10-09"},
        "data_state": "750c23dfffc3aaaa",
    }

    common = SCRIPT.study_provenance(config)
    test = SCRIPT.study_provenance(
        config, period_label="Période de test", context="Un modèle par mois. "
    )

    assert common[0].startswith("Période commune 2023-01-02 → 2026-10-09 · capital 100 000 EUR")
    assert "commit `2b7d147abcde` (CLEAN), magasin `750c23dfffc3`" in common[2]
    assert len(common) == 3
    assert test[0].startswith("Période de test 2023-01-02 → 2026-10-09")
    assert test[-2:] == ["", "Un modèle par mois."]


def study_folder(root: Path) -> Path:
    """Write the exports of a study of three books, one of them a control without a code."""
    names = ["D0 - same risk no filter", "SA12 - ARIMA GARCH", "buy & hold World"]
    summary = pd.DataFrame(
        {
            "rank": [1.0, 2.0, float("nan")],
            "quality": [0.52, 0.0, float("nan")],
            "net_return": [0.21, 0.21, 0.20],
            "sharpe": [0.85, -0.14, 0.93],
            "sortino": [1.17, -0.17, 1.30],
            "max_drawdown": [-0.18, -0.07, -0.22],
            "first_session": ["2026-01-29"] * 3,
            "last_session": ["2026-03-02"] * 3,
            "sessions": [6] * 3,
        },
        index=pd.Index(names, name="book"),
    )
    root.mkdir(parents=True)
    summary.to_csv(root / "summary.csv")
    summary.to_csv(root / "summary_costs_x2.csv")
    yearly = pd.DataFrame(
        {"2026": [0.21, 0.21, 0.20, 6.0]}, index=pd.Index([*names, "sessions"], name="book")
    )
    yearly.to_csv(root / "yearly.csv")
    for name in names:
        history().to_csv(root / f"history_{SCRIPT.slug(name)}.csv")
    config = {
        "source": {"git_commit": "10f6d902af68", "source_state": "CLEAN"},
        "period": {"start": "2026-01-29", "end": "2026-03-02"},
        "data_state": "750c23dfffc3",
    }
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (root / "report_extra_SA12.md").write_text("### Statut : **INSUFFICIENT_EVIDENCE**\n")
    return root


def test_only_the_reports_asked_for_are_written_and_a_control_has_none(tmp_path: Path) -> None:
    study = study_folder(tmp_path / "study")
    output = tmp_path / "reports"
    output.mkdir()
    (output / "commentary.toml").write_text(
        '[SA12]\nsummary = "Une phrase."\nperiod_label = "Période de test"\n'
        'context = "Contexte de l\'étude."\nmeasured_source = "SA12_study_10102026.md"\n'
        'measured = ["m"]\nhistory_note = "Colonnes propres à cette étude."\n',
        encoding="utf-8",
    )

    code = SCRIPT.main(
        ["--study", str(study), "--output", str(output), "--only", "SA12", "--stamp", "10102026"]
    )

    written = sorted(path.name for path in output.glob("strategy*.md"))
    assert code == 0 and written == ["strategySA12_ResultsAndAnalysis_10102026.md"]
    text = (output / written[0]).read_text(encoding="utf-8")
    assert text.startswith("# SA12 - ARIMA GARCH — résultats et analyse")
    assert "Période de test 2026-01-29 → 2026-03-02" in text and "Contexte de l'étude." in text
    assert "| **SA12 - ARIMA GARCH** | 2 |" in text and "| D0 - same risk no filter | 1 |" in text
    assert "### Statut : **INSUFFICIENT_EVIDENCE**" in text
    assert "| Ratio de Sortino net (taux sans risque 0) | -0.17 | +1.30 |" in text
    assert "Mesures complémentaires (voir SA12_study_10102026.md)" in text
    assert text.index("## 3. Historique") < text.index("Colonnes propres à cette étude.")
    with pytest.raises(SystemExit, match="no book for SA13"):
        SCRIPT.main(["--study", str(study), "--output", str(output), "--only", "SA13"])


def test_without_a_selection_a_control_of_a_later_study_is_skipped(tmp_path: Path) -> None:
    study = study_folder(tmp_path / "study")
    output = tmp_path / "reports"

    SCRIPT.main(["--study", str(study), "--output", str(output), "--skip-ml1"])

    written = sorted(path.name for path in output.glob("strategy*.md"))
    assert written == [
        "strategyREF_WorldBuyHold_ResultsAndAnalysis_10102026.md",
        "strategySA12_ResultsAndAnalysis_10102026.md",
    ]
    # No ranking and no study section unless the report was asked for by its code.
    text = (output / written[1]).read_text(encoding="utf-8")
    assert "Classement de tous les livres" not in text and "### Statut" not in text
