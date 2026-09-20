"""Reviewed corrections to a broken bar: what they drop, and when they stop.

The interesting case is not the drop. It is the correction that no longer
describes anything: a provider that repairs its own data leaves a note in a
config file quietly removing a good bar, for ever, and nobody would look.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from quant_backtester.data.bar_corrections import BarCorrection, BarCorrections, BarDefect
from quant_backtester.data.instruments import AssetType, DataType, Instrument
from quant_backtester.data.normalizer import bar_availability
from quant_backtester.data.schemas import BARS_SCHEMA

BROKEN = date(2026, 3, 11)
"""The session a provider sent wrong in these tests."""

WHY = "the open is above the high and no second source reaches this session"
"""A reason, because a correction without one cannot be re-examined."""


@pytest.fixture
def fund() -> Instrument:
    """Return a tradable Paris fund."""
    return Instrument(
        id="ETF_EU",
        name="Paris ETF",
        asset_type=AssetType.ETF,
        data_type=DataType.BAR,
        currency="EUR",
        primary_source="YAHOO",
        source_symbol="CW8.PA",
        tradable=True,
        calendar_id="XPAR",
    )


def bars(xpar, rows: dict[date, tuple[float, float, float, float]]) -> pd.DataFrame:
    """Build canonical bars from ``session -> (open, high, low, close)``."""
    records = []
    for session_date, (open_, high, low, close) in rows.items():
        open_at, close_at = bar_availability(session_date, xpar)
        records.append(
            {
                "instrument_id": "ETF_EU",
                "session_date": session_date,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000.0,
                "open_available_at_utc": pd.Timestamp(open_at),
                "close_available_at_utc": pd.Timestamp(close_at),
                "source": "YAHOO",
                "source_fetch_id": "20260313T210000Z",
            }
        )
    frame = pd.DataFrame(records, columns=list(BARS_SCHEMA.names))
    for column in ("open_available_at_utc", "close_available_at_utc"):
        frame[column] = frame[column].astype("datetime64[us, UTC]")
    return frame


def impossible(xpar) -> pd.DataFrame:
    """Return three bars, the middle one with its open above its high."""
    return bars(
        xpar,
        {
            date(2026, 3, 10): (100.0, 101.0, 99.0, 100.5),
            BROKEN: (101.0, 100.6, 99.5, 100.0),
            date(2026, 3, 12): (100.0, 101.0, 99.0, 100.5),
        },
    )


def correction(**overrides: object) -> BarCorrection:
    """Build the correction for the broken bar, with fields overridden."""
    fields: dict[str, object] = {
        "instrument_id": "ETF_EU",
        "source": "YAHOO",
        "session_date": BROKEN,
        "defect": BarDefect.OHLC_ORDER,
        "reason": WHY,
    }
    fields.update(overrides)
    return BarCorrection(**fields)  # type: ignore[arg-type]


def test_a_reviewed_bar_is_dropped_and_the_rest_is_kept(fund: Instrument, xpar) -> None:
    """The session becomes a hole, which is what it honestly is."""
    corrections = BarCorrections([correction()])

    kept, applied = corrections.apply(fund, "YAHOO", impossible(xpar))

    assert list(kept["session_date"]) == [date(2026, 3, 10), date(2026, 3, 12)]
    assert applied == (correction(),)


def test_a_correction_never_repairs_the_price(fund: Instrument, xpar) -> None:
    """Nothing here knows the high the market made, and inventing one is worse.

    A repaired bar looks like data. A missing one looks like what it is, and
    the reader already reports it as a hole rather than as a price.
    """
    kept, _ = BarCorrections([correction()]).apply(fund, "YAHOO", impossible(xpar))

    assert BROKEN not in set(kept["session_date"])
    assert len(kept.columns) == len(BARS_SCHEMA.names)


def test_another_source_s_bar_for_the_same_session_is_untouched(fund: Instrument, xpar) -> None:
    """A defect belongs to one feed, and the second source is what may arbitrate it."""
    kept, applied = BarCorrections([correction()]).apply(fund, "EURONEXT", impossible(xpar))

    assert len(kept) == 3
    assert applied == ()


def test_a_correction_for_a_session_the_fetch_does_not_cover_matches_nothing(
    fund: Instrument, xpar
) -> None:
    """Most fetches are a recent window, and that is not an error."""
    elsewhere = BarCorrections([correction(session_date=date(2019, 5, 6))])

    kept, applied = elsewhere.apply(fund, "YAHOO", impossible(xpar))

    assert len(kept) == 3
    assert applied == ()


def test_a_bar_the_provider_repaired_stops_the_ingestion(fund: Instrument, xpar) -> None:
    """The decision no longer describes anything, and nobody would have looked.

    Going on dropping a good bar because of a note written in 2026 is the
    failure this class exists to prevent, so it is loud rather than silent.
    """
    repaired = bars(xpar, {BROKEN: (100.0, 101.0, 99.0, 100.5)})

    with pytest.raises(ValueError, match="no longer has"):
        BarCorrections([correction()]).apply(fund, "YAHOO", repaired)


def test_a_correction_written_for_the_wrong_defect_is_refused(fund: Instrument, xpar) -> None:
    """The row is broken, and not in the way the reviewer wrote down."""
    with pytest.raises(ValueError, match="NON_POSITIVE_PRICE"):
        BarCorrections([correction(defect=BarDefect.NON_POSITIVE_PRICE)]).apply(
            fund, "YAHOO", impossible(xpar)
        )


def test_an_empty_set_of_corrections_changes_nothing(fund: Instrument, xpar) -> None:
    """The normal state of the file, and the one that must cost nothing."""
    frame = impossible(xpar)

    kept, applied = BarCorrections([]).apply(fund, "YAHOO", frame)

    assert kept is frame
    assert applied == ()


def test_a_correction_needs_a_reason() -> None:
    """A decision nobody explained cannot be re-examined by anybody."""
    with pytest.raises(ValueError, match="reason cannot be blank"):
        BarCorrections([correction(reason="   ")])


def test_a_bar_cannot_be_corrected_twice() -> None:
    """Two reviews of one bar cannot both be the one that was made."""
    with pytest.raises(ValueError, match="corrected more than once"):
        BarCorrections([correction(), correction(reason="another look")])


def test_a_session_date_is_a_date_not_an_instant() -> None:
    """A datetime would never match the plain date a canonical row carries."""
    with pytest.raises(ValueError, match="plain date"):
        BarCorrections([correction(session_date=datetime(2026, 3, 11, 9, 0))])


def write(tmp_path: Path, text: str) -> Path:
    """Write a corrections file and return its path."""
    path = tmp_path / "bar_corrections.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_correction_loads_from_the_committed_file(tmp_path: Path) -> None:
    """It is configuration a result is reproduced from, like the rest."""
    path = write(
        tmp_path,
        """
[[correction]]
instrument_id = "ETF_EU"
source = "YAHOO"
session_date = 2026-03-11
defect = "OHLC_ORDER"
reason = "open above high"
""",
    )

    corrections = BarCorrections.from_toml(path)

    assert len(corrections) == 1


def test_an_empty_file_is_the_normal_state(tmp_path: Path) -> None:
    """Nothing reviewed is a state someone chose, not a missing file."""
    assert len(BarCorrections.from_toml(write(tmp_path, "# nothing yet\n"))) == 0


def test_a_missing_file_is_an_error(tmp_path: Path) -> None:
    """The empty file is committed on purpose; its absence means a broken tree."""
    with pytest.raises(FileNotFoundError):
        BarCorrections.from_toml(tmp_path / "nowhere.toml")


@pytest.mark.parametrize(
    ("entry", "match"),
    [
        (
            'instrument_id = "A"\nsource = "Y"\nsession_date = 2026-03-11\ndefect = "OHLC_ORDER"',
            "missing key",
        ),
        (
            'instrument_id = "A"\nsource = "Y"\nsession_date = 2026-03-11\n'
            'defect = "OHLC_ORDER"\nreason = "r"\nnote = "x"',
            "unknown key",
        ),
        (
            'instrument_id = "A"\nsource = "Y"\nsession_date = 2026-03-11\n'
            'defect = "EXTREME_MOVE"\nreason = "r"',
            "EXTREME_MOVE",
        ),
    ],
    ids=["no-reason", "unknown-key", "defect-nobody-may-correct"],
)
def test_a_file_that_cannot_be_trusted_is_refused(tmp_path: Path, entry: str, match: str) -> None:
    """A typo in a decision file is a decision nobody took."""
    with pytest.raises(ValueError, match=match):
        BarCorrections.from_toml(write(tmp_path, f"[[correction]]\n{entry}\n"))


def test_the_committed_corrections_hold_together() -> None:
    """The file a result is reproduced from is read on every run of the suite."""
    metadata = Path(__file__).resolve().parents[2] / "market_data" / "metadata"

    corrections = BarCorrections.from_toml(metadata / "bar_corrections.toml")

    assert len(corrections) >= 1
