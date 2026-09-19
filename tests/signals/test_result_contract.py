"""What a result is allowed to say, checked where every result passes.

A :class:`SignalResult` is the only thing that leaves this layer, and nothing
downstream re-reads the frame behind it: a portfolio trusts the pair (value,
status) and a report trusts the definition. The checks pinned here therefore
live in the constructor rather than in the engine, so that they also hold for a
result a strategy, a test or a future model builds for itself.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pandas as pd
import pytest

from quant_backtester.signals.base import (
    RESULT_COLUMNS,
    SignalResult,
    build_result_frame,
    result_row,
    unfreeze,
)
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.types import PriceBasis, SignalStatus
from quant_backtester.signals.windows import LoadedWindow

AS_OF = datetime(2026, 9, 18, 20, 0, tzinfo=UTC)

OK_WINDOW = LoadedWindow(status=SignalStatus.OK, points=(1.0, 2.0), age_sessions=0)


def result(rows: Mapping[str, Mapping[str, object]], signal_id: str = "return_4d") -> SignalResult:
    """Return a result over hand-written rows."""
    return SignalResult(
        signal_id=signal_id,
        as_of=AS_OF,
        _frame=build_result_frame(dict(rows)),
        definition={"type": "Hand written"},
    )


def test_a_well_formed_result_is_accepted() -> None:
    """The baseline the refusals below are variations on."""
    answer = result(
        {
            "ETF_EU": result_row(0.04, OK_WINDOW),
            "IDX_US": result_row(None, LoadedWindow(status=SignalStatus.MISSING_INPUT)),
        }
    )

    assert answer.status("ETF_EU") is SignalStatus.OK
    assert answer.value("ETF_EU") == pytest.approx(0.04)
    assert answer.value("IDX_US") != answer.value("IDX_US")


# --- the value and the status say the same thing -----------------------------


def test_a_row_that_is_ok_without_a_number_is_refused() -> None:
    """``OK`` is what says a number can be used, so there must be one.

    A cross-section counting such a row believes it is ranking three
    instruments while pandas can only rank two: the order survives and the
    scale does not.
    """
    with pytest.raises(ValueError, match="is OK but its value"):
        result({"ETF_EU": result_row(None, OK_WINDOW)})


@pytest.mark.parametrize("number", [float("inf"), float("-inf")])
def test_an_infinite_number_is_not_a_number_either(number: float) -> None:
    """A division that overflowed is not a forecast, whatever its status says."""
    with pytest.raises(ValueError, match="is OK but its value"):
        result({"ETF_EU": result_row(number, OK_WINDOW)})


def test_a_row_that_is_not_ok_and_still_carries_a_number_is_refused() -> None:
    """A number nobody vouched for must not travel beside a reason it is missing."""
    row = dict(result_row(None, LoadedWindow(status=SignalStatus.STALE_INPUT)))
    row["value"] = 0.04

    with pytest.raises(ValueError, match="STALE_INPUT and still carries"):
        result({"ETF_EU": row})


def nullable_value(status: SignalStatus) -> pd.DataFrame:
    """Return a one-row frame whose value column holds ``pd.NA`` rather than ``NaN``."""
    frame = build_result_frame({"ETF_EU": result_row(None, LoadedWindow(status=status))})
    frame["value"] = frame["value"].astype("Float64")
    frame.loc["ETF_EU", "value"] = pd.NA
    return frame


def test_pandas_own_missing_value_reads_as_no_number() -> None:
    """A frame built by hand may hold ``pd.NA`` where a signal holds ``NaN``.

    Both say there is no number, and neither may be read as one: the ``OK`` row
    is refused for having no value, and the row that admits it has none passes.
    """
    with pytest.raises(ValueError, match="is OK but its value"):
        SignalResult(
            signal_id="return_4d",
            as_of=AS_OF,
            _frame=nullable_value(SignalStatus.OK),
            definition={},
        )

    answer = SignalResult(
        signal_id="return_4d",
        as_of=AS_OF,
        _frame=nullable_value(SignalStatus.MISSING_INPUT),
        definition={},
    )
    assert answer.status("ETF_EU") is SignalStatus.MISSING_INPUT


# --- the diagnostics describe something --------------------------------------


@pytest.mark.parametrize("column", ["observations_used", "max_input_age_sessions"])
def test_a_negative_diagnostic_is_refused(column: str) -> None:
    """One counts observations and the other sessions; neither can be negative."""
    row = dict(result_row(0.04, OK_WINDOW))
    row[column] = -1

    with pytest.raises(ValueError, match=f"{column} is -1"):
        result({"ETF_EU": row})


def test_a_diagnostic_nobody_filled_in_is_allowed() -> None:
    """A window that loaded nothing has nothing to count, and says so."""
    answer = result({"ETF_EU": result_row(None, LoadedWindow(status=SignalStatus.NOT_LISTED))})

    frame = answer.frame
    assert pd.isna(frame.loc["ETF_EU", "observations_used"])
    assert pd.isna(frame.loc["ETF_EU", "max_input_age_sessions"])


# --- the result is named, and named once -------------------------------------


@pytest.mark.parametrize("signal_id", ["", "   "])
def test_a_result_without_a_name_is_refused(signal_id: str) -> None:
    """A snapshot keyed by an empty name is a log nobody can read back."""
    with pytest.raises(ValueError, match="signal_id must be a non-empty name"):
        result({"ETF_EU": result_row(0.04, OK_WINDOW)}, signal_id=signal_id)


# --- the frame handed over stops belonging to the caller ---------------------


def test_the_frame_is_copied_when_the_result_is_built() -> None:
    """A signal that kept a reference could rewrite its answer afterwards.

    Without the copy the result would be immutable only through its own API,
    and a strategy reading a snapshot could see a number change under it.
    """
    frame = build_result_frame({"ETF_EU": result_row(0.04, OK_WINDOW)})
    answer = SignalResult(
        signal_id="return_4d", as_of=AS_OF, _frame=frame, definition={"type": "Hand written"}
    )

    frame.loc["ETF_EU", "value"] = 999.0

    assert answer.value("ETF_EU") == pytest.approx(0.04)


# --- the definition can be written down --------------------------------------


def test_a_frozen_definition_can_be_serialised_again(context: SignalContext) -> None:
    """Freezing protects the record; writing an experiment down needs it back.

    The nested definition of a ranking is the case that matters: its source
    comes back as a plain dictionary, not as a read-only view ``json.dumps``
    refuses.
    """
    source = ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW)
    signal = CrossSectionalRank(signal_id="rank", source=source)

    definition = signal.definition_json()

    assert json.loads(json.dumps(definition)) == definition
    assert isinstance(definition["source"], dict)
    assert definition["source"]["lookback_sessions"] == 4
    assert signal.compute(context, ["ETF_EU", "IDX_US"]).definition == signal.definition()


def test_unfreezing_gives_back_lists_where_freezing_made_tuples() -> None:
    """A definition naming its inputs is a sequence, and JSON has only lists."""
    assert unfreeze(({"a": (1, 2)}, "b")) == [{"a": [1, 2]}, "b"]


def test_the_columns_a_result_must_hold_are_the_ones_it_is_read_by() -> None:
    """The contract is a tuple, and a missing column is named rather than hidden."""
    frame = build_result_frame({"ETF_EU": result_row(0.04, OK_WINDOW)})

    with pytest.raises(ValueError, match="observations_used"):
        SignalResult(
            signal_id="return_4d",
            as_of=AS_OF,
            _frame=frame.drop(columns=["observations_used"]),
            definition={},
        )
    assert tuple(frame.columns) == RESULT_COLUMNS


def test_a_fingerprint_survives_a_definition_that_was_frozen(context: SignalContext) -> None:
    """A composite may carry a definition it read back off a result.

    ``json.dumps`` refuses a read-only view, so a fingerprint taken of the raw
    definition would fail exactly where two experiments most need telling
    apart: a signal built out of another one's record.
    """
    source = ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW)
    frozen_source = source.compute(context, ["ETF_EU"]).definition

    class Composite(ReturnSignal):
        def definition(self) -> Mapping[str, object]:
            return {"type": "Composite", "source": frozen_source}

    composite = Composite(signal_id="composite", lookback_sessions=4, price_basis=PriceBasis.RAW)

    assert len(composite.fingerprint()) == 64
    assert composite.definition_json()["source"] == dict(frozen_source)
