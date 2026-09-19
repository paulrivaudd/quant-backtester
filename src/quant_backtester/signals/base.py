"""What every signal is, and what it gives back.

A signal turns the market as it was knowable at one instant into one number per
instrument. It does not decide anything: "the momentum of this fund is +8.1%"
is a signal, "buy the two highest" is a strategy, and the line between them is
what keeps a backtest explainable.

A result therefore carries more than a number. It says which window produced it,
how many points that window held, how old its freshest input was, and - when
there is no number - which of the several ways of having none applies.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from types import MappingProxyType
from typing import Final

import pandas as pd

from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import PriceBasis, SignalStatus, WindowSpec
from quant_backtester.signals.windows import LoadedWindow, load_window

RESULT_COLUMNS: Final[tuple[str, ...]] = (
    "value",
    "status",
    "input_start_date",
    "input_end_date",
    "observations_used",
    "max_input_age_sessions",
)
"""Columns of every :class:`SignalResult`, in order.

The diagnostics are not decoration. A strategy that drops an instrument wants to
know whether it was not listed or whether the data is late, and a result that
says only ``NaN`` cannot tell it.
"""


def freeze(value: object) -> object:
    """Return a value no caller can change, mappings frozen all the way down.

    Parameters
    ----------
    value : object
        A definition, or one of its parts.

    Returns
    -------
    object
        A read-only view of a mapping, a tuple in place of a list, and anything
        else unchanged. A definition is what a fingerprint is taken of, so a
        caller able to edit one could make two different signals claim to be
        the same.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class SignalResult:
    """One signal's answer for a set of instruments, at one instant.

    Attributes
    ----------
    signal_id : str
        Identity of the signal instance that produced it.
    as_of : datetime
        Decision instant. Every row was computed with what was knowable then.
    _frame : pd.DataFrame
        Indexed by ``instrument_id``, with :data:`RESULT_COLUMNS` and possibly
        more. Private, and read through :attr:`frame`: a result is handed to a
        strategy, and a pandas frame is mutable, so the object would otherwise
        be immutable only at its surface. The underscore is the signal that
        constructing one hands over ownership of that frame.
    definition : Mapping[str, object]
        Every parameter that changes the number, serialisable. Two runs with
        the same definition and the same data give the same result. Frozen at
        construction, nested mappings included.

    Raises
    ------
    ValueError
        If the frame does not hold the required columns, repeats an
        instrument, or carries anything other than a :class:`SignalStatus` in
        its status column. Checked here rather than in the engine so that it
        holds for every result, including one a strategy builds itself.
    """

    signal_id: str
    as_of: datetime
    _frame: pd.DataFrame
    definition: Mapping[str, object]

    def __post_init__(self) -> None:
        """Freeze the definition and refuse a frame that breaks the contract."""
        object.__setattr__(self, "definition", freeze(self.definition))
        frame = self._frame
        missing = [column for column in RESULT_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"{self.signal_id}: result is missing column(s) {', '.join(missing)}")
        if not frame.index.is_unique:
            repeated = sorted(frame.index[frame.index.duplicated()].unique())
            raise ValueError(
                f"{self.signal_id}: result holds {', '.join(map(str, repeated))} more than once"
            )
        wrong = [status for status in frame["status"] if not isinstance(status, SignalStatus)]
        if wrong:
            raise ValueError(
                f"{self.signal_id}: result holds a status that is not a SignalStatus: {wrong[0]!r}"
            )

    @property
    def frame(self) -> pd.DataFrame:
        """Return the answer, diagnostics included, as a frame of the caller's own.

        Returns
        -------
        pd.DataFrame
            A deep copy. A strategy may add a column to it, sort it or write
            into it without any of that reaching the result it came from, and
            without two strategies reading the same snapshot interfering.
        """
        return self._frame.copy(deep=True)

    def value(self, instrument_id: str) -> float:
        """Return one instrument's number, ``NaN`` when it has none."""
        return float(self._frame.loc[instrument_id, "value"])

    def status(self, instrument_id: str) -> SignalStatus:
        """Return why one instrument's number is what it is."""
        status = self._frame.loc[instrument_id, "status"]
        assert isinstance(status, SignalStatus)
        return status

    def instruments(self) -> tuple[str, ...]:
        """Return the instruments this result speaks about, in order."""
        return tuple(str(name) for name in self._frame.index)

    def ok(self) -> pd.DataFrame:
        """Return the rows a strategy may use, dropping the ones it may not.

        Returns
        -------
        pd.DataFrame
            The subset whose status is ``OK``, as a frame of the caller's own.
            Keeping the diagnostics: a caller that wants to know how many
            instruments it lost, and why, reads :attr:`frame` instead.
        """
        usable = self._frame.loc[self._frame["status"] == SignalStatus.OK]
        return usable.copy(deep=True)


def empty_result_frame() -> pd.DataFrame:
    """Return an empty frame with the result columns and their dtypes."""
    return pd.DataFrame(
        {
            "value": pd.Series(dtype="float64"),
            "status": pd.Series(dtype="object"),
            "input_start_date": pd.Series(dtype="object"),
            "input_end_date": pd.Series(dtype="object"),
            "observations_used": pd.Series(dtype="Int64"),
            "max_input_age_sessions": pd.Series(dtype="Int64"),
        },
        index=pd.Index([], dtype="object", name="instrument_id"),
    )


def result_row(value: float | None, window: LoadedWindow) -> dict[str, object]:
    """Return the row describing one instrument's outcome.

    Parameters
    ----------
    value : float | None
        The number, or ``None`` when the window did not allow one.
    window : LoadedWindow
        What the window loader returned, status included.

    Returns
    -------
    dict[str, object]
        One row of :data:`RESULT_COLUMNS`.
    """
    used: int | None = len(window.points) if window.points else None
    start: date | None = window.dates[0] if window.dates else None
    end: date | None = window.dates[-1] if window.dates else None
    return {
        "value": float("nan") if value is None else float(value),
        "status": window.status,
        "input_start_date": start,
        "input_end_date": end,
        "observations_used": used,
        "max_input_age_sessions": window.age_sessions,
    }


def build_result_frame(rows: Mapping[str, Mapping[str, object]]) -> pd.DataFrame:
    """Assemble one row per instrument into the canonical result frame.

    Parameters
    ----------
    rows : Mapping[str, Mapping[str, object]]
        One row per instrument id, in the order they were asked for.

    Returns
    -------
    pd.DataFrame
        Indexed by ``instrument_id``, columns in :data:`RESULT_COLUMNS` order,
        with the dtypes of :func:`empty_result_frame`.
    """
    if not rows:
        return empty_result_frame()
    frame = pd.DataFrame(
        [dict(row) for row in rows.values()],
        index=pd.Index(list(rows), dtype="object", name="instrument_id"),
        columns=list(RESULT_COLUMNS),
    )
    return frame.astype(
        {
            "value": "float64",
            "observations_used": "Int64",
            "max_input_age_sessions": "Int64",
        }
    )


def require_positive_int(value: int, name: str) -> None:
    """Raise unless ``value`` is a positive integer.

    Parameters
    ----------
    value : int
        Parameter to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not. A window of zero or of ``"20"`` is a configuration
        mistake, and it stops the run rather than producing a status: no
        instrument would have been computed correctly either.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


def require_non_negative_int(value: int, name: str) -> None:
    """Raise unless ``value`` is a non-negative integer.

    Parameters
    ----------
    value : int
        Parameter to check.
    name : str
        Its name, quoted in the message.

    Raises
    ------
    ValueError
        If it is not.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")


class Signal(ABC):
    """One quantity, computed the same way for every instrument it is asked about.

    A signal is configuration plus a formula. Its configuration is immutable and
    fully described by :meth:`definition`, so that a number in a backtest can be
    traced back to exactly what produced it.
    """

    signal_id: str
    """Stable name of this instance, e.g. ``"momentum_60d"``.

    Declared as an annotation and not as an abstract property on purpose: every
    signal is a frozen dataclass, and a property here would become the field's
    default value.
    """

    @abstractmethod
    def definition(self) -> Mapping[str, object]:
        """Return every parameter that changes the number, serialisable.

        Returns
        -------
        Mapping[str, object]
            JSON-serialisable, and complete: two instances with equal
            definitions must compute the same thing.
        """

    @abstractmethod
    def compute(self, context: SignalContext, instrument_ids: Sequence[str]) -> SignalResult:
        """Compute the signal for these instruments at the context's instant.

        Parameters
        ----------
        context : SignalContext
            Environment of the decision.
        instrument_ids : Sequence[str]
            Instruments to compute for, in the order they will appear.

        Returns
        -------
        SignalResult
            One row per instrument, whether or not it has a number.
        """

    def compute_window(
        self,
        context: SignalContext,
        instrument_ids: Sequence[str],
        *,
        spec: WindowSpec,
        bar_field: BarField,
        basis: PriceBasis,
        max_age_sessions: int,
        formula: Callable[[LoadedWindow], float | None],
    ) -> SignalResult:
        """Run one window-based formula over several instruments.

        Parameters
        ----------
        context : SignalContext
            Environment of the decision.
        instrument_ids : Sequence[str]
            Instruments to compute for, in order.
        spec : WindowSpec
            Window every instrument is asked for.
        bar_field : BarField
            Field to read.
        basis : PriceBasis
            Raw prices or adjusted ones.
        max_age_sessions : int
            Largest accepted age of the freshest input.
        formula : Callable[[LoadedWindow], float | None]
            Turns an ``OK`` window into a number, or ``None`` when these
            particular numbers make the formula meaningless - a zero
            denominator, a non-positive price under a logarithm. That is
            ``INVALID_INPUT``, and it is the only case the formula decides.

        Returns
        -------
        SignalResult
            One row per instrument, whether or not it has a number.

        Notes
        -----
        Nothing here catches a broad exception. An instrument with no data gets
        a status, because that is a case the contract foresees; a bug in a
        formula travels up and stops the run, because it is not.
        """
        rows: dict[str, Mapping[str, object]] = {}
        for instrument_id in instrument_ids:
            window = load_window(
                context,
                instrument_id,
                spec=spec,
                bar_field=bar_field,
                basis=basis,
                max_age_sessions=max_age_sessions,
            )
            if window.status is not SignalStatus.OK:
                rows[instrument_id] = result_row(None, window)
                continue
            value = formula(window)
            if value is None:
                rows[instrument_id] = result_row(
                    None, replace(window, status=SignalStatus.INVALID_INPUT)
                )
                continue
            rows[instrument_id] = result_row(value, window)
        return SignalResult(
            signal_id=self.signal_id,
            as_of=context.as_of,
            _frame=build_result_frame(rows),
            definition=self.definition(),
        )

    def fingerprint(self) -> str:
        """Return a stable hash of this instance's definition.

        Returns
        -------
        str
            SHA-256 of the definition rendered as canonical JSON. Two signals
            with the same fingerprint compute the same thing; the project's
            commit is what identifies the code that does it.
        """
        canonical = json.dumps(dict(self.definition()), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
