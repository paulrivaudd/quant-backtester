"""Reviewed corrections: what a provider called an action, and what it was."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.data.corporate_actions import (
    ActionCorrection,
    ActionCorrections,
)
from quant_backtester.data.schemas import CORPORATE_ACTIONS_SCHEMA, ActionType

COMMITTED = (
    Path(__file__).resolve().parents[2] / "market_data" / "metadata" / "corporate_actions.toml"
)

GE_SPIN_OFF = ActionCorrection(
    instrument_id="GE",
    ex_date=date(2023, 1, 4),
    from_type=ActionType.SPLIT,
    to_type=ActionType.SPIN_OFF,
    reason="GE HealthCare spin-off; Yahoo reports it as a 1.281 stock split",
)
"""The event this module exists for, as Yahoo really serves it."""


def actions(rows: list[tuple[str, str, date, float]]) -> pd.DataFrame:
    """Return canonical actions from ``(instrument_id, type, ex_date, value)``."""
    frame = pd.DataFrame(
        [
            {
                "instrument_id": instrument_id,
                "action_type": action_type,
                "ex_date": ex_date,
                "value": value,
                "available_at_utc": pd.Timestamp(
                    datetime.combine(ex_date, datetime.min.time(), tzinfo=UTC)
                ),
                "source": "YAHOO",
                "source_fetch_id": "20260918T120000Z-actions",
            }
            for instrument_id, action_type, ex_date, value in rows
        ],
        columns=list(CORPORATE_ACTIONS_SCHEMA.names),
    )
    frame["available_at_utc"] = frame["available_at_utc"].astype("datetime64[us, UTC]")
    return frame


def write_toml(tmp_path: Path, content: str) -> Path:
    """Write ``content`` to a corrections file and return its path."""
    path = tmp_path / "corporate_actions.toml"
    path.write_text(content, encoding="utf-8")
    return path


SAMPLE = """
[[correction]]
instrument_id = "GE"
ex_date = 2023-01-04
from_type = "SPLIT"
to_type = "SPIN_OFF"
reason = "GE HealthCare spin-off; Yahoo reports it as a 1.281 stock split"
"""


def test_the_committed_file_loads_and_is_empty() -> None:
    """Committed empty on purpose: none of the five instruments has had such an event."""
    assert len(ActionCorrections.from_toml(COMMITTED)) == 0


def test_a_correction_relabels_exactly_its_own_event() -> None:
    """Same instrument, same ex-date, same reported type - and nothing else."""
    corrections = ActionCorrections([GE_SPIN_OFF])
    frame = actions(
        [
            ("GE", "SPLIT", date(2023, 1, 4), 1.281),
            ("GE", "SPLIT", date(2021, 8, 2), 0.125),  # a real reverse split
            ("AAPL", "SPLIT", date(2023, 1, 4), 4.0),  # another instrument
            ("GE", "DIVIDEND", date(2023, 1, 4), 0.08),  # another reported type
        ]
    )

    corrected = corrections.apply(frame)

    assert corrected["action_type"].tolist() == ["SPIN_OFF", "SPLIT", "SPLIT", "DIVIDEND"]


def test_a_correction_changes_nothing_but_the_label() -> None:
    """It says what an event was, never what it was worth."""
    frame = actions([("GE", "SPLIT", date(2023, 1, 4), 1.281)])

    corrected = ActionCorrections([GE_SPIN_OFF]).apply(frame)

    for column in ("instrument_id", "ex_date", "value", "available_at_utc", "source_fetch_id"):
        assert corrected[column].tolist() == frame[column].tolist()


def test_applying_to_no_action_is_not_an_error() -> None:
    """An instrument with no event at all takes the same path."""
    empty = CORPORATE_ACTIONS_SCHEMA.empty_table().to_pandas()
    assert ActionCorrections([GE_SPIN_OFF]).apply(empty).empty


def test_an_uncorrected_label_is_returned_unchanged() -> None:
    """Including one no ActionType knows: the validator is what rejects it."""
    corrections = ActionCorrections([GE_SPIN_OFF])
    assert corrections.corrected_type("GE", date(2023, 1, 4), "RIGHTS_ISSUE") == "RIGHTS_ISSUE"


def test_from_toml_reads_a_reviewed_entry(tmp_path: Path) -> None:
    """The date is a native TOML date, like everywhere else in the metadata."""
    corrections = ActionCorrections.from_toml(write_toml(tmp_path, SAMPLE))

    assert len(corrections) == 1
    assert corrections.corrected_type("GE", date(2023, 1, 4), "SPLIT") == "SPIN_OFF"


@pytest.mark.parametrize(
    ("broken", "message"),
    [
        (SAMPLE.replace("reason =", "resaon ="), "resaon"),
        (
            SAMPLE.replace(
                'reason = "GE HealthCare spin-off; Yahoo reports it as a 1.281 stock split"', ""
            ),
            "reason",
        ),
        (SAMPLE.replace('to_type = "SPIN_OFF"', 'to_type = "SPLIT_OFF"'), "SPLIT_OFF"),
    ],
)
def test_from_toml_rejects_a_broken_entry(tmp_path: Path, broken: str, message: str) -> None:
    """A typo in a reviewed decision must fail loudly, not fall back to a default."""
    with pytest.raises(ValueError, match=message):
        ActionCorrections.from_toml(write_toml(tmp_path, broken))


def test_a_blank_reason_is_refused() -> None:
    """A decision nobody can re-examine is not a decision."""
    with pytest.raises(ValueError, match="reason"):
        ActionCorrections(
            [ActionCorrection("GE", date(2023, 1, 4), ActionType.SPLIT, ActionType.SPIN_OFF, "  ")]
        )


def test_a_dividend_cannot_be_corrected_into_a_split() -> None:
    """Only a mislabelling is correctable, and only where the price adjustment matches.

    Turning a dividend into a split would silently rewrite every earlier price,
    which is a data change disguised as a label change.
    """
    with pytest.raises(ValueError, match="may only be corrected"):
        ActionCorrections(
            [ActionCorrection("GE", date(2023, 1, 4), ActionType.DIVIDEND, ActionType.SPLIT, "no")]
        )


def test_one_event_cannot_be_corrected_twice() -> None:
    """Two reviews of the same event cannot both be the one that was made."""
    with pytest.raises(ValueError, match="corrected more than once"):
        ActionCorrections([GE_SPIN_OFF, GE_SPIN_OFF])


def test_an_ex_date_that_is_a_datetime_is_refused() -> None:
    """A date with an hour on it would never match a stored ex-date."""
    with pytest.raises(ValueError, match="plain date"):
        ActionCorrections(
            [
                ActionCorrection(
                    "GE",
                    datetime(2023, 1, 4, 12, 0, tzinfo=UTC),  # type: ignore[arg-type]
                    ActionType.SPLIT,
                    ActionType.SPIN_OFF,
                    "wrong type",
                )
            ]
        )
