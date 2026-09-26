"""Ingestion: download, normalise, validate, store.

Kept deliberately apart from :mod:`quant_backtester.data.reader` so that the
backtester, which only ever receives a reader, is physically unable to reach the
network mid-run.

The pipeline for one instrument::

    registry -> source.download -> repository.save_raw (immutable)
             -> normalizer     -> validator
             -> merge under the revision policy
             -> repository.save_clean (atomic)

One writer at a time, enforced: every write the repository makes holds the
store's lock, and a second writer is refused with ``StoreBusy``. A promotion
rewrites several files - the bars, each check source's series, the checked
series, the actions, the journal of applied fetches - and does so as one
repository transaction, so the set is published whole or not at all, and a
promotion that finds its own result invalid throws every write away.
:meth:`MarketDataUpdater.update` still checks that the checked series matches
the bars before building on them, and :meth:`rebuild_clean` repairs a series
from the archive.

Three rules decide what this module may and may not do to stored history.

**Nothing is promoted while an error stands.** The raw snapshot is archived
first, because a download that fails validation is precisely the one to
re-examine, and ``clean/`` is left exactly as it was.

**Stored values win.** A refetch that disagrees with history is logged as a
revision and dropped, unless that exact field and date were reviewed into
``metadata/accepted_revisions.toml``. Corporate actions follow the same rule
without the exception: an action already stored is never rewritten, since a
reviewed acceptance covers bars and levels only.

**The checked layer is written for every BAR instrument**, single-source ones
included - it is what the reader serves. A session keeps the verdict it was
given unless this fetch brings fresh rows for it, so a past cross-check outcome
never moves on its own.

Only one wall-clock read exists here, in :meth:`MarketDataUpdater.update`, to
decide how far to fetch - and it decides it through :func:`safe_end_date`, so
the hour a script happens to run at cannot turn a session still trading into a
stored bar. Everything else is stamped with the fetch's own
``retrieved_at_utc``, which is what makes :meth:`MarketDataUpdater.rebuild_clean`
able to reproduce ``clean/`` byte for byte from the archive alone - and what
makes the normalizer's refusal of an unpublished row hold on a replay too.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pandas as pd

from quant_backtester.data.bar_corrections import BarCorrection, BarCorrections
from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.corporate_actions import ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy, cross_check_bars
from quant_backtester.data.instruments import (
    DataType,
    Instrument,
    InstrumentRegistry,
    PublicationRule,
    VintagePolicy,
)
from quant_backtester.data.normalizer import NormalizedData, Normalizer
from quant_backtester.data.repository import MarketDataRepository, TransactionDoomed
from quant_backtester.data.revisions import (
    AcceptedRevisions,
    detect_revisions,
    merge_with_policy,
)
from quant_backtester.data.schemas import BARS_SCHEMA, LEVELS_SCHEMA, VINTAGES_SCHEMA, CheckStatus
from quant_backtester.data.sources.base import (
    DataSource,
    ProviderError,
    ProviderRangeUnavailable,
    ProviderResponseError,
    RawDownload,
    utc_now,
)
from quant_backtester.data.validator import (
    Severity,
    ValidationIssue,
    ValidationReport,
    bar_row_issues,
    validate_bars,
    validate_corporate_actions,
    validate_levels,
)

BAR_VALUE_COLUMNS: Final[tuple[str, ...]] = ("open", "high", "low", "close", "volume")
"""Bar columns the revision policy governs. Availability and lineage are not values."""

_REPAIR_HINT = (
    "rebuild_clean({instrument_id!r}) recomputes the whole clean layer from raw/ "
    "and the committed configuration."
)
"""What to do about an inconsistent clean layer, said the same way everywhere."""

MAX_UNPUBLISHED_DAYS: Final[int] = 30
"""Longest run of days walked back looking for a published observation.

A same-day rule needs one step, a D+1 rule over a holiday week a handful.
Running past it means the publication rule is wrong, not that a publisher went
quiet for a month.
"""


def _fetched_pairs(
    downloads: Mapping[str, RawDownload], actions: RawDownload | None
) -> list[tuple[str, str]]:
    """Return the ``(source, fetch_id)`` pairs one fetch archived."""
    pairs = [(source_id, download.fetch_id) for source_id, download in downloads.items()]
    if actions is not None:
        pairs.append((actions.source, actions.fetch_id))
    return sorted(pairs)


@dataclass(frozen=True, slots=True)
class HistoryCoverage:
    """How much of one instrument's declared history the store actually holds.

    Attributes
    ----------
    instrument_id : str
        Instrument measured.
    declared_from : date | None
        Its ``first_session``, or ``None`` when the registry does not say.
    declared_until : date
        Its ``last_session`` when it was delisted, otherwise the last
        observation that is published today.
    stored_from, stored_until : date | None
        Span of the clean series, ``None`` when nothing is stored.
    raw_fetches : int
        Archived provider responses across every source. A name with fetches
        and no clean series was downloaded and refused, which is not the same
        problem as a name nobody ever fetched.
    missing_sessions : tuple[date, ...] | None
        For a ``BAR``, every session of its venue inside the window it is
        measured over that has no stored bar - inside the span as well as
        before and after it. ``None`` for a published series: its release
        calendar is not a venue's, and one is not invented to count against.
    contested_sessions : tuple[date, ...] | None
        For a ``BAR``, the stored sessions the cross-check marked
        ``CONFLICT``: present on disk, and served as holes. ``None`` for a
        published series.
    """

    instrument_id: str
    declared_from: date | None
    declared_until: date
    stored_from: date | None
    stored_until: date | None
    raw_fetches: int
    missing_sessions: tuple[date, ...] | None = None
    contested_sessions: tuple[date, ...] | None = None

    @property
    def spans_declared_window(self) -> bool:
        """Return whether the stored span reaches both ends of the declared window.

        Only the ends: a series stored on the first and the last day and on
        nothing between spans its window. Named for what it checks, which is
        what ``complete`` used to check under a stronger name (audit A12).
        """
        if self.stored_from is None or self.stored_until is None:
            return False
        starts = self.declared_from is None or self.stored_from <= self.declared_from
        return starts and self.stored_until >= self.declared_until

    @property
    def complete(self) -> bool:
        """Return whether the store holds every session it should.

        Returns
        -------
        bool
            For a ``BAR``: the span reaches both ends and no session inside it
            is missing. Contested sessions do not make it incomplete - they are
            stored - and are reported beside it. For a published series, only
            :attr:`spans_declared_window` can be said, and that is what this
            returns; :attr:`missing_sessions` being ``None`` is how a reader
            knows the inside was not checked.
        """
        if not self.spans_declared_window:
            return False
        return self.missing_sessions is None or not self.missing_sessions

    @property
    def missing_head(self) -> tuple[date, date] | None:
        """Return the declared range before the first stored observation."""
        if self.declared_from is None:
            return None
        if self.stored_from is None:
            return (self.declared_from, self.declared_until)
        if self.stored_from <= self.declared_from:
            return None
        return (self.declared_from, self.stored_from)

    @property
    def missing_tail(self) -> tuple[date, date] | None:
        """Return the declared range after the last stored observation."""
        if self.stored_until is None or self.stored_until >= self.declared_until:
            return None
        return (self.stored_until, self.declared_until)


def _vintage_availability(
    rule: PublicationRule, calendar: TradingCalendar | None, vintage_at: datetime
) -> Callable[[date], datetime]:
    """Return when a row of one vintage became public.

    The later of the observation's own release and the vintage's: a number
    restated in June 2021 was not knowable in 2019, whatever quarter it
    describes, and a vintage of a day carries observations released that
    morning, which were not knowable the evening before.
    """

    def available_at(day: date) -> datetime:
        return max(rule.available_at(day, calendar), vintage_at)

    return available_at


def _vintage_cell(row: Mapping[str, Any]) -> float | None:
    """Return a vintage row's value, or ``None`` for a withdrawal."""
    return None if bool(row["withdrawn"]) else float(row["value"])


def _withdrawal_issues(instrument: Instrument, frame: pd.DataFrame) -> list[ValidationIssue]:
    """Return an error for every vintage row whose value and withdrawal disagree.

    A withdrawal carries no value, and a row that is not one carries a value
    (the level rules check that it is a finite one).
    """
    withdrawn = frame["withdrawn"].astype(bool)
    contradictory = frame.loc[withdrawn & frame["value"].notna()]
    return [
        _issue(
            "WITHDRAWAL_WITH_VALUE",
            Severity.ERROR,
            instrument.id,
            row["observation_date"],
            f"{instrument.id} {row['observation_date']} is withdrawn in the vintage of "
            f"{row['vintage_date']} and still carries {row['value']}",
        )
        for row in _records(contradictory)
    ]


def clean_table(instrument: Instrument) -> str:
    """Return the clean table an instrument's series is stored in.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned.

    Returns
    -------
    str
        ``"bars"`` for a ``BAR``; ``"vintages"`` for a published series read
        as of each decision, stored one row per vintage it was restated in;
        ``"levels"`` for any other published series. The one place the choice
        is made.
    """
    if instrument.data_type is DataType.BAR:
        return "bars"
    if instrument.vintage_policy is VintagePolicy.AS_OF_DECISION:
        return "vintages"
    return "levels"


def _canonical_frame(instrument: Instrument, data: NormalizedData) -> pd.DataFrame | None:
    """Return the frame an instrument's own kind of series is stored as."""
    table = clean_table(instrument)
    if table == "bars":
        return data.bars
    if table == "vintages":
        return data.vintages
    return data.levels


def _corrected_bar_issue(
    instrument: Instrument, source_id: str, correction: BarCorrection
) -> ValidationIssue:
    """Report a bar a reviewed correction dropped.

    A warning rather than an error: the decision was taken on purpose, and the
    series must still be written. What it must not do is happen in silence - a
    row removed by a config file nobody reads is indistinguishable from a
    provider that never sent it.
    """
    return _issue(
        "REVIEWED_BAR_DROPPED",
        Severity.WARNING,
        instrument.id,
        correction.session_date,
        f"{source_id}'s bar for {instrument.id} on {correction.session_date} was dropped "
        f"by a reviewed correction ({correction.defect.value}): {correction.reason}",
    )


def safe_end_date(
    instrument: Instrument, calendar: TradingCalendar | None, now_utc: datetime
) -> date:
    """Return the latest observation date entirely published at ``now_utc``.

    Parameters
    ----------
    instrument : Instrument
        Instrument to fetch.
    calendar : TradingCalendar | None
        Venue calendar of a ``BAR``; for a ``LEVEL``, the calendar its
        publication rule counts its lag on, and ``None`` for a same-day release.
    now_utc : datetime
        Timezone-aware instant the fetch is planned at.

    Returns
    -------
    date
        Last session whose close is already published, for a ``BAR``; last
        observation date whose release time has passed, for a ``LEVEL``.

    Raises
    ------
    ValueError
        If ``now_utc`` is naive, a ``BAR`` has no calendar, a ``LEVEL`` has no
        publication rule, or no published observation is found within
        ``MAX_UNPUBLISHED_DAYS`` days.

    Notes
    -----
    Asking a provider for today is asking for whatever it has so far. A daily
    bar downloaded at noon is a session still running, and the pipeline would
    stamp it with the official closing instant and store it as canonical - the
    first value stored wins, so the real close that evening would then arrive as
    a revision and be refused. The guard belongs here rather than in the human
    workflow: a script run at the wrong hour must not be able to change history.

    The rule mirrors availability exactly. A bar is whole at the closing
    auction, which is what ``close_available_at_utc`` records, so the last
    fetchable session is the last one that has closed. A published level is
    whole at its release instant, lag included.

    A delisted instrument stops at its declared ``last_session``. Asking a
    provider for what came after is asking for rows that do not exist, or for
    whatever it decided to serve in their place.
    """
    if now_utc.tzinfo is None:
        raise ValueError(f"now_utc must be timezone-aware, got {now_utc!r}")
    today = now_utc.astimezone(UTC).date()
    if instrument.last_session is not None and instrument.last_session < today:
        today = instrument.last_session
    if instrument.data_type is DataType.BAR:
        if calendar is None:
            raise ValueError(f"BAR instrument {instrument.id} has no calendar")
        session = calendar.session(today)
        while session is None or session.close_utc > now_utc:
            session = calendar.previous_session(today if session is None else session.session_date)
        return session.session_date
    rule = instrument.publication_rule
    if rule is None:
        raise ValueError(f"LEVEL instrument {instrument.id} has no publication rule")
    day = today
    for _ in range(MAX_UNPUBLISHED_DAYS):
        if rule.available_at(day, calendar) <= now_utc:
            return day
        day -= timedelta(days=1)
    raise ValueError(
        f"{instrument.id}: nothing published within {MAX_UNPUBLISHED_DAYS} days of {today}"
    )


LEVEL_VALUE_COLUMNS: Final[tuple[str, ...]] = ("value",)
"""The only value a level carries."""

REBASE_FIELDS: Final[tuple[str, ...]] = ("open", "high", "low", "close")
"""Fields the rebasing guard compares.

Volume is excluded on purpose: a split rebases prices by ``1 / r`` and volumes by
``r``, so mixing the two would hide the very pattern the guard looks for.
"""

REBASE_REL_TOLERANCE: Final = 1e-4
"""How far two ratios may differ and still count as the same constant factor.

Wide enough to absorb a provider's rounding, far below any real price move.
"""

MIN_REBASE_DATES: Final = 2
"""Overlapping dates required before a constant factor means anything."""

MIN_REBASE_VALUES: Final = 4
"""Compared values required, for the same reason."""


def _issue(
    code: str,
    severity: Severity,
    instrument_id: str,
    observation_date: date | None,
    message: str,
    context: Mapping[str, object] | None = None,
) -> ValidationIssue:
    """Build one issue raised by the updater rather than by a validation rule."""
    return ValidationIssue(
        code=code,
        severity=severity,
        instrument_id=instrument_id,
        observation_date=observation_date,
        message=message,
        context=context or {},
    )


class _PromotionRefused(Exception):
    """Raised inside a promotion's transaction to undo every write it made.

    Carries the issues the report must still show: what the promotion had
    found before it was refused, and why it was.
    """

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        super().__init__(f"{len(issues)} issue(s)")
        self.issues = list(issues)


def _merged_bar_errors(
    instrument: Instrument, source_id: str, merged: pd.DataFrame, incoming: pd.DataFrame
) -> list[ValidationIssue]:
    """Return what is wrong with a bar the merge put together from two fetches.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned.
    source_id : str
        Source whose canonical series ``merged`` is.
    merged : pd.DataFrame
        That series after the revision policy was applied.
    incoming : pd.DataFrame
        What this fetch brought, already validated on its own.

    Returns
    -------
    list[ValidationIssue]
        One ``MERGED_BAR_INVALID`` error per session the fetch touched whose
        merged bar breaks a row rule, naming the rules it breaks.

    Notes
    -----
    The stored bar was valid and so was the incoming one, but the policy takes
    them field by field: an accepted open of 120 kept beside a stored high of
    100 is a bar nobody served. Only the sessions this fetch brought can have
    been assembled that way, so only they are judged.
    """
    touched = incoming["session_date"]
    errors: list[ValidationIssue] = []
    for row in _records(merged.loc[merged["session_date"].isin(touched)]):
        broken = [
            issue for issue in bar_row_issues(instrument, row) if issue.severity is Severity.ERROR
        ]
        if broken:
            day = row["session_date"]
            errors.append(
                _issue(
                    "MERGED_BAR_INVALID",
                    Severity.ERROR,
                    instrument.id,
                    day,
                    f"{instrument.id} {source_id} bar of {day} would be stored as "
                    f"{', '.join(issue.code for issue in broken)} once the accepted "
                    "revisions are applied to it field by field; the promotion is "
                    "refused rather than store a bar no source served",
                    {
                        "source": source_id,
                        "rules": [issue.code for issue in broken],
                        **{field: row[field] for field in BAR_VALUE_COLUMNS},
                    },
                )
            )
    return errors


def _secondary_only_sessions(
    instrument: Instrument, primary: pd.DataFrame, frames: Mapping[str, pd.DataFrame]
) -> list[ValidationIssue]:
    """Report the sessions a check source brought that the primary does not hold.

    Parameters
    ----------
    instrument : Instrument
        Instrument concerned.
    primary : pd.DataFrame
        The primary source's canonical series after this fetch was merged.
    frames : Mapping[str, pd.DataFrame]
        What this fetch brought, per source.

    Returns
    -------
    list[ValidationIssue]
        One ``SECONDARY_ONLY_SESSION`` warning per such session, naming the
        check sources that hold it, in date order.

    Notes
    -----
    Such a session is kept in the check source's own series and is not served:
    the checked series covers the primary's sessions and no others (decision
    D8 of the 2026-09-26 audit). It is reported only when a fetch brings it, so
    a hole is said once and not at every update.
    """
    held = set(primary["session_date"])
    only: dict[date, list[str]] = {}
    for check in instrument.check_sources:
        frame = frames.get(check.source)
        if frame is None:
            continue
        for day in sorted(set(frame["session_date"]) - held):
            only.setdefault(day, []).append(check.source)
    return [
        _issue(
            "SECONDARY_ONLY_SESSION",
            Severity.WARNING,
            instrument.id,
            day,
            f"{instrument.id} session {day} is held by {', '.join(sources)} and not by the "
            f"primary source {instrument.primary_source}; it is stored as a second opinion "
            "and not served",
            {"sources": sources},
        )
        for day, sources in sorted(only.items())
    ]


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return a frame as plain dictionaries, with string keys."""
    return [
        {str(column): value for column, value in record.items()}
        for record in frame.to_dict("records")
    ]


def _verdict_of(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return one checked row's verdict: its status and the fields it contests."""
    return str(row["check_status"]), str(row["conflicting_fields"])


def _verdict_label(verdict: tuple[str, str]) -> str:
    """Return a verdict as one readable phrase for the log."""
    status, conflicting = verdict
    return f"{status} on {conflicting}" if conflicting else status


def _rebasing_factor(
    stored: pd.DataFrame, incoming: pd.DataFrame, key_column: str, fields: Sequence[str]
) -> float | None:
    """Return the constant factor the provider rebased a series by, if it did.

    Parameters
    ----------
    stored : pd.DataFrame
        Rows already in the clean layer.
    incoming : pd.DataFrame
        Freshly normalised rows covering the overlap.
    key_column : str
        Date column joining the two.
    fields : Sequence[str]
        Value columns to compare.

    Returns
    -------
    float | None
        The factor when every compared value moved by the same one and it is not
        ``1``; ``None`` otherwise - including when the evidence is too thin
        (:data:`MIN_REBASE_DATES`, :data:`MIN_REBASE_VALUES`) or a value is
        missing or zero on one side.

    Notes
    -----
    The point is to tell a restatement from a revision. One close corrected by a
    cent is a revision; every price of the overlap divided by exactly four is a
    change of basis, and merging a window of it into an old series would invent
    a -75% move in the middle of the history that passes every other check.
    """
    stored_rows = {row[key_column]: row for row in _records(stored)}
    incoming_rows = {row[key_column]: row for row in _records(incoming)}
    shared = sorted(set(stored_rows) & set(incoming_rows))
    ratios: list[float] = []
    for observation_date in shared:
        for field in fields:
            old = float(stored_rows[observation_date][field])
            new = float(incoming_rows[observation_date][field])
            if not (math.isfinite(old) and math.isfinite(new)) or old == 0.0:
                # A value that appeared, vanished or sits at zero says nothing
                # about a factor; the plain revision path deals with it.
                continue
            ratios.append(new / old)
    if len(shared) < MIN_REBASE_DATES or len(ratios) < MIN_REBASE_VALUES:
        return None
    factor = ratios[0]
    if any(not math.isclose(ratio, factor, rel_tol=REBASE_REL_TOLERANCE) for ratio in ratios):
        return None
    if math.isclose(factor, 1.0, rel_tol=REBASE_REL_TOLERANCE):
        return None
    return factor


class MarketDataUpdater:
    """Fetch and refresh the market data tree.

    Parameters
    ----------
    repository : MarketDataRepository
        Storage to write to.
    instruments : InstrumentRegistry
        Instrument registry.
    calendars : CalendarRegistry
        Calendar registry.
    sources : Mapping[str, DataSource]
        Adapters, keyed by source identifier.
    normalizers : Mapping[str, Normalizer]
        Normalizers, keyed by source identifier.
    accepted_revisions : AcceptedRevisions
        Reviewed decisions to apply.
    action_corrections : ActionCorrections
        Reviewed decisions about what a mislabelled corporate action really was,
        declared in ``metadata/corporate_actions.toml``. Required for the same
        reason the accepted revisions are: an empty set is a state someone chose,
        not a default.
    bar_corrections : BarCorrections
        Reviewed decisions to drop a bar a provider sent broken, declared in
        ``metadata/bar_corrections.toml``. Required for the same reason, and
        applied where the raw becomes canonical, so the live path and a replay
        of the archive reach the same series.
    cross_check_policy : CrossCheckPolicy
        Tolerances deciding when two sources agree, declared in
        ``metadata/crosscheck.toml``. Required, and passed in like the accepted
        revisions: it decides which bars a strategy is allowed to see, so it is
        committed configuration rather than a default living in code.
    overlap_sessions : int
        How far back an update re-fetches, to detect provider revisions.
    clock : Callable[[], datetime]
        Wall-clock source, read by :meth:`update` alone to know where "now" is.
        Injected so tests are deterministic.

    Raises
    ------
    ValueError
        If ``overlap_sessions`` is negative.
    """

    def __init__(
        self,
        repository: MarketDataRepository,
        instruments: InstrumentRegistry,
        calendars: CalendarRegistry,
        sources: Mapping[str, DataSource],
        normalizers: Mapping[str, Normalizer],
        accepted_revisions: AcceptedRevisions,
        action_corrections: ActionCorrections,
        bar_corrections: BarCorrections,
        cross_check_policy: CrossCheckPolicy,
        overlap_sessions: int = 5,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if overlap_sessions < 0:
            raise ValueError(f"overlap_sessions must be zero or more, got {overlap_sessions}")
        self._repository = repository
        self._instruments = instruments
        self._calendars = calendars
        self._sources = dict(sources)
        self._normalizers = dict(normalizers)
        self._accepted_revisions = accepted_revisions
        self._action_corrections = action_corrections
        self._bar_corrections = bar_corrections
        self._cross_check_policy = cross_check_policy
        self._overlap_sessions = overlap_sessions
        self._clock = clock

    def download(self, instrument_id: str, start: date, end: date) -> ValidationReport:
        """Fetch an instrument over a range and build its clean series.

        Parameters
        ----------
        instrument_id : str
            Instrument to fetch.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        ValidationReport
            Issues found. Nothing is written to ``clean/`` when it is invalid;
            the raw snapshot is archived regardless, since it is evidence.

        Raises
        ------
        ValueError
            If ``start`` is after ``end``, or the clean layer was left half
            written by an interrupted run.
        KeyError
            If the instrument, one of its sources, one of its normalizers or its
            calendar is not registered.

        Notes
        -----
        Exercice 9.2 (moyen). Enchaine le pipeline du docstring de module. Note
        l'ordre : ``save_raw`` a lieu **avant** la validation. Un telechargement
        invalide est precisement celui qu'on voudra reexaminer.

        Every source of the instrument is fetched, primary and check sources
        alike, plus its corporate actions when the primary source has them.
        """
        instrument = self._instruments.get(instrument_id)
        if start > end:
            raise ValueError(f"{instrument_id}: start {start} is after end {end}")
        self._require_consistent_clean(instrument)
        downloads, actions_download, fetch_issues = self._fetch(instrument, start, end)
        frames, actions, issues = self._normalize_all(instrument, downloads, actions_download)
        return self._ingest(
            instrument,
            frames,
            actions,
            fetch_id=downloads[instrument.primary_source].fetch_id,
            checked_at=downloads[instrument.primary_source].retrieved_at_utc,
            requested=(start, end),
            extra_issues=fetch_issues + issues,
            fetches=_fetched_pairs(downloads, actions_download),
        )

    def update(self, instrument_id: str) -> ValidationReport:
        """Extend an instrument's clean series with recent sessions.

        Parameters
        ----------
        instrument_id : str
            Instrument to refresh.

        Returns
        -------
        ValidationReport
            Issues found.

        Raises
        ------
        ValueError
            If the instrument has no stored data and no ``first_session`` to
            start from, or if the range to fetch ends before it starts.

        Notes
        -----
        Exercice 9.3 (difficile - c'est ici que le bug classique se loge).

        Re-telecharge depuis ``last_date - overlap_sessions`` seances, puis
        fusionne via ``merge_with_policy``.

        **Le piege.** Le recouvrement detecte les revisions ponctuelles, mais ne
        peut rien contre un restatement retroactif : apres un split 4:1, le
        fournisseur reecrit *tout* l'historique. Fusionner cinq jours de
        nouvelles valeurs dans un stock reste a l'ancienne base fabrique un
        -75% fictif au milieu de la serie - qui passe tous les controles, parce
        que les dates sont triees, sans doublon, et les prix positifs.

        Comme on ne stocke que des prix bruts, le cas ne devrait pas se produire.
        Mais un fournisseur qui change silencieusement de convention, si. Donc :
        si les valeurs de recouvrement different de l'ancien stock par un
        **facteur constant**, ce n'est pas une revision, c'est un changement de
        base - refetch integral de l'instrument et signalement, jamais une
        fusion partielle.

        The full refetch is archived under ``raw/`` and nothing else happens:
        the clean layer stays on its old basis until someone reviews the
        evidence and rebuilds. Promoting the new basis silently would be the
        same bug the guard exists to prevent, one order of magnitude larger.
        """
        instrument = self._instruments.get(instrument_id)
        self._require_consistent_clean(instrument)
        key_column = self._key_column(instrument)
        stored = self._stored_frame(instrument)
        last = instrument.last_session
        if last is not None and not stored.empty and max(stored[key_column]) >= last:
            raise ValueError(
                f"{instrument_id} was delisted on {last} and its series already reaches "
                "it; there is nothing left to extend. A delisted name is read from the "
                "archive - rebuild it rather than asking a provider what it serves for a "
                "ticker that has been reused."
            )
        end = safe_end_date(instrument, self._calendar_of(instrument), self._clock())
        if stored.empty:
            if instrument.first_session is None:
                raise ValueError(
                    f"{instrument_id}: nothing stored and no first_session to start from"
                )
            start = instrument.first_session
        else:
            # Distinct dates: a vintage archive holds one row per vintage.
            dates = sorted(set(stored[key_column]))
            start = dates[max(0, len(dates) - 1 - self._overlap_sessions)]
        if start > end:
            raise ValueError(
                f"{instrument_id}: the clock says {end}, before the range start {start}"
            )

        downloads, actions_download, fetch_issues = self._fetch(instrument, start, end)
        frames, actions, issues = self._normalize_all(instrument, downloads, actions_download)
        issues = fetch_issues + issues
        primary = downloads[instrument.primary_source]
        incoming = frames.get(instrument.primary_source)
        # A vintage archive is never rebased: a vintage whose value moves is
        # a rewrite, which the promotion refuses on its own.
        factor = (
            None
            if incoming is None or stored.empty or clean_table(instrument) == "vintages"
            else _rebasing_factor(stored, incoming, key_column, self._value_columns(instrument))
        )
        if factor is not None:
            return self._report_rebasing(instrument, factor, start, end, primary, issues)
        return self._ingest(
            instrument,
            frames,
            actions,
            fetch_id=primary.fetch_id,
            checked_at=primary.retrieved_at_utc,
            requested=(start, end),
            extra_issues=issues,
            fetches=_fetched_pairs(downloads, actions_download),
        )

    def archive_history(self, instrument_id: str) -> ValidationReport:
        """Fetch an instrument's whole declared history, from its first session.

        Parameters
        ----------
        instrument_id : str
            Instrument to archive.

        Returns
        -------
        ValidationReport
            Issues found, exactly as :meth:`download` reports them.

        Raises
        ------
        ValueError
            If the instrument declares no ``first_session``: a history with no
            beginning cannot be asked for in full.

        Notes
        -----
        This is the other half of the survivorship problem, and it is the half
        a dated universe cannot solve. Membership dated correctly says TWTR was
        in the index until it left; it does not give anyone its prices, and the
        day a provider stops serving a delisted name, its history is gone for
        good. Nobody can go back for it later - a download is only possible
        while the name is still served.

        So the archive is taken on purpose, in full, while it can be: the
        response lands in ``raw/`` like any other, and ``clean/`` is rebuilt
        from it for ever after. Run it for a name that may leave, and read
        :meth:`history_coverage` to know which ones are not covered yet.

        It is an ordinary fetch of a wide window, not a special path: the same
        normalizer, the same validator, the same revision policy. What it adds
        is the range - the instrument's own listing window - and the intent.
        """
        instrument = self._instruments.get(instrument_id)
        if instrument.first_session is None:
            raise ValueError(
                f"{instrument_id}: no first_session declared, so there is no whole "
                "history to ask for"
            )
        end = safe_end_date(instrument, self._calendar_of(instrument), self._clock())
        return self.download(instrument_id, instrument.first_session, end)

    def history_coverage(self, instrument_id: str) -> HistoryCoverage:
        """Return how much of an instrument's declared history the store holds.

        Parameters
        ----------
        instrument_id : str
            Instrument to measure.

        Returns
        -------
        HistoryCoverage
            The declared window, what is stored inside it, and how many raw
            fetches stand behind it.

        Notes
        -----
        Measured on the clean series rather than on the raw archive, and on
        purpose: ``clean`` is what a replay of ``raw`` produces, so a fetch the
        validator refused is correctly counted as history the store does not
        have. The raw count is reported beside it, because a name with archived
        fetches and an empty clean series is a different problem from a name
        that was never fetched at all.
        """
        instrument = self._instruments.get(instrument_id)
        stored = self._stored_frame(instrument)
        key_column = self._key_column(instrument)
        dates = sorted(set(stored[key_column])) if not stored.empty else []
        fetches = sum(
            len(self._repository.list_raw_fetches(instrument.id, source))
            for source in instrument.sources
        )
        until = instrument.last_session or safe_end_date(
            instrument, self._calendar_of(instrument), self._clock()
        )
        missing: tuple[date, ...] | None = None
        contested: tuple[date, ...] | None = None
        if instrument.data_type is DataType.BAR:
            since = instrument.first_session or (dates[0] if dates else None)
            expected = (
                []
                if since is None or since > until
                else [
                    session.session_date
                    for session in self._venue_of(instrument).sessions(since, until)
                    if instrument.is_listed(session.session_date)
                ]
            )
            missing = tuple(sorted(set(expected) - set(dates)))
            checked = self._repository.load_checked_bars(instrument.id)
            contested = tuple(
                sorted(
                    checked.loc[
                        checked["check_status"] == CheckStatus.CONFLICT.value, "session_date"
                    ]
                )
            )
        return HistoryCoverage(
            instrument_id=instrument.id,
            declared_from=instrument.first_session,
            declared_until=until,
            stored_from=dates[0] if dates else None,
            stored_until=dates[-1] if dates else None,
            raw_fetches=fetches,
            missing_sessions=missing,
            contested_sessions=contested,
        )

    def update_all(self) -> dict[str, ValidationReport]:
        """Refresh every registered instrument.

        Returns
        -------
        dict[str, ValidationReport]
            One report per instrument, in registry order.

        Notes
        -----
        Exercice 9.4 (facile). L'echec d'un instrument ne doit pas interrompre
        les autres : collecte les erreurs et rends-les toutes.

        A failure becomes an ``UPDATE_FAILED`` error in that instrument's report
        and is written to the validation log: an exception printed to a terminal
        nobody reads is an exception lost.
        """
        reports: dict[str, ValidationReport] = {}
        for instrument in self._instruments.list_all():
            try:
                reports[instrument.id] = self.update(instrument.id)
            # One instrument failing must not stop the rest: that is the method's point.
            except Exception as error:
                report = ValidationReport(
                    instrument_id=instrument.id,
                    issues=[
                        _issue(
                            "UPDATE_FAILED",
                            Severity.ERROR,
                            instrument.id,
                            None,
                            f"Updating {instrument.id} raised {type(error).__name__}: {error}",
                        )
                    ],
                )
                self._repository.append_validation_log([report], self._clock().astimezone(UTC))
                reports[instrument.id] = report
        return reports

    def rebuild_clean(self, instrument_id: str) -> ValidationReport:
        """Rebuild an instrument's clean series from the raw archive alone.

        Parameters
        ----------
        instrument_id : str
            Instrument to rebuild.

        Returns
        -------
        ValidationReport
            Issues found while replaying, in replay order. If any is an error,
            the report ends with ``REBUILD_ABANDONED`` and nothing was written.

        Raises
        ------
        FileNotFoundError
            If a fetch the journal says shaped the clean layer is no longer in
            ``raw/``. Nothing is written.
        StoreBusy
            If someone else holds the store.

        Notes
        -----
        The whole rebuild is one repository transaction: the emptying, every
        replayed promotion, and nothing published until the last one has
        passed. A replay that fails - an archive that no longer reads, a
        fetch the validator now refuses - leaves the previous clean layer
        exactly as it was, where emptying it first used to leave nothing
        (audit A16).

        Exercice 9.5 (difficile, et c'est la methode qui prouve tout le reste).

        Rejoue les snapshots ``raw/`` dans l'ordre chronologique, applique
        normalizer, validator et politique de revision, et reecrit ``clean/``.
        Aucun acces reseau.

        Elle materialise la propriete centrale du module :

            raw + instruments.toml + accepted_revisions.toml + calendriers
            + version du normalizer  ->  clean

        Le test associe est celui qu'on oublie toujours d'ecrire : deux appels
        consecutifs doivent produire des fichiers **identiques octet pour
        octet**. S'il echoue, il y a un etat cache quelque part - une horloge
        lue, un ordre de dictionnaire, un chemin absolu - et la reproductibilite
        n'est qu'une intention.

        Only the fetches that completed a promotion are replayed. ``raw/`` also
        holds downloads the validator refused and runs that died before writing
        anything to ``clean/``, and replaying those would not rebuild what the
        live path built: the first value stored wins, so a snapshot that never
        reached ``clean/`` would win over the one that did. They stay in the
        archive as evidence, and the report names them.

        Two deliberate differences with the live path, and only two. The
        instrument's clean files are emptied first, otherwise the policy would
        compare every replayed row with the rows already there and rebuild
        nothing. And neither the revision log nor the validation log is appended
        to: they record what happened when the data arrived, and replaying the
        archive is not a second arrival.

        Nothing else differs. Every source has a canonical series governed by
        the revision policy, so meeting the archived fetches one at a time
        reaches the state the live run reached meeting them together, without a
        replay rule of its own.
        """
        instrument = self._instruments.get(instrument_id)
        applied = self._repository.load_applied_fetches(instrument.id)
        archived = self._archived_fetches(instrument)
        lost = sorted(applied - {(source_id, fetch_id) for fetch_id, source_id in archived})
        if lost:
            raise FileNotFoundError(
                f"{instrument.id}: {len(lost)} fetch(es) shaped the clean layer and are no "
                f"longer in raw/: {', '.join(f'{source}:{fetch}' for source, fetch in lost)}. "
                "Nothing was rebuilt; the clean layer is as it was."
            )
        issues: list[ValidationIssue] = []
        try:
            with self._repository.transaction():
                self._replay(instrument, applied, archived, issues)
                if any(issue.severity is Severity.ERROR for issue in issues):
                    raise _PromotionRefused([])
        except (_PromotionRefused, TransactionDoomed):
            issues.append(
                _issue(
                    "REBUILD_ABANDONED",
                    Severity.ERROR,
                    instrument.id,
                    None,
                    f"{instrument.id}: a replayed fetch no longer passes; nothing was "
                    "rebuilt and the clean layer is as it was",
                )
            )
        return ValidationReport(instrument_id=instrument.id, issues=issues)

    def _replay(
        self,
        instrument: Instrument,
        applied: set[tuple[str, str]],
        archived: Sequence[tuple[str, str]],
        issues: list[ValidationIssue],
    ) -> None:
        """Empty an instrument's clean tables and replay its applied fetches.

        Parameters
        ----------
        instrument : Instrument
            Instrument to rebuild.
        applied : set[tuple[str, str]]
            ``(source, fetch_id)`` of every fetch that completed a promotion.
        archived : Sequence[tuple[str, str]]
            ``(fetch_id, source)`` of every archived fetch, oldest first.
        issues : list[ValidationIssue]
            Appended to as the replay goes, so a caller whose transaction
            failed still has everything found up to the failure.
        """
        self._reset_clean(instrument)
        skipped: list[str] = []
        for fetch_id, source_id in archived:
            if (source_id, fetch_id) not in applied:
                # Archived, then never promoted: a download refused by the
                # validator, or a run that died after writing raw. Replaying it
                # would let a snapshot the live path never kept win over the one
                # it did, since the first value stored wins.
                skipped.append(f"{source_id}:{fetch_id}")
                continue
            download = self._repository.load_raw(instrument.id, source_id, fetch_id)
            data, corrected = self._normalize(instrument, source_id, download)
            issues.extend(corrected)
            frames = {}
            frame = _canonical_frame(instrument, data)
            if frame is not None:
                frames[source_id] = frame
            report = self._ingest(
                instrument,
                frames,
                data.corporate_actions,
                fetch_id=download.fetch_id,
                checked_at=download.retrieved_at_utc,
                requested=None,
                extra_issues=[],
                log=False,
            )
            issues.extend(report.issues)
        if skipped:
            issues.append(
                _issue(
                    "UNAPPLIED_FETCH_SKIPPED",
                    Severity.WARNING,
                    instrument.id,
                    None,
                    f"{len(skipped)} archived fetch(es) never completed a promotion and were "
                    f"not replayed: {', '.join(skipped)}. They stay in raw/ as evidence.",
                )
            )

    # -- fetching ----------------------------------------------------------

    def _fetch(
        self, instrument: Instrument, start: date, end: date
    ) -> tuple[dict[str, RawDownload], RawDownload | None, list[ValidationIssue]]:
        """Download every source of an instrument and archive each response.

        Parameters
        ----------
        instrument : Instrument
            Instrument to fetch.
        start, end : date
            Inclusive requested range.

        Returns
        -------
        tuple[dict[str, RawDownload], RawDownload | None, list[ValidationIssue]]
            One download per source that answered, the corporate actions
            download of the primary source when it has one, and a
            ``CHECK_SOURCE_UNAVAILABLE`` warning for every check source that
            could not.
        """
        downloads: dict[str, RawDownload] = {}
        issues: list[ValidationIssue] = []
        for source_id in instrument.sources:
            source = self._source(source_id)
            asked = instrument.for_source(source_id)
            if source_id == instrument.primary_source:
                download = source.download(asked, start, end)
                self._repository.save_raw(download)
                downloads[source_id] = download
                continue
            download, issue = self._check_download(instrument, source, asked, start, end)
            if issue is not None:
                issues.append(issue)
            if download is None:
                continue
            self._repository.save_raw(download)
            downloads[source_id] = download
        # Actions come from the primary source only: two providers' event feeds
        # would need a cross-check of their own, which is not this layer's job.
        actions = self._source(instrument.primary_source).download_corporate_actions(
            instrument, start, end
        )
        if actions is not None:
            self._repository.save_raw(actions)
        return downloads, actions, issues

    def _require_consistent_clean(self, instrument: Instrument) -> None:
        """Refuse to build on a clean layer left half written.

        Parameters
        ----------
        instrument : Instrument
            Instrument about to be updated.

        Raises
        ------
        ValueError
            If the checked series is not what the stored series produce, which
            means a previous run died between two writes, or the cross-check
            policy changed after the verdicts were computed.

        Notes
        -----
        The verdicts are a function of the stored series and the committed
        policy, so the check is to compute them again and compare. Matching
        session dates is not enough: a run that died after writing the bars and
        before the verdicts leaves two files that agree on which days exist and
        disagree on what happened on them, which nothing would have noticed.

        It runs before anything is fetched, and on the daily volumes here it
        costs a few milliseconds - the alternative is an update that merges into
        a series whose verdicts describe different values, and says nothing.
        """
        if instrument.data_type is not DataType.BAR:
            return
        bars = self._repository.load_bars(instrument.id)
        checked = self._repository.load_checked_bars(instrument.id)
        stored_days = set(bars["session_date"])
        checked_days = set(checked["session_date"])
        if stored_days != checked_days:
            raise ValueError(
                f"{instrument.id}: the clean layer is inconsistent - "
                f"{len(stored_days - checked_days)} session(s) have bars and no verdict, "
                f"{len(checked_days - stored_days)} the other way round. "
                f"{_REPAIR_HINT.format(instrument_id=instrument.id)}"
            )
        canonical = {instrument.primary_source: bars}
        for check in instrument.check_sources:
            canonical[check.source] = self._repository.load_check_bars(instrument.id, check.source)
        expected = cross_check_bars(
            instrument.id,
            canonical,
            reference_source=instrument.primary_source,
            policy=self._cross_check_policy,
        )
        if expected.equals(checked):
            return
        moved = [
            str(column)
            for column in checked.columns
            if not checked[column].equals(expected[column])
        ]
        raise ValueError(
            f"{instrument.id}: the stored verdicts are not what the stored series produce - "
            f"{', '.join(moved)} differ(s). Either a run was interrupted between two "
            f"writes, or metadata/crosscheck.toml changed after they were computed. "
            f"{_REPAIR_HINT.format(instrument_id=instrument.id)}"
        )

    def _check_download(
        self,
        instrument: Instrument,
        source: DataSource,
        asked: Instrument,
        start: date,
        end: date,
    ) -> tuple[RawDownload | None, ValidationIssue | None]:
        """Fetch one check source over the range it can actually serve.

        Parameters
        ----------
        instrument : Instrument
            Instrument being fetched, for the messages.
        source : DataSource
            Check source to ask.
        asked : Instrument
            The instrument as that source knows it, symbol included.
        start, end : date
            Range the primary source was asked for.

        Returns
        -------
        tuple[RawDownload | None, ValidationIssue | None]
            The response, and a ``CHECK_SOURCE_UNAVAILABLE`` warning when there
            is none.

        Notes
        -----
        A second opinion that cannot be obtained is not a reason to lose the
        primary data, so an outage is a warning and the sessions it would have
        confirmed stay ``SINGLE_SOURCE`` - which is what that status means.

        But a window is not an outage. Euronext keeps about two years and
        refuses anything older; asking it for 2018 used to lose the whole
        request, and with it the cross-check of every session since - 2230 of
        them on ETF_WORLD, none of them ever confirmed. The range is therefore
        cut to what the source declares it holds, and if the window has moved
        since, its refusal names the date it did serve from and the request is
        made again from there. Once: a source that keeps moving its answer is a
        source to look at.

        An unreadable answer is neither, and does not degrade. A format that
        changed or a symbol that moved has to be seen, not absorbed for months
        behind a warning nobody reads, so :class:`ProviderResponseError`
        propagates. :meth:`update_all` keeps the other instruments going.
        """
        floor = source.available_from(asked)
        source_start = max(start, floor) if floor is not None else start
        for attempt in range(2):
            if source_start > end:
                return None, self._check_unavailable(
                    instrument,
                    source,
                    start,
                    end,
                    f"it holds nothing before {source_start}",
                )
            try:
                return source.download(asked, source_start, end), None
            except ProviderResponseError:
                raise
            except ProviderRangeUnavailable as error:
                retry = error.available_from
                if attempt == 0 and retry is not None and retry > source_start:
                    source_start = retry
                    continue
                return None, self._check_unavailable(instrument, source, start, end, str(error))
            except ProviderError as error:
                return None, self._check_unavailable(
                    instrument, source, start, end, f"{type(error).__name__}: {error}"
                )
        raise AssertionError("unreachable: the loop returns on every path")

    @staticmethod
    def _check_unavailable(
        instrument: Instrument,
        source: DataSource,
        start: date,
        end: date,
        reason: str,
    ) -> ValidationIssue:
        """Build the warning left when a check source cannot answer."""
        return _issue(
            "CHECK_SOURCE_UNAVAILABLE",
            Severity.WARNING,
            instrument.id,
            None,
            f"{source.source_id} could not serve {instrument.id} from {start} to {end} "
            f"({reason}); the sessions it would have confirmed stay single-sourced",
        )

    def _normalize_all(
        self,
        instrument: Instrument,
        downloads: Mapping[str, RawDownload],
        actions_download: RawDownload | None,
    ) -> tuple[dict[str, pd.DataFrame], pd.DataFrame | None, list[ValidationIssue]]:
        """Normalise every response of one fetch.

        Parameters
        ----------
        instrument : Instrument
            Instrument fetched.
        downloads : Mapping[str, RawDownload]
            One response per source.
        actions_download : RawDownload | None
            Corporate actions response, when there is one.

        Returns
        -------
        tuple[dict[str, pd.DataFrame], pd.DataFrame | None, list[ValidationIssue]]
            Canonical frames per source, canonical corporate actions, and a
            ``NO_DATA`` error for any source that returned nothing of the kind
            the instrument declares.
        """
        frames: dict[str, pd.DataFrame] = {}
        issues: list[ValidationIssue] = []
        for source_id, download in downloads.items():
            data, corrected = self._normalize(instrument, source_id, download)
            issues += corrected
            issues += self._rejected_issues(instrument, source_id, data)
            frame = _canonical_frame(instrument, data)
            if frame is None:
                issues.append(
                    _issue(
                        "NO_DATA",
                        Severity.ERROR,
                        instrument.id,
                        None,
                        f"{source_id} returned no {instrument.data_type.value.lower()} rows "
                        f"for {instrument.id} in fetch {download.fetch_id}",
                    )
                )
                continue
            frames[source_id] = frame
        actions = None
        if actions_download is not None:
            normalized, corrected = self._normalize(
                instrument, instrument.primary_source, actions_download
            )
            issues += corrected
            issues += self._rejected_issues(instrument, instrument.primary_source, normalized)
            actions = normalized.corporate_actions
        return frames, actions, issues

    @staticmethod
    def _rejected_issues(
        instrument: Instrument, source_id: str, data: NormalizedData
    ) -> list[ValidationIssue]:
        """Report the rows the normalizer refused to store, by reason.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.
        source_id : str
            Source that sent them.
        data : NormalizedData
            What the normalizer kept, and what it refused.

        Returns
        -------
        list[ValidationIssue]
            One warning per dropped date, coded by reason.

        Notes
        -----
        Warnings rather than errors, all three: a junk day from 2019, a value
        the market had not yet made, or a bar of a session still running must
        not stop a series from updating today. What they must not do is vanish,
        because dropping a row in silence is how a provider's junk becomes
        invisible.
        """
        rejected = data.rejected
        return (
            [
                _issue(
                    "NON_SESSION_ROW",
                    Severity.WARNING,
                    instrument.id,
                    day,
                    f"{source_id} sent a row for {instrument.id} on {day}, a day its venue held "
                    f"no session; it cannot be dated and was dropped",
                )
                for day in rejected.non_session
            ]
            + [
                _issue(
                    "OUTSIDE_LISTING_WINDOW",
                    Severity.WARNING,
                    instrument.id,
                    day,
                    f"{source_id} sent a row for {instrument.id} on {day}, outside its listing "
                    f"window; it is not a price the market made and was dropped",
                )
                for day in rejected.unlisted
            ]
            + [
                _issue(
                    "NOT_YET_AVAILABLE",
                    Severity.WARNING,
                    instrument.id,
                    day,
                    f"{source_id} sent a row for {instrument.id} on {day} that was not public yet "
                    f"when the fetch ran; it would have frozen a provisional value and was dropped",
                )
                for day in rejected.unpublished
            ]
        )

    def _normalize(
        self, instrument: Instrument, source_id: str, download: RawDownload
    ) -> tuple[NormalizedData, list[ValidationIssue]]:
        """Run one source's normalizer on one response, then the reviewed corrections.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.
        source_id : str
            Source that sent the response.
        download : RawDownload
            The response, exactly as it was archived.

        Returns
        -------
        tuple[NormalizedData, list[ValidationIssue]]
            The canonical frames, and one warning per bar a reviewed correction
            dropped. The correction is applied here, at the one point both the
            live path and a replay of the archive go through, so a rebuild
            produces the series the live run produced.

        Raises
        ------
        KeyError
            If no normalizer is registered for the source.
        ValueError
            If a correction no longer matches the row it was written for.
        """
        normalizer = self._normalizers.get(source_id)
        if normalizer is None:
            raise KeyError(
                f"No normalizer registered for source {source_id!r}; "
                f"known: {', '.join(sorted(self._normalizers))}"
            )
        data = normalizer.normalize(
            instrument.for_source(source_id), download, self._calendar_of(instrument)
        )
        if data.bars is None:
            return data, []
        bars, applied = self._bar_corrections.apply(instrument, source_id, data.bars)
        if not applied:
            return data, []
        return replace(data, bars=bars), [
            _corrected_bar_issue(instrument, source_id, correction) for correction in applied
        ]

    # -- promotion ---------------------------------------------------------

    def _ingest(
        self,
        instrument: Instrument,
        frames: Mapping[str, pd.DataFrame],
        actions: pd.DataFrame | None,
        *,
        fetch_id: str,
        checked_at: datetime,
        requested: tuple[date, date] | None,
        extra_issues: Sequence[ValidationIssue],
        fetches: Sequence[tuple[str, str]] = (),
        log: bool = True,
    ) -> ValidationReport:
        """Validate one fetch and, if it holds, promote it to the clean layer.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.
        frames : Mapping[str, pd.DataFrame]
            Canonical bars or levels, per source.
        actions : pd.DataFrame | None
            Canonical corporate actions of the fetch.
        fetch_id : str
            Fetch that produced the frames, recorded in the revision log.
        checked_at : datetime
            The fetch's ``retrieved_at_utc``: never a clock read, so a replay
            stamps exactly what the live run stamped.
        requested : tuple[date, date] | None
            Range asked of the provider, used to tell a corporate action the
            provider dropped from one it was simply not asked for. ``None``
            when replaying an archive.
        extra_issues : Sequence[ValidationIssue]
            Issues raised before validation, such as a source that sent nothing.
        fetches : Sequence[tuple[str, str]]
            ``(source, fetch_id)`` pairs this ingestion consumed, recorded as
            applied once the promotion has completed. Empty on a replay, which
            reads that journal rather than writing to it.
        log : bool
            Whether to append to the validation log and the revision log.

        Returns
        -------
        ValidationReport
            Everything found, promotion issues included.
        """
        issues = list(extra_issues) + self._validate(instrument, frames, actions)
        report = ValidationReport(instrument_id=instrument.id, issues=issues)
        if report.valid:
            # One promotion, one change to the clean layer. The series, the
            # verdicts computed from them and the journal saying which fetches
            # produced them are the same statement, and a run interrupted
            # between two of those writes used to leave a store whose verdicts
            # described values that were no longer there.
            # And a promotion that finds the store it would write invalid
            # raises inside the transaction, which throws every write away.
            try:
                with self._repository.transaction():
                    issues = issues + self._promote(
                        instrument,
                        frames,
                        actions,
                        fetch_id=fetch_id,
                        checked_at=checked_at,
                        requested=requested,
                        log=log,
                    )
                    if log:
                        self._repository.mark_fetches_applied(instrument.id, fetches, checked_at)
            except _PromotionRefused as refused:
                issues = issues + refused.issues
            report = ValidationReport(instrument_id=instrument.id, issues=issues)
        if log:
            self._repository.append_validation_log([report], checked_at)
        return report

    def _validate(
        self,
        instrument: Instrument,
        frames: Mapping[str, pd.DataFrame],
        actions: pd.DataFrame | None,
    ) -> list[ValidationIssue]:
        """Run the validator on every frame of one fetch."""
        issues: list[ValidationIssue] = []
        for _, frame in sorted(frames.items()):
            if instrument.data_type is DataType.BAR:
                issues += list(validate_bars(instrument, frame, self._venue_of(instrument)).issues)
            elif instrument.vintage_policy is VintagePolicy.AS_OF_DECISION:
                # One vintage at a time: inside one, the rules about a
                # published series are exactly the level rules, and across
                # them a repeated observation date is the point rather than a
                # duplicate.
                calendar = self._calendar_of(instrument)
                rule = instrument.publication_rule
                if rule is None:  # pragma: no cover - a LEVEL always has one
                    raise ValueError(f"{instrument.id} is a LEVEL with no publication rule")
                issues += _withdrawal_issues(instrument, frame)
                for vintage in sorted(set(frame["vintage_date"])):
                    slice_ = frame.loc[
                        (frame["vintage_date"] == vintage) & ~frame["withdrawn"].astype(bool)
                    ]
                    vintage_at = rule.available_at(vintage, calendar)
                    issues += list(
                        validate_levels(
                            instrument,
                            slice_.drop(columns=["vintage_date", "withdrawn"]).reset_index(
                                drop=True
                            ),
                            calendar,
                            available_at=_vintage_availability(rule, calendar, vintage_at),
                        ).issues
                    )
            else:
                issues += list(
                    validate_levels(instrument, frame, self._calendar_of(instrument)).issues
                )
        if actions is not None:
            issues += list(validate_corporate_actions(instrument, actions).issues)
        return issues

    def _promote(
        self,
        instrument: Instrument,
        frames: Mapping[str, pd.DataFrame],
        actions: pd.DataFrame | None,
        *,
        fetch_id: str,
        checked_at: datetime,
        requested: tuple[date, date] | None,
        log: bool,
    ) -> list[ValidationIssue]:
        """Write one validated fetch into the clean layer."""
        if instrument.data_type is DataType.BAR:
            issues = self._promote_bars(
                instrument,
                frames,
                fetch_id=fetch_id,
                checked_at=checked_at,
                log=log,
            )
        elif instrument.vintage_policy is VintagePolicy.AS_OF_DECISION:
            issues = self._promote_vintages(instrument, frames)
        else:
            issues = self._promote_levels(
                instrument, frames, fetch_id=fetch_id, checked_at=checked_at, log=log
            )
        if actions is not None:
            issues += self._promote_actions(instrument, actions, requested=requested)
        return issues

    def _promote_bars(
        self,
        instrument: Instrument,
        frames: Mapping[str, pd.DataFrame],
        *,
        fetch_id: str,
        checked_at: datetime,
        log: bool,
    ) -> list[ValidationIssue]:
        """Merge every source's bars, then rewrite the checked series.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.
        frames : Mapping[str, pd.DataFrame]
            Canonical bars per source. A fetch of a check source alone carries
            no primary frame: the stored bars stay as they are and only the
            cross-check is redone.
        fetch_id : str
            Fetch that produced the frames.
        checked_at : datetime
            Instant recorded in the revision log.
        log : bool
            Whether to append detected revisions to the log.

        Returns
        -------
        list[ValidationIssue]
            One ``VALUE_REVISED`` warning per changed field, one
            ``SECONDARY_ONLY_SESSION`` warning per session this fetch brought
            from a check source and not from the primary, plus the
            cross-check's own issues.

        Notes
        -----
        Every source is merged the same way, primary or check. That is what
        makes the live path and a replay the same function: neither judges a
        session with the rows of the fetch in hand, both judge it with the
        canonical series on disk, and a restatement that nobody reviewed moves
        neither of them.
        """
        issues: list[ValidationIssue] = []
        merged = self._merge_source(
            instrument,
            instrument.primary_source,
            frames.get(instrument.primary_source),
            fetch_id=fetch_id,
            checked_at=checked_at,
            log=log,
            issues=issues,
        )
        canonical = {instrument.primary_source: merged}
        for check in instrument.check_sources:
            canonical[check.source] = self._merge_source(
                instrument,
                check.source,
                frames.get(check.source),
                fetch_id=fetch_id,
                checked_at=checked_at,
                log=log,
                issues=issues,
            )
        issues += _secondary_only_sessions(instrument, merged, frames)
        checked, checked_issues = self._checked_series(instrument, canonical, frames)
        self._repository.save_checked_bars(instrument.id, checked)
        return issues + checked_issues

    def _merge_source(
        self,
        instrument: Instrument,
        source_id: str,
        incoming: pd.DataFrame | None,
        *,
        fetch_id: str,
        checked_at: datetime,
        log: bool,
        issues: list[ValidationIssue],
    ) -> pd.DataFrame:
        """Merge one source's bars into its canonical series and store it.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.
        source_id : str
            Source whose series this is.
        incoming : pd.DataFrame | None
            What this fetch brought from it, ``None`` when it brought nothing.
        fetch_id : str
            Fetch that produced ``incoming``.
        checked_at : datetime
            Instant recorded in the revision log.
        log : bool
            Whether to append detected revisions to the log.
        issues : list[ValidationIssue]
            Appended to, one ``VALUE_REVISED`` per changed field.

        Returns
        -------
        pd.DataFrame
            The source's canonical series after the merge.

        Raises
        ------
        _PromotionRefused
            If the merge assembled a bar that breaks a row rule. What is
            validated before promotion is the fetch; what is stored is the
            merge, and it is judged too.
        """
        primary = source_id == instrument.primary_source
        stored = (
            self._repository.load_bars(instrument.id)
            if primary
            else self._repository.load_check_bars(instrument.id, source_id)
        )
        if incoming is None or incoming.empty:
            return stored
        revisions = detect_revisions(
            stored,
            incoming,
            table="bars",
            key_column="session_date",
            value_columns=BAR_VALUE_COLUMNS,
            new_fetch_id=fetch_id,
            detected_at_utc=checked_at,
        )
        if not revisions.empty:
            if log:
                self._repository.append_revisions(revisions)
            issues += self._revision_issues(instrument, revisions, "bars")
        merged = merge_with_policy(
            stored,
            incoming,
            self._accepted_revisions,
            table="bars",
            key_column="session_date",
            value_columns=BAR_VALUE_COLUMNS,
        )
        broken = _merged_bar_errors(instrument, source_id, merged, incoming)
        if broken:
            raise _PromotionRefused(issues + broken)
        if primary:
            self._repository.save_bars(instrument.id, merged)
        else:
            self._repository.save_check_bars(instrument.id, source_id, merged)
        return merged

    def _promote_levels(
        self,
        instrument: Instrument,
        frames: Mapping[str, pd.DataFrame],
        *,
        fetch_id: str,
        checked_at: datetime,
        log: bool,
    ) -> list[ValidationIssue]:
        """Merge a published series under the revision policy."""
        incoming = frames.get(instrument.primary_source)
        if incoming is None:
            return []
        stored = self._repository.load_levels(instrument.id)
        issues: list[ValidationIssue] = []
        revisions = detect_revisions(
            stored,
            incoming,
            table="levels",
            key_column="observation_date",
            value_columns=LEVEL_VALUE_COLUMNS,
            new_fetch_id=fetch_id,
            detected_at_utc=checked_at,
        )
        if not revisions.empty:
            if log:
                self._repository.append_revisions(revisions)
            issues += self._revision_issues(instrument, revisions, "levels")
        merged = merge_with_policy(
            stored,
            incoming,
            self._accepted_revisions,
            table="levels",
            key_column="observation_date",
            value_columns=LEVEL_VALUE_COLUMNS,
        )
        self._repository.save_levels(instrument.id, merged)
        return issues

    def _promote_vintages(
        self, instrument: Instrument, frames: Mapping[str, pd.DataFrame]
    ) -> list[ValidationIssue]:
        """Add new vintage rows to the archive, and refuse a rewritten one.

        Parameters
        ----------
        instrument : Instrument
            The published series.
        frames : Mapping[str, pd.DataFrame]
            Canonical vintage rows per source.

        Returns
        -------
        list[ValidationIssue]
            One error per pair whose value moved.

        Notes
        -----
        The revision policy does not apply here, and the reason is worth
        writing down. A level may legitimately be revised, and the policy
        decides whether to accept the new value. A vintage cannot: the archive
        of what was known on a given day is a fact about the past, and it does
        not change. So a pair that arrives with a different value is a provider
        rewriting history, and it stops the promotion instead of being merged
        under a rule that does not fit it.
        """
        incoming = frames.get(instrument.primary_source)
        if incoming is None:
            return []
        stored = self._repository.load_vintages(instrument.id)
        known = {
            (row["observation_date"], row["vintage_date"]): _vintage_cell(row)
            for row in stored.to_dict("records")
        }
        issues: list[ValidationIssue] = []
        rows = []
        for record in incoming.to_dict("records"):
            key = (record["observation_date"], record["vintage_date"])
            if key in known:
                # A withdrawal is compared as one, never as a NaN: NaN != NaN
                # would call every refetched withdrawal a rewrite.
                if known[key] != _vintage_cell(record):
                    issues.append(
                        _issue(
                            "VINTAGE_REWRITTEN",
                            Severity.ERROR,
                            instrument.id,
                            record["observation_date"],
                            f"the vintage of {record['vintage_date']} gave "
                            f"{known[key] or 'a withdrawal'} for {record['observation_date']} "
                            f"and now gives {_vintage_cell(record) or 'a withdrawal'}; an "
                            "archive of what was known on a day cannot change",
                        )
                    )
                continue
            rows.append(record)
        if issues:
            return issues
        if not rows:
            return []
        merged = pd.concat([stored, pd.DataFrame(rows, columns=list(VINTAGES_SCHEMA.names))])
        merged = merged.sort_values(
            ["observation_date", "vintage_date"], kind="stable"
        ).reset_index(drop=True)
        self._repository.save_vintages(instrument.id, merged)
        return []

    def _promote_actions(
        self,
        instrument: Instrument,
        incoming: pd.DataFrame,
        *,
        requested: tuple[date, date] | None,
    ) -> list[ValidationIssue]:
        """Add corporate actions we did not have, and never rewrite one we did.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.
        incoming : pd.DataFrame
            Canonical actions of this fetch, already restricted to the range.
        requested : tuple[date, date] | None
            Range asked of the provider. Inside it, a stored action the fetch
            does not carry is reported: the provider withdrew an event we had.

        Returns
        -------
        list[ValidationIssue]
            ``ACTION_REVISED`` and ``ACTION_ABSENT`` warnings.

        Notes
        -----
        The reviewed corrections are applied before anything else, so a spin-off
        Yahoo reported as a fractional split is stored as a ``SPIN_OFF`` and
        compared as one. The correction changes no value and no date, and both
        sides of every allowed pair adjust prices identically, so it cannot move
        a stored series.

        An action is keyed by ``(ex_date, action_type)``: a dividend and a split
        can share an ex-date, so the date alone is not a key. A stored action
        whose value changed is reported and kept as stored - the accepted
        revisions file covers bars and levels only, so there is no reviewed way
        to let an action change, and silently taking the new number would move
        every adjusted price before that ex-date.
        """
        issues: list[ValidationIssue] = []
        # Reviewed labels first: what is compared with the stored table, and what
        # is added to it, is what the event was - not what the provider called it.
        incoming = self._action_corrections.apply(incoming)
        stored_all = self._repository.load_corporate_actions()
        mine = stored_all.loc[stored_all["instrument_id"] == instrument.id]
        others = stored_all.loc[stored_all["instrument_id"] != instrument.id]
        stored_by_key = {(row["ex_date"], row["action_type"]): row for row in _records(mine)}
        incoming_rows = _records(incoming)
        additions: list[bool] = []
        for row in incoming_rows:
            key = (row["ex_date"], row["action_type"])
            stored_row = stored_by_key.get(key)
            additions.append(stored_row is None)
            if stored_row is not None and float(stored_row["value"]) != float(row["value"]):
                issues.append(
                    _issue(
                        "ACTION_REVISED",
                        Severity.WARNING,
                        instrument.id,
                        row["ex_date"],
                        f"{instrument.id} {row['action_type']} of {row['ex_date']} is stored as "
                        f"{stored_row['value']} and was refetched as {row['value']}; "
                        f"the stored value is kept",
                        {"stored": stored_row["value"], "incoming": row["value"]},
                    )
                )
        if requested is not None:
            start, end = requested
            incoming_keys = {(row["ex_date"], row["action_type"]) for row in incoming_rows}
            for (ex_date, action_type), row in sorted(
                stored_by_key.items(), key=lambda item: (item[0][0], item[0][1])
            ):
                if start <= ex_date <= end and (ex_date, action_type) not in incoming_keys:
                    issues.append(
                        _issue(
                            "ACTION_ABSENT",
                            Severity.WARNING,
                            instrument.id,
                            ex_date,
                            f"{instrument.id} {action_type} of {ex_date} is stored but absent "
                            f"from the fetch covering {start} to {end}; it is kept",
                            {"value": row["value"]},
                        )
                    )
        new_rows = incoming.loc[additions] if additions else incoming.iloc[0:0]
        pieces = [frame for frame in (others, mine, new_rows) if not frame.empty]
        table = pd.concat(pieces, ignore_index=True) if pieces else stored_all.iloc[0:0]
        table = table.sort_values(
            ["instrument_id", "ex_date", "action_type"], kind="stable"
        ).reset_index(drop=True)
        self._repository.save_corporate_actions(table)
        return issues

    def _checked_series(
        self,
        instrument: Instrument,
        canonical: Mapping[str, pd.DataFrame],
        frames: Mapping[str, pd.DataFrame],
    ) -> tuple[pd.DataFrame, list[ValidationIssue]]:
        """Rebuild the checked series over the sessions this fetch speaks about.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.
        canonical : Mapping[str, pd.DataFrame]
            Each source's stored series after the revision policy. They are what
            a session is judged **with**, primary source included, so the
            verdict follows the values the layer actually stands behind.
        frames : Mapping[str, pd.DataFrame]
            Canonical bars per source for this fetch. They decide **which**
            sessions are judged again.

        Returns
        -------
        tuple[pd.DataFrame, list[ValidationIssue]]
            The whole checked series, and a ``CHECK_STATUS_CHANGED`` warning for
            every session whose verdict this fetch moved.

        Notes
        -----
        A session is judged again only when this fetch brings rows for it, or
        when it has no verdict yet. Everything else keeps the verdict it was
        given, so a past cross-check outcome never moves because of data about
        another day.

        Judging from storage rather than from the fetch is what makes a replay
        of the archive reach the verdicts of the live run: one fetch at a time
        or every source at once, both read the same canonical series.
        """
        merged = canonical[instrument.primary_source]
        stored = self._repository.load_checked_bars(instrument.id)
        previous = {
            row["session_date"]: (row["check_status"], row["conflicting_fields"])
            for row in _records(stored)
        }
        judged: set[date] = set()
        for frame in frames.values():
            judged |= set(frame["session_date"])
        judged |= set(merged["session_date"]) - set(previous)
        to_judge = sorted(judged)
        # Every source, empty ones included: a check source that has never
        # answered leaves its sessions SINGLE_SOURCE, and the reference source
        # has to be there even when this fetch brought it nothing.
        judge_frames = {
            source_id: frame.loc[frame["session_date"].isin(to_judge)]
            for source_id, frame in canonical.items()
        }
        fresh = cross_check_bars(
            instrument.id,
            judge_frames,
            reference_source=instrument.primary_source,
            policy=self._cross_check_policy,
        )
        kept = stored.loc[~stored["session_date"].isin(to_judge)]
        pieces = [frame for frame in (kept, fresh) if not frame.empty]
        checked = pd.concat(pieces, ignore_index=True) if pieces else stored.iloc[0:0]
        checked = checked.sort_values("session_date", kind="stable").reset_index(drop=True)
        issues = [
            _issue(
                "CHECK_STATUS_CHANGED",
                Severity.WARNING,
                instrument.id,
                row["session_date"],
                f"{instrument.id} session {row['session_date']} was "
                f"{_verdict_label(previous[row['session_date']])} and is now "
                f"{_verdict_label(_verdict_of(row))} ({row['checked_sources']})",
                {"from": previous[row["session_date"]], "to": _verdict_of(row)},
            )
            for row in _records(fresh)
            if row["session_date"] in previous and previous[row["session_date"]] != _verdict_of(row)
        ]
        return checked, issues

    def _revision_issues(
        self, instrument: Instrument, revisions: pd.DataFrame, table: str
    ) -> list[ValidationIssue]:
        """Turn detected revisions into warnings, so a report says what moved."""
        return [
            _issue(
                "VALUE_REVISED",
                Severity.WARNING,
                instrument.id,
                row["observation_date"],
                f"{instrument.id} {table}.{row['field']} of {row['observation_date']} is stored "
                f"as {row['old_value']} and was refetched as {row['new_value']}; "
                f"{'applied' if self._is_accepted(instrument, table, row) else 'kept as stored'}",
                {"old": row["old_value"], "new": row["new_value"]},
            )
            for row in _records(revisions)
        ]

    def _is_accepted(self, instrument: Instrument, table: str, row: Mapping[str, Any]) -> bool:
        """Return whether one detected revision was reviewed into the policy."""
        return self._accepted_revisions.is_accepted(
            instrument.id,
            str(row["source"]),
            table,
            row["observation_date"],
            str(row["field"]),
            float(row["old_value"]),
            float(row["new_value"]),
        )

    def _report_rebasing(
        self,
        instrument: Instrument,
        factor: float,
        start: date,
        end: date,
        primary: RawDownload,
        issues: Sequence[ValidationIssue],
    ) -> ValidationReport:
        """Archive the full history, report the rebasing, promote nothing.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.
        factor : float
            Constant factor the overlap moved by.
        start, end : date
            Range the overlap fetch covered.
        primary : RawDownload
            Primary source's overlap response, whose instant stamps the log.
        issues : Sequence[ValidationIssue]
            Issues already raised by this fetch.

        Returns
        -------
        ValidationReport
            An ``ERROR`` report; the clean layer is untouched.
        """
        full_start = instrument.first_session or self._repository.first_date(instrument.id) or start
        # Evidence first: whatever the review decides, the new basis must be on
        # disk to be looked at. Nothing of it reaches clean/.
        self._fetch(instrument, full_start, end)
        report = ValidationReport(
            instrument_id=instrument.id,
            issues=[
                *issues,
                _issue(
                    "SERIES_REBASED",
                    Severity.ERROR,
                    instrument.id,
                    None,
                    f"{instrument.id}: every overlapping value between {start} and {end} moved "
                    f"by the same factor {factor:.6g}; this is a change of basis, not a "
                    f"revision. The full history was refetched into raw/ and clean/ was left "
                    f"untouched - review it before rebuilding",
                    {"factor": factor, "start": start, "end": end},
                ),
            ],
        )
        self._repository.append_validation_log([report], primary.retrieved_at_utc)
        return report

    # -- small helpers -----------------------------------------------------

    def _source(self, source_id: str) -> DataSource:
        """Return one registered adapter."""
        source = self._sources.get(source_id)
        if source is None:
            raise KeyError(
                f"No source registered for {source_id!r}; known: {', '.join(sorted(self._sources))}"
            )
        return source

    def _calendar_of(self, instrument: Instrument) -> TradingCalendar | None:
        """Return the calendar an instrument's availability depends on.

        Parameters
        ----------
        instrument : Instrument
            Instrument concerned.

        Returns
        -------
        TradingCalendar | None
            The venue calendar of a ``BAR``; for a ``LEVEL``, the calendar its
            publication rule counts its lag on, and ``None`` for a same-day
            release, which needs none.
        """
        if instrument.data_type is DataType.BAR:
            return (
                None
                if instrument.calendar_id is None
                else self._calendars.get(instrument.calendar_id)
            )
        rule = instrument.publication_rule
        if rule is None or rule.calendar_id is None:
            return None
        return self._calendars.get(rule.calendar_id)

    def _venue_of(self, instrument: Instrument) -> TradingCalendar:
        """Return the venue calendar of a ``BAR``, which it always has."""
        calendar = self._calendar_of(instrument)
        if calendar is None:
            raise KeyError(f"BAR instrument {instrument.id} has no calendar")
        return calendar

    @staticmethod
    def _key_column(instrument: Instrument) -> str:
        """Return the date column of the instrument's clean table."""
        return "session_date" if instrument.data_type is DataType.BAR else "observation_date"

    @staticmethod
    def _value_columns(instrument: Instrument) -> tuple[str, ...]:
        """Return the columns the rebasing guard compares."""
        return REBASE_FIELDS if instrument.data_type is DataType.BAR else LEVEL_VALUE_COLUMNS

    def _stored_frame(self, instrument: Instrument) -> pd.DataFrame:
        """Return the instrument's stored clean rows, from the table it lives in.

        Notes
        -----
        The table is :func:`clean_table`'s answer, the one every other reader
        of the store asks. Reading ``levels`` for every non-bar instrument
        made a vintage archive look empty: the resume point fell back to the
        first session, and each update fetched the whole history again
        (audit A10).
        """
        table = clean_table(instrument)
        if table == "bars":
            return self._repository.load_bars(instrument.id)
        if table == "vintages":
            return self._repository.load_vintages(instrument.id)
        return self._repository.load_levels(instrument.id)

    def _archived_fetches(self, instrument: Instrument) -> list[tuple[str, str]]:
        """Return every archived ``(fetch_id, source)`` of an instrument, oldest first.

        Notes
        -----
        Sorted by fetch identifier, then by source, so two sources archived in
        the same second replay in a fixed order - the ordering a rebuild's
        reproducibility rests on.
        """
        return sorted(
            (fetch_id, source_id)
            for source_id in instrument.sources
            for fetch_id in self._repository.list_raw_fetches(instrument.id, source_id)
        )

    def _reset_clean(self, instrument: Instrument) -> None:
        """Empty an instrument's clean tables, leaving every other instrument alone.

        Notes
        -----
        A table the instrument has no rows in is left untouched rather than
        created empty: a rebuild must not add files the pipeline never wrote,
        or two trees holding the same data would stop comparing equal.
        """
        if instrument.data_type is DataType.BAR:
            if not self._repository.load_bars(instrument.id).empty:
                self._repository.save_bars(instrument.id, BARS_SCHEMA.empty_table().to_pandas())
            for check in instrument.check_sources:
                stored = self._repository.load_check_bars(instrument.id, check.source)
                if not stored.empty:
                    self._repository.save_check_bars(
                        instrument.id, check.source, BARS_SCHEMA.empty_table().to_pandas()
                    )
            checked = self._repository.load_checked_bars(instrument.id)
            if not checked.empty:
                self._repository.save_checked_bars(instrument.id, checked.iloc[0:0])
        elif instrument.vintage_policy is VintagePolicy.AS_OF_DECISION:
            if not self._repository.load_vintages(instrument.id).empty:
                self._repository.save_vintages(
                    instrument.id, VINTAGES_SCHEMA.empty_table().to_pandas()
                )
        elif not self._repository.load_levels(instrument.id).empty:
            self._repository.save_levels(instrument.id, LEVELS_SCHEMA.empty_table().to_pandas())
        stored_all = self._repository.load_corporate_actions()
        mine = stored_all["instrument_id"] == instrument.id
        if mine.any():
            self._repository.save_corporate_actions(stored_all.loc[~mine].reset_index(drop=True))
