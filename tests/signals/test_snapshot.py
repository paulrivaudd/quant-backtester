"""The snapshot: what a strategy is allowed to hold, and what it cannot do with it."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.cross_sectional.rank import CrossSectionalRank
from quant_backtester.signals.engine import SignalEngine
from quant_backtester.signals.price.returns import ReturnSignal
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import PriceBasis, SignalStatus


@pytest.fixture
def snapshot(context: SignalContext) -> SignalSnapshot:
    """Return a snapshot holding one return over three instruments."""
    signal = ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW)
    return SignalEngine().compute(context, [signal], ["ETF_EU", "IDX_US", "ETF_LATE"])


def test_a_strategy_reads_a_number_without_knowing_where_it_came_from(
    snapshot: SignalSnapshot,
) -> None:
    """No Yahoo, no Parquet, no calendar, no field availability: a number."""
    assert snapshot.value("return_4d", "ETF_EU") == pytest.approx(109.0 / 105.0 - 1.0)


def test_it_also_says_why_a_number_is_missing(snapshot: SignalSnapshot) -> None:
    """The four ways of having none stay four different things."""
    assert snapshot.status("return_4d", "ETF_EU") is SignalStatus.OK
    assert snapshot.status("return_4d", "ETF_LATE") is SignalStatus.INSUFFICIENT_HISTORY


def test_the_usable_rows_can_be_taken_apart_from_the_rest(
    snapshot: SignalSnapshot,
) -> None:
    """A cross-section is built on the instruments that have a number."""
    usable = snapshot.result("return_4d").ok()

    assert list(usable.index) == ["ETF_EU", "IDX_US"]
    assert len(snapshot.values("return_4d")) == 3


def test_asking_for_a_signal_that_was_not_computed_is_loud(
    snapshot: SignalSnapshot,
) -> None:
    """A strategy naming a signal the engine was not given is a wiring mistake."""
    with pytest.raises(KeyError, match="momentum_60d"):
        snapshot.result("momentum_60d")


def test_a_snapshot_cannot_be_reassigned(snapshot: SignalSnapshot) -> None:
    """Immutable: a strategy cannot change what it was handed."""
    with pytest.raises((AttributeError, TypeError)):
        snapshot.as_of = snapshot.as_of  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot.results["return_4d"] = snapshot.result("return_4d")  # type: ignore[index]


def test_a_snapshot_refuses_a_result_from_another_instant(
    snapshot: SignalSnapshot,
) -> None:
    """Every number in it answers the same question, asked once."""
    other = snapshot.as_of.replace(year=2027)

    with pytest.raises(ValueError, match="not at the snapshot"):
        SignalSnapshot(as_of=other, results=dict(snapshot.results))


def test_membership_reads_naturally(snapshot: SignalSnapshot) -> None:
    """A strategy can ask whether a signal is there before reaching for it."""
    assert "return_4d" in snapshot
    assert "momentum_60d" not in snapshot


# --- the snapshot is immutable all the way down ------------------------------
#
# A frozen dataclass around a pandas frame is immutable only at its surface.
# The frame is what a strategy actually reads, and a strategy that wrote into
# one would change what every strategy reading the same snapshot sees after it.


def test_mutating_snapshot_values_does_not_change_snapshot(
    snapshot: SignalSnapshot,
) -> None:
    """What comes out of the snapshot belongs to the caller."""
    before = snapshot.value("return_4d", "ETF_EU")

    frame = snapshot.values("return_4d")
    frame.loc["ETF_EU", "value"] = 999.0
    frame["a_column_of_my_own"] = 1.0

    assert snapshot.value("return_4d", "ETF_EU") == before
    assert "a_column_of_my_own" not in snapshot.values("return_4d").columns


def test_mutating_a_result_frame_does_not_change_the_result(
    snapshot: SignalSnapshot,
) -> None:
    """The same guarantee one level down, where a signal hands over its answer."""
    result = snapshot.result("return_4d")
    before = result.value("ETF_EU")

    frame = result.frame
    frame.loc["ETF_EU", "status"] = SignalStatus.INVALID_INPUT
    frame.loc["ETF_EU", "value"] = 999.0

    assert result.value("ETF_EU") == before
    assert result.status("ETF_EU") is SignalStatus.OK


def test_writing_straight_into_the_property_is_loud(snapshot: SignalSnapshot) -> None:
    """``result.frame.loc[...] = x`` writes into a frame that is thrown away.

    Pandas refuses the chained assignment outright, which is the right end for
    a mistake that would otherwise look like it had worked.
    """
    result = snapshot.result("return_4d")

    with pytest.raises(Exception, match=r"[Cc]hained"):
        result.frame.loc["ETF_EU", "value"] = 999.0


def test_the_usable_rows_are_a_copy_too(snapshot: SignalSnapshot) -> None:
    """A strategy filters, then writes weights into what it filtered."""
    result = snapshot.result("return_4d")

    usable = result.ok()
    usable.loc["ETF_EU", "value"] = -1.0

    assert result.value("ETF_EU") != -1.0


def test_mutating_a_definition_does_not_change_the_result(
    snapshot: SignalSnapshot,
) -> None:
    """A definition is what a fingerprint is taken of.

    Two signals that could be edited into agreeing would make a fingerprint
    worthless as a way of telling two experiments apart.
    """
    definition = snapshot.result("return_4d").definition

    with pytest.raises(TypeError):
        definition["lookback_sessions"] = 999  # type: ignore[index]


def test_a_nested_definition_is_frozen_too(context: SignalContext) -> None:
    """A ranking carries its source's definition inside its own."""
    source = ReturnSignal(signal_id="return_4d", lookback_sessions=4, price_basis=PriceBasis.RAW)
    result = CrossSectionalRank(signal_id="rank", source=source).compute(
        context, ["ETF_EU", "IDX_US"]
    )

    nested = result.definition["source"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        nested["lookback_sessions"] = 999  # type: ignore[index]


def test_a_result_filed_under_another_name_is_refused(snapshot: SignalSnapshot) -> None:
    """The key and the result have to be the same signal.

    The engine builds the mapping itself, but this constructor is public: a
    snapshot where the two disagree would answer
    ``result("momentum").signal_id == "return_4d"``, and every log, report and
    attribution built on it would be wrong about what it was reading.
    """
    with pytest.raises(ValueError, match="filed under"):
        SignalSnapshot(as_of=snapshot.as_of, results={"momentum_60d": snapshot.result("return_4d")})
