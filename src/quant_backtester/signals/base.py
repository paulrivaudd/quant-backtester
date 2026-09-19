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
import math
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from types import MappingProxyType
from typing import Final

import pandas as pd

from quant_backtester.data.schemas import BarField
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.types import (
    PriceBasis,
    SignalStatus,
    WindowSpec,
    require_identifier,
)
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


def unfreeze(value: object) -> object:
    """Return a value made of plain built-ins again, ready to be serialised.

    Parameters
    ----------
    value : object
        A frozen definition, or one of its parts.

    Returns
    -------
    object
        Dictionaries in place of read-only views and lists in place of tuples,
        all the way down. :func:`freeze` protects a definition from being
        edited; this turns it back into something ``json.dumps`` accepts, which
        is what recording an experiment beside its numbers needs.
    """
    if isinstance(value, Mapping):
        return {key: unfreeze(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [unfreeze(item) for item in value]
    return value


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
        If the signal has no name, or the frame does not hold the required
        columns, repeats an instrument, carries anything other than a
        :class:`SignalStatus` in its status column, holds a number beside a
        status that says there is none, or the other way round. Checked here
        rather than in the engine so that it holds for every result, including
        one a future model builds for itself.
    """

    signal_id: str
    as_of: datetime
    _frame: pd.DataFrame
    definition: Mapping[str, object]

    def __post_init__(self) -> None:
        """Take a copy of the frame, freeze the definition, and check both."""
        require_identifier(self.signal_id, "signal_id")
        object.__setattr__(self, "definition", freeze(self.definition))
        # A copy, and not the caller's object. A signal that kept a reference
        # to the frame it built could otherwise rewrite a result after handing
        # it over, and the snapshot would be immutable only through its own API.
        object.__setattr__(self, "_frame", self._frame.copy(deep=True))
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
        self._require_value_matches_status(frame)
        self._require_sensible_diagnostics(frame)

    def _require_value_matches_status(self, frame: pd.DataFrame) -> None:
        """Refuse a row whose number and whose status say different things.

        Raises
        ------
        ValueError
            If a row is ``OK`` without a finite number, or carries a number
            although it is not ``OK``.

        Notes
        -----
        The pair is the whole contract of a result, and nothing downstream
        re-checks it. A cross-section that counts an ``OK`` row holding ``NaN``
        believes it is ranking three instruments while pandas can only rank
        two, and normalises by a size one too large: the best name comes out at
        0.5 instead of 1.0, in the right order and on the wrong scale. A
        strategy taking the top few is unaffected; one with a threshold quietly
        holds nothing.

        The other direction matters as much. A number travelling beside
        ``MISSING_INPUT`` is a number nobody vouched for, and the statuses
        exist so that it cannot be used by accident.
        """
        for name, value, status in zip(frame.index, frame["value"], frame["status"], strict=True):
            # A missing number may arrive as a float NaN or as pandas' own
            # missing value, depending on how the frame was built. Both say the
            # same thing: there is no number here.
            number = float("nan") if value is pd.NA or value is None else float(value)
            if status is SignalStatus.OK:
                if not math.isfinite(number):
                    raise ValueError(
                        f"{self.signal_id}: {name} is OK but its value is {number}; a status "
                        f"of OK is what says a number can be used"
                    )
            elif math.isfinite(number):
                raise ValueError(
                    f"{self.signal_id}: {name} is {status.value} and still carries "
                    f"{number}; a value nobody vouched for must not travel"
                )

    def _require_sensible_diagnostics(self, frame: pd.DataFrame) -> None:
        """Refuse a count of observations or an age that cannot describe anything.

        Raises
        ------
        ValueError
            If either diagnostic is negative where it is present.
        """
        for column in ("observations_used", "max_input_age_sessions"):
            for name, diagnostic in zip(frame.index, frame[column], strict=True):
                if diagnostic is pd.NA or diagnostic is None:
                    continue
                # A frame built by hand can hold a float NaN here rather than
                # the Int64 missing value, and neither says anything wrong.
                count = float(diagnostic)
                if math.isfinite(count) and count < 0:
                    raise ValueError(
                        f"{self.signal_id}: {column} is {diagnostic} for {name}; "
                        f"it counts something"
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

    def definition_json(self) -> dict[str, object]:
        """Return the definition as plain built-ins, ready to be serialised.

        Returns
        -------
        dict[str, object]
            The same content as :meth:`definition`, made of dictionaries, lists
            and scalars, so that ``json.dumps`` accepts it. The frozen form
            protects the definition from being edited; recording an experiment
            needs one that can be written down.
        """
        thawed = unfreeze(self.definition())
        assert isinstance(thawed, dict)
        return thawed

    def fingerprint(self) -> str:
        """Return a stable hash of this instance's definition.

        Returns
        -------
        str
            SHA-256 of the definition rendered as canonical JSON. Two signals
            with the same fingerprint compute the same thing; the project's
            commit is what identifies the code that does it.

        Notes
        -----
        Taken of :meth:`definition_json` rather than of the definition itself,
        so that a composite signal carrying a frozen definition inside its own
        - what a result hands back - can still be hashed. The rendering is the
        same either way: ``json.dumps`` writes a tuple as a list already.
        """
        canonical = json.dumps(self.definition_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
