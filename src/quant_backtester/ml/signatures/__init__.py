"""Models that forecast a return from the log-signature of a window: SA13 and its controls.

``config`` holds the frozen configurations, ``models`` the fitted weights and
their inference in NumPy - what a decision needs - ``artifacts`` the frozen
model of one month and the schedule that says which model a decision may use,
and ``training`` the monthly calibration, which is the only part that needs
PyTorch.

Nothing is imported here on purpose: PyTorch (the ``ml`` extra) and the
log-signature backend (the ``signatures`` extra) are optional, and a decision
taken with a model already calibrated needs neither PyTorch nor scikit-learn.
"""

from __future__ import annotations
