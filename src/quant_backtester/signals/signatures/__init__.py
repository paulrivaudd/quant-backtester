"""A window of a market described by the log-signature of its path.

``path`` builds the path - cumulative log return, cumulative relative turnover,
session time - from what a reader fixed at one decision serves, and the
classical indicators and the raw trajectory the study compares it with.
``logsignature`` turns a path into the coefficients of its truncated
log-signature, through ``esig`` with the ``roughpy`` backend.

Nothing is imported here on purpose: the backend is an optional dependency
(the ``signatures`` extra), imported when a log-signature is asked for, and
the rest of the layer must keep importing without it.
"""

from __future__ import annotations
