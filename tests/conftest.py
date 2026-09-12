"""Shared pytest fixtures.

Keep fixtures deterministic: no network access, no wall-clock dependence, and
no reliance on files outside `tests/`.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def rng_seed() -> int:
    """Return the single seed used by every test that needs randomness."""
    return 20240101
