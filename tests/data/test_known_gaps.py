"""Reviewed gaps: known, never filled, and refused the day they stop being gaps."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quant_backtester.data.bar_corrections import BarCorrections
from quant_backtester.data.known_gaps import GapKind, KnownGap, KnownGaps

COMMITTED = Path(__file__).resolve().parents[2] / "market_data" / "metadata"


def gap(**overrides: object) -> KnownGap:
    """Return one reviewed gap of ETF_SP500_PEA, with some fields replaced."""
    values: dict[str, object] = {
        "instrument_id": "ETF_SP500_PEA",
        "session_date": date(2015, 5, 25),
        "kind": GapKind.NO_BAR_SERVED,
        "hypothesis": "no trade",
        "evidence": "neighbouring volumes",
        "reviewed_on": date(2026, 9, 26),
    }
    values.update(overrides)
    return KnownGap(**values)  # type: ignore[arg-type]


def test_the_committed_register_loads_and_agrees_with_the_bar_corrections() -> None:
    gaps = KnownGaps.from_toml(COMMITTED / "known_gaps.toml")
    corrections = BarCorrections.from_toml(COMMITTED / "bar_corrections.toml")

    assert gaps.sessions("ETF_SP500_PEA") == {
        date(2014, 12, 24),
        date(2015, 5, 25),
        date(2015, 12, 24),
        date(2015, 12, 31),
        date(2017, 9, 7),
    }
    dropped = {g.session_date for g in gaps if g.kind is GapKind.BAR_DROPPED}
    assert dropped <= corrections.sessions("ETF_SP500_PEA")


def test_a_gap_is_reviewed_once() -> None:
    with pytest.raises(ValueError, match="more than once"):
        KnownGaps([gap(), gap()])


@pytest.mark.parametrize("blank", ["hypothesis", "evidence", "instrument_id"])
def test_a_gap_without_its_reasons_is_refused(blank: str) -> None:
    with pytest.raises(ValueError, match=blank):
        KnownGaps([gap(**{blank: "  "})])


def test_an_unknown_kind_in_the_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "known_gaps.toml"
    path.write_text(
        '[[gap]]\ninstrument_id = "X"\nsession_date = 2015-05-25\nkind = "FILLED"\n'
        'hypothesis = "h"\nevidence = "e"\nreviewed_on = 2026-09-26\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="FILLED"):
        KnownGaps.from_toml(path)


def test_a_missing_register_is_an_error_not_an_empty_one(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        KnownGaps.from_toml(tmp_path / "known_gaps.toml")
