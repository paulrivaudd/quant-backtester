"""Signals computed by a fitted model.

Nothing is imported here on purpose: ``neural_allocation`` needs PyTorch, which
is an optional dependency (the ``ml`` extra), and the rest of the layer must
keep importing without it. ``signature_return`` does not - its models are plain
arrays at inference - and may be read by a rule-based strategy.
"""

from __future__ import annotations
