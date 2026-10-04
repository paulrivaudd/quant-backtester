"""Signals computed by a fitted model.

Nothing is imported here on purpose: these signals need PyTorch, which is an
optional dependency (the ``ml`` extra), and the rest of the layer must keep
importing without it.
"""

from __future__ import annotations
