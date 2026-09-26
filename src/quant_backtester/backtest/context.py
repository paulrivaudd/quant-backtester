"""Everything a strategy is given, and the vocabulary it answers in.

A strategy should read like the reasoning behind it. "Stand aside while the
gauge is high, otherwise hold the two best of the ranking" is one sentence, and
it should be about two lines of code - not a frame to filter, a sort to get
right, a set of statuses to interpret and a five-field record to assemble by
hand. That assembly is the same every time, so it lives here.

The context is fixed at one decision instant and everything in it is fixed at
the same one: the signals, the market view and the portfolio all answer for
``as_of``, and the construction refuses a set that does not agree. There is no
method that takes an instant, and no attribute that hands back the reader. A
strategy cannot read tomorrow because there is nothing to call.

Two things it deliberately does not do. It does not decide - a helper builds
the allocation a strategy asked for and never chooses the names. And it does
not apply the portfolio's rules: a maximum weight, a gross limit, a turnover
budget are applied to what comes out of a strategy, and keeping them separate
is what lets a report say what each of them cost.

It lives beside the engine rather than in ``strategies`` because the engine
builds it, and a lower layer never imports a higher one.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType

import pandas as pd

from quant_backtester.backtest.market import StrategyMarketView
from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.numbers import require_unit_fraction
from quant_backtester.portfolio.targets import WEIGHT_SUM_TOLERANCE, TargetAllocation
from quant_backtester.portfolio.view import PortfolioView
from quant_backtester.signals.snapshot import SignalSnapshot
from quant_backtester.signals.types import (
    SignalStatus,
    require_non_negative_int,
    require_positive_int,
)


class UnusableSignal(LookupError):
    """Raised when a strategy asked for a value a signal could not compute.

    Separate from a missing signal - which is a wiring mistake - because this
    one is an ordinary market situation: the history is too short, a session is
    missing, the last value is too old. A strategy that has a policy for it
    reads the status or asks for ``signal_value_or_none``; one that has not
    stops here rather than deciding on a ``NaN``.
    """


@dataclass(frozen=True, slots=True)
class Selection:
    """Instruments a strategy chose, and what it chose them among.

    Attributes
    ----------
    names : tuple[str, ...]
        The instruments, best first.
    considered : int
        How many had a usable signal to be chosen among. Two of nine and two
        of two are not the same decision, and only this number tells them
        apart afterwards.
    skipped : Mapping[str, SignalStatus]
        Why each of the others was not chosen: no history yet, a session
        missing, a value too old - or simply a worse rank. Frozen at
        construction: it is part of the record of a decision, not a buffer to
        edit before building one.

    Notes
    -----
    A value rather than a plain list because the count and the reasons are part
    of the decision. A helper handed a bare list of names cannot know how many
    instruments were rankable, and a run that lost that number can no longer
    tell a strategy standing aside from a strategy with nothing to choose from.
    """

    names: tuple[str, ...]
    considered: int
    skipped: Mapping[str, SignalStatus]

    def __post_init__(self) -> None:
        """Check the selection describes a choice, and freeze its diagnostics.

        Raises
        ------
        ValueError
            If a name appears twice, or fewer instruments were considered than
            were chosen. Both would make the record of the decision say
            something the decision cannot have meant.
        """
        names = tuple(self.names)
        repeated = sorted(name for name, seen in Counter(names).items() if seen > 1)
        if repeated:
            raise ValueError(f"{', '.join(repeated)} is selected more than once")
        require_non_negative_int(self.considered, "considered")
        if self.considered < len(names):
            raise ValueError(
                f"{len(names)} instrument(s) were chosen among {self.considered} considered"
            )
        object.__setattr__(self, "names", names)
        object.__setattr__(self, "skipped", MappingProxyType(dict(self.skipped)))

    def __iter__(self) -> Iterator[str]:
        """Iterate over the chosen instruments, so a selection reads as a list."""
        return iter(self.names)

    def __len__(self) -> int:
        """Return how many instruments were chosen."""
        return len(self.names)

    def __contains__(self, instrument_id: object) -> bool:
        """Return whether an instrument was chosen."""
        return instrument_id in self.names

    def __getitem__(self, index: int) -> str:
        """Return one chosen instrument by position."""
        return self.names[index]


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """The decision instant, as a strategy sees it.

    Attributes
    ----------
    as_of : datetime
        When the decision is taken. Timezone-aware, and shared by everything
        below.
    signals : SignalSnapshot
        Every signal computed for this decision.
    market : StrategyMarketView
        What the market says at this instant, status and staleness included.
    portfolio : PortfolioView
        The book as it stands, before the order this decision will produce.
    universe : tuple[str, ...]
        The instruments the book may hold on this session. A strategy may read
        anything the registry declares, and may only target these.
    instruments : InstrumentRegistry
        Static description of each series, used to refuse a target the book
        could not actually take.

    Raises
    ------
    ValueError
        If the instant is naive, if the signals, the market or the portfolio
        answer for another one, or if the universe repeats a name. A context
        whose parts disagree about *when* is the one thing this object exists
        to make impossible.
    """

    as_of: datetime
    signals: SignalSnapshot
    market: StrategyMarketView
    portfolio: PortfolioView
    universe: tuple[str, ...]
    instruments: InstrumentRegistry

    def __post_init__(self) -> None:
        """Check every part of the context answers for the same instant."""
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError(f"as_of must be a timezone-aware datetime, got {self.as_of!r}")
        for what, instant in (
            ("the signals", self.signals.as_of),
            ("the market view", self.market.as_of),
            ("the portfolio view", self.portfolio.as_of),
        ):
            if instant != self.as_of:
                raise ValueError(
                    f"{what} answer for {instant} and the decision is taken at {self.as_of}"
                )
        universe = tuple(self.universe)
        repeated = sorted(name for name, seen in Counter(universe).items() if seen > 1)
        if repeated:
            raise ValueError(f"the universe holds {', '.join(repeated)} more than once")
        object.__setattr__(self, "universe", universe)

    # -- reading the signals ----------------------------------------------

    def signal(self, signal_id: str) -> pd.DataFrame:
        """Return one signal's frame, diagnostics included.

        Parameters
        ----------
        signal_id : str
            Signal to read.

        Returns
        -------
        pd.DataFrame
            A copy: writing into it changes nothing anyone else will see.

        Raises
        ------
        KeyError
            If the snapshot holds no such signal - a strategy naming one the
            engine was not given is a wiring mistake, not an empty day.
        """
        return self.signals.values(signal_id)

    def signal_value(self, signal_id: str, instrument_id: str) -> float:
        """Return one signal's value for one instrument.

        Parameters
        ----------
        signal_id : str
            Signal to read.
        instrument_id : str
            Instrument to read it for.

        Returns
        -------
        float
            The number.

        Raises
        ------
        KeyError
            If the signal or the instrument is not in the snapshot.
        UnusableSignal
            If the status is not ``OK``. The alternative is a ``NaN``, which
            compares false against every threshold: the strategy would take the
            "otherwise" branch without anything saying why.
        """
        status = self.signals.status(signal_id, instrument_id)
        if status is not SignalStatus.OK:
            raise UnusableSignal(
                f"{signal_id} has no usable value for {instrument_id}: {status.value}. "
                "Read the status, or use signal_value_or_none, if this is a day to decide on."
            )
        return self.signals.value(signal_id, instrument_id)

    def signal_status(self, signal_id: str, instrument_id: str) -> SignalStatus:
        """Return why one signal's value for one instrument is what it is."""
        return self.signals.status(signal_id, instrument_id)

    def signal_value_or_none(self, signal_id: str, instrument_id: str) -> float | None:
        """Return one signal's value, or ``None`` when it is not usable.

        Parameters
        ----------
        signal_id : str
            Signal to read.
        instrument_id : str
            Instrument to read it for.

        Returns
        -------
        float | None
            The number, or ``None`` for any status other than ``OK``.

        Notes
        -----
        For a strategy that has a rule for the missing case and says so -
        ``if vix is None or vix > 1.5``. Reaching for it everywhere turns every
        data problem into the same silent branch, which is what
        :meth:`signal_value` exists to prevent.
        """
        if self.signals.status(signal_id, instrument_id) is not SignalStatus.OK:
            return None
        return self.signals.value(signal_id, instrument_id)

    # -- choosing instruments ---------------------------------------------

    def top(self, signal_id: str, count: int) -> Selection:
        """Return the ``count`` best-ranked instruments of a signal.

        Parameters
        ----------
        signal_id : str
            Signal to sort on, highest first.
        count : int
            How many to keep. Fewer come back when fewer are usable, and that
            is a decision the strategy then takes: holding two names at half
            the capital each is not the same as doubling a bet because a
            provider was late.

        Returns
        -------
        Selection
            The names, how many were usable, and why the others were not.

        Raises
        ------
        ValueError
            If ``count`` is not a positive whole number.
        KeyError
            If the snapshot holds no such signal.
        """
        return self._ranked(signal_id, count, best_first=True)

    def bottom(self, signal_id: str, count: int) -> Selection:
        """Return the ``count`` worst-ranked instruments of a signal."""
        return self._ranked(signal_id, count, best_first=False)

    def where(self, signal_id: str, predicate: Callable[[float], bool]) -> Selection:
        """Return the instruments whose usable value satisfies a test.

        Parameters
        ----------
        signal_id : str
            Signal to read.
        predicate : Callable[[float], bool]
            Applied to each usable value; anything it accepts is selected.

        Returns
        -------
        Selection
            The instruments kept, in the order the signal lists them, with the
            usable count and the reasons the others were dropped.

        Notes
        -----
        Kept deliberately small. A filter that grows a language of its own -
        operators, combinators, a parser - would be a second way of writing
        Python, and the first one works.
        """
        frame = self.signals.values(signal_id)
        usable = frame.loc[frame["status"] == SignalStatus.OK]
        names = tuple(
            str(name)
            for name, value in zip(usable.index, usable["value"], strict=True)
            if predicate(float(value))
        )
        return Selection(
            names=names,
            considered=len(usable),
            skipped=self._skipped(frame, names),
        )

    def _ranked(self, signal_id: str, count: int, *, best_first: bool) -> Selection:
        """Return the ``count`` instruments at one end of a signal's ordering."""
        require_positive_int(count, "count")
        frame = self.signals.values(signal_id)
        usable = frame.loc[frame["status"] == SignalStatus.OK]
        # Stable, so instruments that tie keep the order the universe was asked
        # in - the only tie-break available here, and one the ranking itself
        # recorded rather than this layer inventing another.
        ordered = usable.sort_values("value", ascending=not best_first, kind="stable")
        names = tuple(str(name) for name in ordered.index[:count])
        return Selection(
            names=names,
            considered=len(usable),
            skipped=self._skipped(frame, names),
        )

    @staticmethod
    def _skipped(frame: pd.DataFrame, chosen: Sequence[str]) -> dict[str, SignalStatus]:
        """Return why each instrument of a signal's frame was not chosen."""
        skipped: dict[str, SignalStatus] = {}
        for name, status in zip(frame.index, frame["status"], strict=True):
            if str(name) not in chosen:
                assert isinstance(status, SignalStatus)
                skipped[str(name)] = status
        return skipped

    # -- expressing a decision --------------------------------------------

    def weights(
        self, weights: Mapping[str, float], among: Selection | None = None
    ) -> TargetAllocation:
        """Return the allocation holding these instruments at these fractions.

        Parameters
        ----------
        weights : Mapping[str, float]
            Fraction of capital per instrument. What is not allocated is not
            invested; the sum may be less than one and never more.
        among : Selection | None
            The selection these weights came from, when there was one. It
            carries how many instruments were usable and why the others were
            not, which is what lets a report tell a strategy that stood aside
            from one that had nothing to choose from.

        Returns
        -------
        TargetAllocation
            The decision, stamped at this instant.

        Raises
        ------
        ValueError
            If an instrument is not in this session's universe, if it is not
            tradable, or if a weight is not a finite fraction of ``[0, 1]``.
            All three are configuration mistakes rather than market
            situations, so they stop the run instead of becoming a flat day.
        """
        chosen = tuple(weights)
        for instrument_id, weight in weights.items():
            require_unit_fraction(weight, f"the weight of {instrument_id}")
            self._require_targetable(instrument_id)
        total = math.fsum(weights.values())
        if total > 1.0 + WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"the target weights add up to {total}, and this book does not borrow")
        return TargetAllocation(
            as_of=self.as_of,
            weights=dict(weights),
            selected=chosen,
            considered=self._considered(among, len(chosen)),
            skipped=self._reasons(among, chosen),
        )

    def equal_weight(
        self, selected: Selection | Sequence[str], count: int | None = None
    ) -> TargetAllocation:
        """Return the allocation holding these instruments in equal parts.

        Parameters
        ----------
        selected : Selection | Sequence[str]
            The instruments to hold.
        count : int | None
            How many parts the capital is split into. The number of
            instruments by default; give it explicitly when a strategy means
            "the two best" and only one is usable today, so that the one is
            held at half the capital rather than at all of it.

        Returns
        -------
        TargetAllocation
            The decision.

        Raises
        ------
        ValueError
            If an instrument appears twice, if ``count`` is not positive, or if
            it is below the number of instruments given - which would ask for
            more than the whole book.
        """
        names = tuple(selected)
        repeated = sorted(name for name, seen in Counter(names).items() if seen > 1)
        if repeated:
            raise ValueError(
                f"{', '.join(repeated)} is selected more than once; the weights would "
                "collapse into one position and the book would be half invested "
                "without saying so"
            )
        parts = len(names) if count is None else count
        if parts == 0:
            return self.cash(among=selected if isinstance(selected, Selection) else None)
        require_positive_int(parts, "count")
        if parts < len(names):
            raise ValueError(f"{len(names)} instrument(s) cannot be held in {parts} equal parts")
        weight = 1.0 / parts
        return self.weights(
            {name: weight for name in names},
            among=selected if isinstance(selected, Selection) else None,
        )

    def cash(self, among: Selection | None = None) -> TargetAllocation:
        """Return the allocation that holds nothing.

        Parameters
        ----------
        among : Selection | None
            What the strategy was choosing among when it decided to stand
            aside. Worth passing: a flat day with instruments considered is a
            strategy saying no, and a flat day with none is a data hole, and a
            report cannot tell them apart otherwise.

        Returns
        -------
        TargetAllocation
            Nothing held, everything in cash.
        """
        return TargetAllocation(
            as_of=self.as_of,
            weights={},
            selected=(),
            considered=self._considered(among, 0),
            skipped=self._reasons(among, ()),
        )

    def hold_positions(self, among: Selection | None = None) -> TargetAllocation:
        """Return the decision to keep every position exactly as it is.

        Parameters
        ----------
        among : Selection | None
            What the strategy was choosing among, as for :meth:`cash`.

        Returns
        -------
        TargetAllocation
            The book's own weights at this decision, marked as a hold: no order
            is sent for it at the next open, however far the prices move
            overnight. A risk limit the book breaches still trades it down.

        Raises
        ------
        ValueError
            If the book holds an instrument this session's universe does not,
            or one the registry says is not tradable. Both mean the book can no
            longer be kept as a decision, and a strategy asking to keep it has
            to say what it wants instead.

        Notes
        -----
        Not the same decision as :meth:`cash`, and the difference matters on
        exactly the days it is hardest to see. A signal that cannot be computed
        today leaves two honest policies - stand aside, or do not trade on bad
        data - and a framework that offered only ``cash()`` would quietly make
        every strategy choose the first.

        Nor is it the same as asking for the weights the book has. Those are
        the weights of this close, and at the next open the prices have moved:
        two funds drift apart overnight, and a target restated in weights
        trades the drift every morning - a "hold" that only a minimum trade
        value keeps still. This one sends nothing.
        """
        held = dict(self.portfolio.weights)
        for instrument_id in held:
            self._require_targetable(instrument_id)
        return replace(self.weights(held, among=among), hold_positions=True)

    def keep_and_buy(
        self, purchases: Mapping[str, float], among: Selection | None = None
    ) -> TargetAllocation:
        """Return the decision to keep every held position and buy new ones.

        Parameters
        ----------
        purchases : Mapping[str, float]
            Fraction of capital per instrument not held yet. Together with the
            book's own weights they may not exceed the whole book.
        among : Selection | None
            What the strategy was choosing among, as for :meth:`cash`.

        Returns
        -------
        TargetAllocation
            The book's weights for what it holds, marked as kept - no order,
            however the prices move overnight - and the purchases beside them.

        Raises
        ------
        ValueError
            If a purchase names an instrument already held - resizing a kept
            line is a rebalancing, not a purchase - or if anything held or
            bought is not targetable, as for :meth:`weights`.

        Notes
        -----
        The partial form of :meth:`hold_positions`, for a book still being
        built: a basket whose first purchase went through for some names and
        not others completes the rest with the cash left, and the lines it
        already has are not traded back to equal weights on the way.
        """
        held = dict(self.portfolio.weights)
        again = sorted(set(purchases) & set(held))
        if again:
            raise ValueError(
                f"{', '.join(again)} is held already; a kept line is not bought again, and "
                "resizing it is a rebalancing"
            )
        for instrument_id in held:
            self._require_targetable(instrument_id)
        return replace(self.weights({**held, **purchases}, among=among), kept=frozenset(held))

    def _require_targetable(self, instrument_id: str) -> None:
        """Raise unless the book may actually hold this instrument."""
        if instrument_id not in self.universe:
            raise ValueError(
                f"{instrument_id} is not in this session's universe "
                f"({', '.join(self.universe) or 'empty'}); it can be read, not held"
            )
        if not self.instruments.get(instrument_id).tradable:
            raise ValueError(
                f"{instrument_id} is declared tradable = false: a strategy may read it "
                "and may not hold it"
            )

    @staticmethod
    def _considered(among: Selection | None, chosen: int) -> int:
        """Return how many instruments the decision was taken among."""
        return chosen if among is None else among.considered

    @staticmethod
    def _reasons(among: Selection | None, chosen: Sequence[str]) -> dict[str, SignalStatus]:
        """Return why each instrument that was not chosen was not."""
        if among is None:
            return {}
        return {name: status for name, status in among.skipped.items() if name not in chosen}
