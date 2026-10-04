"""Fitted models: what they read, how they are trained and how they are kept.

A fitted model is a strategy with a past: it was calibrated on one period and
is only honest on a later one. Everything here exists to keep those two apart.
The inputs are built by one function for the training set and for a decision
(``features``), the labels are read by a builder that cannot see past the end
of the training period (``dataset``), the normalisation is fitted on that
period alone, and what is kept afterwards (``artifacts``) carries the instant
its information stops at, so that a backtest starting before it is refused.

The package is not one layer. ``config``, ``features``, ``network`` and
``artifacts`` read nothing above the signals, and are what the signal and the
strategy of a model import. ``dataset`` and ``training`` run offline, before
any backtest: they compose the reader, the runner and the strategy, the way
``backtest.runner`` composes the layers. Nothing is imported here, so that
importing the first group never drags in the second.

PyTorch is an optional dependency (the ``ml`` extra): nothing outside this
package and the two modules that use it - ``signals.ml`` and
``strategies.ml`` - imports it.
"""

from __future__ import annotations
