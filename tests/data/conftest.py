"""Fixtures for the market data layer.

Everything here is synthetic and offline. A test that needs a provider is marked
``@pytest.mark.network`` and is not part of the routine suite.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from quant_backtester.data.calendars import TradingCalendar


@pytest.fixture
def xnys() -> TradingCalendar:
    """Return a minimal NYSE calendar covering the tricky dates of 2026.

    Holidays: two Mondays (MLK Day 19 January, Labor Day 7 September),
    Thanksgiving (Thursday 26 November) and Christmas. Half days: 27 November and
    24 December, closing 13:00 ET. The US DST switches of 8 March and 1 November
    fall inside the year, so sessions on either side of each are covered.

    Synthetic on purpose: the committed ``XNYS.toml`` can grow without moving
    these tests.
    """
    return TradingCalendar(
        calendar_id="XNYS",
        timezone="America/New_York",
        regular_open=time(9, 30),
        regular_close=time(16, 0),
        holidays=frozenset(
            {date(2026, 1, 19), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}
        ),
        early_closes={date(2026, 11, 27): time(13, 0), date(2026, 12, 24): time(13, 0)},
    )


@pytest.fixture
def xpar() -> TradingCalendar:
    """Return a minimal Euronext Paris calendar for 2026.

    Easter Monday (6 April) closes Paris while New York trades: the day that
    tests the two calendars disagreeing. 1 November, the usual example, is a
    Sunday in 2026 - and not a Euronext holiday anyway. Half days: 24 and 31
    December, closing 14:05 CET.
    """
    return TradingCalendar(
        calendar_id="XPAR",
        timezone="Europe/Paris",
        regular_open=time(9, 0),
        regular_close=time(17, 30),
        holidays=frozenset(
            {date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 1), date(2026, 12, 25)}
        ),
        early_closes={date(2026, 12, 24): time(14, 5), date(2026, 12, 31): time(14, 5)},
    )


@pytest.fixture
def market_root(tmp_path: Path) -> Path:
    """Return an empty market data root.

    Notes
    -----
    Exercice T.2. Cree ``metadata/``, ``raw/``, ``clean/`` et ``validation/``.
    """
    pytest.skip("Exercice T.2")
