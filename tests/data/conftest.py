"""Fixtures for the market data layer.

Everything here is synthetic and offline. A test that needs a provider is marked
``@pytest.mark.network`` and is not part of the routine suite.
"""

from __future__ import annotations

from datetime import date, time  # noqa: F401  (a utiliser dans les fixtures)
from pathlib import Path

import pytest

from quant_backtester.data.calendars import TradingCalendar


@pytest.fixture
def xnys() -> TradingCalendar:
    """Return a minimal NYSE calendar covering the tricky dates of 2026.

    Notes
    -----
    Exercice T.1. Inclus au minimum : le 27 novembre 2026 (demi-seance, cloture
    13:00 ET) et une seance de mars et de novembre, pour les bascules d'heure.
    """
    pytest.skip("Exercice T.1")


@pytest.fixture
def xpar() -> TradingCalendar:
    """Return a minimal Euronext Paris calendar.

    Notes
    -----
    Exercice T.1. Prevois un jour ferie a Paris ou NY est ouvert (1er novembre)
    pour tester le desalignement des deux calendriers.
    """
    pytest.skip("Exercice T.1")


@pytest.fixture
def market_root(tmp_path: Path) -> Path:
    """Return an empty market data root.

    Notes
    -----
    Exercice T.2. Cree ``metadata/``, ``raw/``, ``clean/`` et ``validation/``.
    """
    pytest.skip("Exercice T.2")
