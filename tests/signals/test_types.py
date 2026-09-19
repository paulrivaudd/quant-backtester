"""The vocabulary the whole layer is written in, and the guards on it.

The checks here look small. They are the ones that keep a parameter written
wrong from quietly meaning something else: ``True`` is an integer to Python and
would pass for one session, ``0.5`` compares like zero, and a string that reads
like a :class:`WindowMode` is not that object, so a window would stop checking
the very thing it asked for.
"""

from __future__ import annotations

import pytest

from quant_backtester.signals.types import (
    WindowMode,
    WindowSpec,
    require_identifier,
    require_non_negative_int,
    require_positive_int,
)


@pytest.mark.parametrize("value", [1, 20, 252])
def test_a_positive_whole_number_of_sessions_is_accepted(value: int) -> None:
    """The ordinary case: a lookback is a count of sessions."""
    require_positive_int(value, "lookback_sessions")


@pytest.mark.parametrize("value", [0, -1, True, 1.0, 0.5, "20", None])
def test_anything_that_is_not_one_is_refused(value: object) -> None:
    """A window of zero, of ``True`` or of ``"20"`` is a configuration mistake.

    It stops the run rather than becoming a status: no instrument would have
    been computed correctly either, so there is nothing to report per name.
    """
    with pytest.raises(ValueError, match="lookback_sessions must be a positive integer"):
        require_positive_int(value, "lookback_sessions")  # type: ignore[arg-type]


def test_zero_is_a_threshold_and_not_a_mistake() -> None:
    """A staleness threshold of zero means the freshest session, and is legal."""
    require_non_negative_int(0, "max_age_sessions")


@pytest.mark.parametrize("value", [-1, True, 0.5, "0", None])
def test_a_threshold_that_is_not_a_count_of_sessions_is_refused(value: object) -> None:
    """``True`` would mean one session and ``0.5`` would compare like zero."""
    with pytest.raises(ValueError, match="max_age_sessions must be a non-negative integer"):
        require_non_negative_int(value, "max_age_sessions")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "   ", None, 4])
def test_something_that_cannot_be_a_name_is_refused(value: object) -> None:
    """An empty id makes a snapshot key, a log and a report unreadable."""
    with pytest.raises(ValueError, match="signal_id must be a non-empty name"):
        require_identifier(value, "signal_id")  # type: ignore[arg-type]


def test_a_window_declares_how_it_counts() -> None:
    """The two modes are different contracts, and a spec holds one of them."""
    spec = WindowSpec(20, WindowMode.AVAILABLE_OBSERVATIONS)

    assert spec.observations == 20
    assert spec.mode is WindowMode.AVAILABLE_OBSERVATIONS
    assert WindowSpec(20).mode is WindowMode.CONSECUTIVE_SESSIONS


def test_a_mode_that_only_reads_like_one_is_refused() -> None:
    """``"CONSECUTIVE_SESSIONS"`` is not ``WindowMode.CONSECUTIVE_SESSIONS``.

    The code that acts on the mode compares with ``is``, so the string would
    leave the continuity check switched off and a signal would measure
    something other than what it asked for - exactly what this module exists to
    make impossible, and not something a type checker nobody has to run can be
    left in charge of.
    """
    with pytest.raises(ValueError, match="mode must be a WindowMode"):
        WindowSpec(20, "CONSECUTIVE_SESSIONS")  # type: ignore[arg-type]
