"""The catalogue: one code and one short label per strategy, by family.

Two hundred strategies cannot be told apart by class names and by the order
they were written in. So a strategy that is kept gets a code - a family and a
number, ``SA3`` or ``ML1`` - and a label of two or three words, and that pair
is its name everywhere a person reads one: ``"SA3 - smooth MA"`` in a table or
a figure, ``SA3_smooth_ma`` as the ``strategy_id`` of a result, and
``sa3_smooth_ma`` in a file name.

A code is given once and never reused: a strategy that is dropped keeps its
number, and the next one takes the next. The label may be reworded; the code
is what a result is traced by. Numbers follow the order of adoption inside a
family and say nothing about merit.

The classes are named by their import path and loaded on demand, so that
listing the catalogue does not import PyTorch for a reader who only wants the
rule-based strategies.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from enum import Enum

from quant_backtester.strategies.base import Strategy


class Family(Enum):
    """What kind of reasoning a strategy rests on. The value is the code's prefix."""

    SA = "SA"
    """Statistical rules on prices and published series: trends, momentum,
    pullbacks, relative value, volatility control, and blends of those."""

    ML = "ML"
    """Weights proposed by a model fitted on a training period."""


@dataclass(frozen=True, slots=True)
class CatalogueEntry:
    """One strategy of the catalogue.

    Attributes
    ----------
    family : Family
        The family it belongs to.
    number : int
        Its rank of adoption in the family, from 1.
    label : str
        Two or three words that tell it from its neighbours.
    target : str
        ``"module:Class"`` of the strategy.

    Raises
    ------
    ValueError
        If the number is not positive, the label is empty or holds a
        character other than letters, digits and spaces, or the target is
        not a ``module:Class`` pair.
    """

    family: Family
    number: int
    label: str
    target: str

    def __post_init__(self) -> None:
        """Refuse an entry that cannot be written as a code, a name and a slug."""
        if isinstance(self.number, bool) or not isinstance(self.number, int) or self.number < 1:
            raise ValueError(f"a catalogue number is a positive integer, got {self.number!r}")
        if not re.fullmatch(r"[A-Za-z0-9]+( [A-Za-z0-9]+)*", self.label):
            raise ValueError(
                f"a label is words of letters and digits separated by one space, got {self.label!r}"
            )
        if self.target.count(":") != 1:
            raise ValueError(f"a target is 'module:Class', got {self.target!r}")

    @property
    def code(self) -> str:
        """Return the family and the number: ``SA3``."""
        return f"{self.family.value}{self.number}"

    @property
    def display_name(self) -> str:
        """Return the name a person reads: ``SA3 - smooth MA``."""
        return f"{self.code} - {self.label}"

    @property
    def strategy_id(self) -> str:
        """Return the identifier a result is recorded under: ``SA3_smooth_ma``."""
        return f"{self.code}_{self.label.lower().replace(' ', '_')}"

    @property
    def slug(self) -> str:
        """Return the name as a file name: ``sa3_smooth_ma``."""
        return self.strategy_id.lower()

    def load(self) -> type[Strategy]:
        """Return the strategy's class, importing its module now.

        Raises
        ------
        ImportError
            If the module needs an optional dependency that is not installed
            (the ``ml`` extra for the ML family). ``SA11`` loads without its
            ``stats`` extra and refuses to run without it.
        TypeError
            If the target is not a strategy.
        """
        module, name = self.target.split(":")
        loaded = getattr(importlib.import_module(module), name)
        if not (isinstance(loaded, type) and issubclass(loaded, Strategy)):
            raise TypeError(f"{self.target} is not a Strategy")
        return loaded


_EXAMPLES = "quant_backtester.strategies.examples"

CATALOGUE: tuple[CatalogueEntry, ...] = (
    CatalogueEntry(
        Family.SA, 1, "std MA20", f"{_EXAMPLES}.world_ma20_benchmark:WorldMA20Benchmark"
    ),
    CatalogueEntry(
        Family.SA, 2, "dual momentum", f"{_EXAMPLES}.buffered_dual_momentum:BufferedDualMomentum"
    ),
    CatalogueEntry(
        Family.SA, 3, "smooth MA", f"{_EXAMPLES}.smooth_moving_average:SmoothMovingAverage"
    ),
    CatalogueEntry(
        Family.SA, 4, "pullback", f"{_EXAMPLES}.trend_filtered_pullback:TrendFilteredPullback"
    ),
    CatalogueEntry(
        Family.SA, 5, "relative tilt", f"{_EXAMPLES}.relative_residual_tilt:RelativeResidualTilt"
    ),
    CatalogueEntry(
        Family.SA, 6, "vol control", f"{_EXAMPLES}.realized_vol_control:RealizedVolControl"
    ),
    CatalogueEntry(Family.SA, 7, "factor blend", f"{_EXAMPLES}.factor_etf_blend:FactorETFBlend"),
    CatalogueEntry(Family.SA, 8, "monetary carry", f"{_EXAMPLES}.monetary_carry:MonetaryCarry"),
    CatalogueEntry(Family.SA, 9, "VIX relief", f"{_EXAMPLES}.vix_relief_entry:VixReliefEntry"),
    CatalogueEntry(
        Family.SA, 10, "ensemble", "quant_backtester.strategies.adaptive.etf_ensemble:ETFEnsemble"
    ),
    CatalogueEntry(
        Family.SA, 11, "GARCH vol control", f"{_EXAMPLES}.garch_vol_control:GarchVolControl"
    ),
    CatalogueEntry(
        Family.ML,
        1,
        "neural allocation",
        "quant_backtester.strategies.ml.neural_allocation:NeuralAllocationStrategy",
    ),
)
"""Every catalogued strategy, by family then by number.

``SA1`` to ``SA10`` are the ten ETF rules of 2026-10-03, numbered 0 to 9 in
their specification: ``SA1`` is its benchmark 0, the fund held above its
20-session average, and ``SA10`` its ensemble 9. ``SA11`` is the GARCH
volatility control of 2026-10-10; its estimator is an optional dependency (the
``stats`` extra) that its module imports only when a fit is asked for, so the
entry loads without it. ``ML1`` is the neural allocation of 2026-10-04. The
exercises and the baselines that came before are not catalogued: they are
examples of how a strategy is written.
"""


def _require_consistent(entries: tuple[CatalogueEntry, ...]) -> None:
    """Raise unless codes and targets are unique and each family counts from one."""
    for family in Family:
        numbers = [entry.number for entry in entries if entry.family is family]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(
                f"the {family.value} family must be numbered 1, 2, 3... in order, got {numbers}"
            )
    for what in ("target", "strategy_id"):
        values = [getattr(entry, what) for entry in entries]
        if len(set(values)) != len(values):
            raise ValueError(f"two catalogue entries share a {what}")


_require_consistent(CATALOGUE)


def entry(code: str) -> CatalogueEntry:
    """Return the entry of a code.

    Parameters
    ----------
    code : str
        A catalogue code such as ``"SA3"``.

    Raises
    ------
    KeyError
        If no strategy carries it.
    """
    for candidate in CATALOGUE:
        if candidate.code == code:
            return candidate
    raise KeyError(f"no strategy is catalogued as {code!r}")


def entry_of(strategy: Strategy | type[Strategy]) -> CatalogueEntry:
    """Return the entry of a strategy, by its class.

    Parameters
    ----------
    strategy : Strategy | type[Strategy]
        An instance or its class.

    Raises
    ------
    KeyError
        If the class is not catalogued.
    """
    kind = strategy if isinstance(strategy, type) else type(strategy)
    target = f"{kind.__module__}:{kind.__qualname__}"
    for candidate in CATALOGUE:
        if candidate.target == target:
            return candidate
    raise KeyError(f"{target} is not in the catalogue")


def family(members: Family) -> tuple[CatalogueEntry, ...]:
    """Return the entries of one family, by number."""
    return tuple(candidate for candidate in CATALOGUE if candidate.family is members)
