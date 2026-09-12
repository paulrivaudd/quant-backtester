"""The three tests that decide whether this layer can be trusted."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Exercice 8.2 - test 1/3")
def test_field_masking_follows_the_session(xpar):
    """Availability is carried by the field, not by the row.

    At 23:00 Paris on day t, the reader exposes the close of t and refuses the
    open of t+1. At 09:01 on day t+1 it exposes the open of t+1 and refuses the
    close of t+1.

    This is what makes the engine's two readers per day legitimate: the strategy
    gets the decision one and never holds an object able to show it its own fill
    price.
    """


@pytest.mark.skip(reason="Exercice 8.5 - test 2/3")
def test_future_data_does_not_change_the_past(xnys):
    """The look-ahead guard.

    Build a series, read it through a reader frozen at ``as_of``, keep the
    result. Then append bars *and a 4:1 split* dated after ``as_of``, and read
    again through a reader at the same instant. The two results must be
    identical, byte for byte.

    The split is the part that matters: it is the one event able to rewrite a
    past series retroactively, and the reason ``adj_close`` is not stored.
    """


@pytest.mark.skip(reason="Exercice 8.5")
def test_adjusted_series_is_flat_across_a_split(xnys):
    """A flat series at 100 with a 4:1 split adjusts to a flat series at 25.

    No return jump on the ex-date. If one appears, the adjustment factor is
    applied on the wrong side of the boundary.
    """


@pytest.mark.skip(reason="Exercice 8.3")
def test_not_listed_is_distinct_from_missing(xpar):
    """Before its first session an instrument is NOT_LISTED, never MISSING.

    An ETF launched in 2018 read at a 2015 decision instant must be excluded
    from the universe, not reported as a data hole - and a genuine hole in 2020
    must not be excluded as if it had never been listed.
    """


@pytest.mark.skip(reason="Exercice 8.3")
def test_stale_value_reports_its_age(xnys, xpar):
    """A US close read on a day NYSE was closed is STALE with age_sessions >= 1."""


@pytest.mark.skip(reason="Exercice 8.1")
def test_naive_as_of_is_rejected():
    """A naive decision instant raises rather than being assumed to be UTC."""
