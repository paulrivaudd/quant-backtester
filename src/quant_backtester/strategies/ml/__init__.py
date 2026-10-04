"""Strategies whose weights come from a fitted model: the ML family.

Nothing is imported here on purpose: these strategies need PyTorch, which is
an optional dependency (the ``ml`` extra), and the other strategies must keep
importing without it. :mod:`quant_backtester.strategies.catalogue` names them.
"""

from __future__ import annotations
