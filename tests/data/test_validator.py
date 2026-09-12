"""Validation rules are typed by instrument, not universal."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Exercice 6.2")
def test_negative_rate_is_accepted():
    """A negative level is valid for a RATE.

    The German 10-year yield was negative from 2019 to 2022. A blanket
    ``value > 0`` rule would make that period unloadable.
    """


@pytest.mark.skip(reason="Exercice 6.2")
def test_negative_price_is_rejected_for_an_etf():
    """The same rule that is wrong for a rate is right for an ETF."""


@pytest.mark.skip(reason="Exercice 6.2")
def test_large_volatility_move_is_not_flagged():
    """The VIX gained 115% on 5 February 2018; that is not a data error."""


@pytest.mark.skip(reason="Exercice 6.2")
def test_ohlc_ordering_is_enforced():
    """``low <= open <= high`` and ``low <= close <= high``."""


@pytest.mark.skip(reason="Exercice 6.3")
def test_repeated_stale_open_is_flagged():
    """An open repeatedly equal to the previous close is reported.

    One occurrence is normal. A run of them on an illiquid ETF means there was
    no usable auction - and since the open is our execution price, a strategy
    trading it would book a gain that never existed.
    """


@pytest.mark.skip(reason="Exercice 6.2")
def test_gap_against_the_calendar_is_a_warning():
    """A session the calendar knows about with no row is reported as a hole."""
