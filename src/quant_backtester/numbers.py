"""Guards for the numbers a configuration is made of.

A research parameter is declared once and then believed for the rest of a run,
so the moment to refuse a wrong one is the moment it is written down. The
awkward part is that Python's comparisons let two wrong ones through without a
word:

- ``NaN`` compares false against everything, so ``if rate < 0: raise`` accepts
  it and every later comparison on it is false too. A commission rate of
  ``NaN`` charges ``NaN`` and turns a whole equity curve into one;
- ``True`` is an ``int``, so a threshold of ``True`` is a threshold of one.

Both are a parameter written wrong rather than a parameter meaning something
unusual, and a backtest that swallows either reports a number nobody can
reproduce. These helpers live at the root of the package rather than in a
layer: a cost rate, a weight and a starting cash are the same kind of
statement, and the rule about them should not be written three times.

Integer parameters and identifiers have their own guards in
:mod:`quant_backtester.signals.types`, beside the window API they exist for.
"""

from __future__ import annotations

import math


def require_finite(value: float, name: str) -> None:
    """Raise unless ``value`` is a finite number.

    Parameters
    ----------
    value : float
        Parameter to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not a number at all, is a boolean, or is ``NaN`` or an
        infinity. An infinite threshold is a filter that is always open or
        always shut, which is a configuration mistake dressed as a strategy.
    """
    if isinstance(value, bool) or not isinstance(value, float | int):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value}")


def require_finite_non_negative(value: float, name: str) -> None:
    """Raise unless ``value`` is a finite number of zero or more.

    Parameters
    ----------
    value : float
        Parameter to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not finite, or is negative.
    """
    require_finite(value, name)
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")


def require_finite_positive(value: float, name: str) -> None:
    """Raise unless ``value`` is a finite number strictly above zero.

    Parameters
    ----------
    value : float
        Parameter to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not finite, or is zero or less.
    """
    require_finite(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def require_unit_fraction(value: float, name: str) -> None:
    """Raise unless ``value`` is a finite fraction in ``[0, 1]``.

    Parameters
    ----------
    value : float
        Parameter to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not finite, or falls outside ``[0, 1]``. A weight below zero
        is a short position, which nothing in this project finances; a weight
        above one is a position bought with money the book does not have.
    """
    require_finite(value, name)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a fraction in [0, 1], got {value}")
