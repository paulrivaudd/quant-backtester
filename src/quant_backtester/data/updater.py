"""Ingestion: download, normalise, validate, store.

Kept deliberately apart from :mod:`quant_backtester.data.reader` so that the
backtester, which only ever receives a reader, is physically unable to reach the
network mid-run.

The pipeline for one instrument::

    registry -> source.download -> repository.save_raw (immutable)
             -> normalizer     -> validator
             -> merge under the revision policy
             -> repository.save_clean (atomic)

One writer at a time. An update rewrites several files - the bars, each check
source's series, the checked series, the actions - and each write is atomic on
its own, but the set of them is not. Nothing here takes a lock: reading the
clean layer while an update runs, or running two updates at once, is outside
what this module supports. A crash between two writes leaves the checked series
behind the bars; :meth:`MarketDataUpdater.update` notices that at the next run
and says so rather than building on it, and :meth:`rebuild_clean` repairs it
from the archive. A staging directory and a version pointer would make the set
atomic, and would be worth it the day something schedules this or reads it
concurrently - not for one process run by hand.

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
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pandas as pd

from quant_backtester.data.calendars import CalendarRegistry, TradingCalendar
from quant_backtester.data.corporate_actions import ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy, cross_check_bars
from quant_backtester.data.instruments import DataType, Instrument, InstrumentRegistry
from quant_backtester.data.normalizer import NormalizedData, Normalizer
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import (
    AcceptedRevisions,
    detect_revisions,
    merge_with_policy,
)
from quant_backtester.data.schemas import BARS_SCHEMA, LEVELS_SCHEMA
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
    validate_bars,
    validate_corporate_actions,
    validate_levels,
)

BAR_VALUE_COLUMNS: Final[tuple[str, ...]] = ("open", "high", "low", "close", "volume")
"""Bar columns the revision policy governs. Availability and lineage are not values."""

MAX_UNPUBLISHED_DAYS: Final[int] = 30
"""Longest run of days walked back looking for a published observation.

A same-day rule needs one step, a D+1 rule over a holiday week a handful.
Running past it means the publication rule is wrong, not that a publisher went
quiet for a month.
"""


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
    """
    if now_utc.tzinfo is None:
        raise ValueError(f"now_utc must be timezone-aware, got {now_utc!r}")
    today = now_utc.astimezone(UTC).date()
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
        end = safe_end_date(instrument, self._calendar_of(instrument), self._clock())
        if stored.empty:
            if instrument.first_session is None:
                raise ValueError(
                    f"{instrument_id}: nothing stored and no first_session to start from"
                )
            start = instrument.first_session
        else:
            dates = sorted(stored[key_column])
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
        factor = (
            None
            if incoming is None or stored.empty
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
            Issues found while replaying, in replay order.

        Notes
        -----
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

        Two deliberate differences with the live path, and only two. The
        instrument's clean files are emptied first, otherwise the policy would
        compare every replayed row with the rows already there and rebuild
        nothing. And neither the revision log nor the validation log is appended
        to: they record what happened when the data arrived, and replaying the
        archive is not a second arrival. A fetch whose validation fails is
        skipped, the replay continues, and its issues come back in the report -
        one bad old snapshot must not empty the whole series.

        Nothing else differs. Every source has a canonical series governed by
        the revision policy, so meeting the archived fetches one at a time
        reaches the state the live run reached meeting them together, without a
        replay rule of its own.
        """
        instrument = self._instruments.get(instrument_id)
        self._reset_clean(instrument)
        issues: list[ValidationIssue] = []
        for fetch_id, source_id in self._archived_fetches(instrument):
            download = self._repository.load_raw(instrument.id, source_id, fetch_id)
            data = self._normalize(instrument, source_id, download)
            frames = {}
            frame = data.bars if instrument.data_type is DataType.BAR else data.levels
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
            issues += list(report.issues)
        return ValidationReport(instrument_id=instrument.id, issues=issues)

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
            If the checked series and the bars disagree on which sessions are
            stored, which only happens when a previous run died between the two
            writes.

        Notes
        -----
        Cheap, and it runs before anything is fetched: the alternative is an
        update that merges into a series whose verdicts belong to a different
        set of sessions, and says nothing.
        """
        if instrument.data_type is not DataType.BAR:
            return
        bars = set(self._repository.load_bars(instrument.id)["session_date"])
        checked = set(self._repository.load_checked_bars(instrument.id)["session_date"])
        if bars == checked:
            return
        missing = len(bars - checked)
        extra = len(checked - bars)
        raise ValueError(
            f"{instrument.id}: the clean layer is inconsistent - {missing} session(s) have "
            f"bars and no verdict, {extra} the other way round. A run was interrupted "
            f"between two writes; rebuild_clean({instrument.id!r}) repairs it from raw/."
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
            data = self._normalize(instrument, source_id, download)
            issues += self._rejected_issues(instrument, source_id, data)
            frame = data.bars if instrument.data_type is DataType.BAR else data.levels
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
            normalized = self._normalize(instrument, instrument.primary_source, actions_download)
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
    ) -> NormalizedData:
        """Run one source's normalizer on one response."""
        normalizer = self._normalizers.get(source_id)
        if normalizer is None:
            raise KeyError(
                f"No normalizer registered for source {source_id!r}; "
                f"known: {', '.join(sorted(self._normalizers))}"
            )
        return normalizer.normalize(
            instrument.for_source(source_id), download, self._calendar_of(instrument)
        )

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
            issues = issues + self._promote(
                instrument,
                frames,
                actions,
                fetch_id=fetch_id,
                checked_at=checked_at,
                requested=requested,
                log=log,
            )
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
            One ``VALUE_REVISED`` warning per changed field, plus the
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
        """Return the instrument's stored clean rows, bars or levels."""
        if instrument.data_type is DataType.BAR:
            return self._repository.load_bars(instrument.id)
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
        elif not self._repository.load_levels(instrument.id).empty:
            self._repository.save_levels(instrument.id, LEVELS_SCHEMA.empty_table().to_pandas())
        stored_all = self._repository.load_corporate_actions()
        mine = stored_all["instrument_id"] == instrument.id
        if mine.any():
            self._repository.save_corporate_actions(stored_all.loc[~mine].reset_index(drop=True))
