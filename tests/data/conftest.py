"""Fixtures for the market data layer.

Everything here is synthetic and offline. A test that needs a provider is marked
``@pytest.mark.network`` and is not part of the routine suite.

The venue calendars and the empty store live in ``tests/conftest.py``: the
signals layer builds on the same ones, and two copies of a holiday list drift.
"""

from __future__ import annotations
