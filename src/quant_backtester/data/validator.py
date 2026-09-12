"""Validation of canonical frames before they reach the clean layer.

Rules are typed by instrument. Two rules that look universal are not:

- ``close > 0`` is false for a rate. The German 10-year yield was negative from
  2019 to 2022.
- a 50% daily move is not an anomaly on the VIX, which gained 115% on
  5 February 2018.

A rule that cries wolf is a rule that gets switched off, so each one is scoped to
the asset types where it means something.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

import pandas as pd

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.instruments import Instrument


class Severity(Enum):
    """How a validation issue is treated by the updater."""

    WARNING = "WARNING"
    """Logged; the write proceeds."""

    ERROR = "ERROR"
    """Logged; the write is aborted and the clean layer left untouched."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One problem found in a candidate frame.

    Attributes
    ----------
    code : str
        Stable machine-readable code, e.g. ``"OHLC_ORDER"``. Stable so the log
        stays queryable as messages are reworded.
    severity : Severity
        Whether the issue blocks the write.
    instrument_id : str
        Instrument concerned.
    observation_date : date | None
        Row concerned; ``None`` for a whole-frame issue.
    message : str
        Human-readable explanation.
    context : Mapping[str, object]
        Values that led to the issue, for the log.
    """

    code: str
    severity: Severity
    instrument_id: str
    observation_date: date | None
    message: str
    context: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Outcome of validating one instrument's frame.

    Attributes
    ----------
    instrument_id : str
        Instrument concerned.
    issues : Sequence[ValidationIssue]
        Everything found, in row order.
    """

    instrument_id: str
    issues: Sequence[ValidationIssue]

    @property
    def valid(self) -> bool:
        """Return whether the frame may be written.

        Returns
        -------
        bool
            ``True`` when no issue has ``Severity.ERROR``.

        Notes
        -----
        Exercice 6.1 (trivial).
        """
        raise NotImplementedError("Exercice 6.1")

    @property
    def errors(self) -> list[ValidationIssue]:
        """Return the blocking issues.

        Returns
        -------
        list[ValidationIssue]
            Issues with ``Severity.ERROR``.

        Notes
        -----
        Exercice 6.1 (trivial).
        """
        raise NotImplementedError("Exercice 6.1")

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Return the non-blocking issues.

        Returns
        -------
        list[ValidationIssue]
            Issues with ``Severity.WARNING``.

        Notes
        -----
        Exercice 6.1 (trivial).
        """
        raise NotImplementedError("Exercice 6.1")


def validate_bars(
    instrument: Instrument, frame: pd.DataFrame, calendar: TradingCalendar
) -> ValidationReport:
    """Check a canonical bars frame.

    Parameters
    ----------
    instrument : Instrument
        Instrument the frame belongs to.
    frame : pd.DataFrame
        Candidate rows, already normalised.
    calendar : TradingCalendar
        Venue calendar, needed to tell a holiday from a hole.

    Returns
    -------
    ValidationReport
        Issues found.

    Notes
    -----
    Exercice 6.2 (le plus long du module, moyen). Regles a implementer, chacune
    avec son propre ``code`` :

    ERROR
        ``DATES_UNSORTED`` / ``DATE_DUPLICATE`` ; ``NON_SESSION`` (une seance qui
        n'existe pas au calendrier) ; ``OHLC_ORDER`` (``low <= open <= high`` et
        ``low <= close <= high``) ; ``NON_POSITIVE_PRICE``, mais uniquement pour
        ``AssetType`` ``ETF``, ``EQUITY``, ``INDEX`` - jamais pour un taux ;
        ``NEGATIVE_VOLUME`` ; ``AVAILABILITY_ORDER`` (``open_available_at_utc <
        close_available_at_utc``).

    WARNING
        ``SESSION_GAP`` (seances du calendrier sans ligne) ; ``EXTREME_MOVE``,
        avec un seuil dependant de l'``AssetType`` : 25% sur un ETF, mais aucun
        seuil utile sur la volatilite ; ``STALE_OPEN`` (voir exercice 6.3).

    Ne modifie jamais la frame ici. Un validateur qui corrige est un validateur
    qu'on ne peut plus auditer.
    """
    raise NotImplementedError("Exercice 6.2")


def check_stale_open(
    instrument: Instrument, frame: pd.DataFrame, window: int = 20, threshold: float = 0.3
) -> list[ValidationIssue]:
    """Flag opening prints that merely repeat the previous close.

    Parameters
    ----------
    instrument : Instrument
        Instrument the frame belongs to.
    frame : pd.DataFrame
        Canonical bars, chronologically sorted.
    window : int
        Rolling window, in sessions.
    threshold : float
        Fraction of the window above which the pattern is reported.

    Returns
    -------
    list[ValidationIssue]
        One issue per offending window.

    Notes
    -----
    Exercice 6.3 (moyen, et le plus rentable du module). Sur un ETF europeen peu
    liquide, Yahoo sert parfois un open egal au close de la veille : il n'y a pas
    eu de fixing exploitable. Comme l'open **est** notre prix d'execution, une
    strategie qui achete a ce prix realise un gain qui n'existe pas. C'est le
    type exact de mauvaise donnee qui fabrique un faux alpha : elle passe tous
    les autres controles.

    Un ``open == close`` isole est normal et ne doit rien declencher ; c'est la
    repetition qui est le signal.
    """
    raise NotImplementedError("Exercice 6.3")


def validate_levels(instrument: Instrument, frame: pd.DataFrame) -> ValidationReport:
    """Check a canonical levels frame.

    Parameters
    ----------
    instrument : Instrument
        Instrument the frame belongs to.
    frame : pd.DataFrame
        Candidate rows, already normalised.

    Returns
    -------
    ValidationReport
        Issues found.

    Notes
    -----
    Exercice 6.4 (facile). Dates triees, sans doublon, ``available_at_utc`` non
    nul et posterieur a ``observation_date``. Pas de controle de signe : un taux
    peut etre negatif, et c'est precisement le genre de regle "evidente" qui
    rendrait le Bund 2019-2022 inchargeable.
    """
    raise NotImplementedError("Exercice 6.4")


def validate_corporate_actions(instrument: Instrument, frame: pd.DataFrame) -> ValidationReport:
    """Check a canonical corporate actions frame.

    Parameters
    ----------
    instrument : Instrument
        Instrument the frame belongs to.
    frame : pd.DataFrame
        Candidate rows.

    Returns
    -------
    ValidationReport
        Issues found.

    Notes
    -----
    Exercice 6.5 (facile). Un ``SPLIT`` a un ratio strictement positif et
    different de 1 ; un ``DIVIDEND`` a un montant strictement positif. Deux
    actions du meme type a la meme ex-date sont une erreur.
    """
    raise NotImplementedError("Exercice 6.5")
