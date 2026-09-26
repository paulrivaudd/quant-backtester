"""The conventions a performance figure depends on, declared rather than assumed.

An annualised number is not a property of a run: it is the run plus a rule for
turning sessions into years, and a Sharpe ratio is the run plus a rate the
strategy is being compared against. Two reports built on different conventions
are not comparable, and neither is worth anything if nobody wrote down which
one it used. Both live here, with no default, so that a result follows from
committed code plus committed configuration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class AnalyticsConfig:
    """How to annualise, and what to compare a return against.

    Attributes
    ----------
    sessions_per_year : int
        Sessions a year holds on the calendar the run was walked on. It scales
        a volatility and a Sharpe ratio, and nothing else. A venue's own count
        belongs here - roughly 252 for XNYS, 255 for XPAR - and it is declared
        rather than guessed because the two give different numbers.
    risk_free_rate : float
        Annual rate the strategy is measured against, as a fraction: ``0.02``
        is two percent. Constant on purpose. A rate series would be more
        faithful and would mean this layer reads market data, which it does
        not; a constant that is written down can at least be argued with.
    minimum_sessions : int
        Below this many sessions, annualised figures are not produced at all.
        Compounding a fortnight into a year is how a run that gained one
        percent a day for a week reports a return of several million percent,
        and a report that prints nothing is more honest than one that prints
        that. It changes no number, only whether one is shown.

    Raises
    ------
    ValueError
        If the counts are not positive whole numbers, or the rate is not a
        finite fraction above ``-1``.
    """

    sessions_per_year: int
    risk_free_rate: float
    minimum_sessions: int = 60

    def __post_init__(self) -> None:
        """Reject a convention that cannot describe a year or a rate."""
        for name, value in (
            ("sessions_per_year", self.sessions_per_year),
            ("minimum_sessions", self.minimum_sessions),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                raise ValueError(
                    f"{name} must be a whole number of sessions above 1, got {value!r}"
                )
        if isinstance(self.risk_free_rate, bool) or not isinstance(
            self.risk_free_rate, float | int
        ):
            raise ValueError(f"risk_free_rate must be a number, got {self.risk_free_rate!r}")
        if not math.isfinite(self.risk_free_rate) or self.risk_free_rate <= -1.0:
            raise ValueError(
                f"risk_free_rate is an annual fraction above -1, got {self.risk_free_rate}"
            )

    def definition(self) -> dict[str, object]:
        """Return every field of the convention, as it is recorded with a run.

        Returns
        -------
        dict[str, object]
            One entry per dataclass field, read from the fields themselves: a
            convention added later is recorded without anyone remembering to.
            Leaving ``minimum_sessions`` out made two runs whose annualised
            return was ``0.0`` in one and ``None`` in the other record the same
            configuration (audit A13).
        """
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @property
    def risk_free_per_session(self) -> float:
        """Return the risk-free rate over one session.

        Returns
        -------
        float
            The annual rate compounded down to a session, not divided by the
            number of them: a rate that compounds up must come down the same
            way, or the excess return carries an error of its own.
        """
        return (1.0 + self.risk_free_rate) ** (1.0 / self.sessions_per_year) - 1.0
