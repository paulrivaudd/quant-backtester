"""The catalogue: one code and one short label per strategy.

Two hundred strategies cannot be told apart by class names and by the order
they were written in. So a strategy that is kept gets a code - a family and a
number, ``SA3`` or ``SA14`` - and a label of two or three words, and that pair
is its name everywhere a person reads one: ``"SA3 - smooth MA"`` in a table or
a figure, ``SA3_smooth_ma`` as the ``strategy_id`` of a result, and
``sa3_smooth_ma`` in the name of a file a run exports.

The files written for one catalogued strategy alone carry its code first: its
module (``SA3_smooth_moving_average.py``), its test file
(``test_SA11_garch_vol_control.py``), its study script
(``SA11_run_garch_study.py``) and the figures that script writes. A module
several strategies share keeps a plain name. Every strategy module sits at the
root of the ``strategies`` package, beside this one.

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

from quant_backtester.signals.types import require_identifier
from quant_backtester.strategies.base import Strategy


class Family(Enum):
    """What kind of reasoning a strategy rests on. The value is the code's prefix."""

    SA = "SA"
    """Systematic rules on prices and published series: trends, momentum,
    pullbacks, relative value, volatility control, blends of those, and weights
    proposed by a model fitted on a training period (``SA13``, ``SA14``)."""


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
    extra : str | None
        The optional dependency group its module imports as soon as it is
        loaded, ``"ml"`` for PyTorch; ``None`` when the class loads without
        any extra.
    recorded_id : str | None
        Explicit result identifier when a retained name differs from the
        spelling derived from the display label.

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
    extra: str | None = None
    recorded_id: str | None = None

    def __post_init__(self) -> None:
        """Refuse an entry that cannot be written as a code, a name and a slug."""
        if isinstance(self.number, bool) or not isinstance(self.number, int) or self.number < 1:
            raise ValueError(f"a catalogue number is a positive integer, got {self.number!r}")
        if not re.fullmatch(r"[A-Za-z0-9]+( [A-Za-z0-9]+)*", self.label):
            raise ValueError(
                f"a label is words of letters and digits separated by one space, got {self.label!r}"
            )
        if self.recorded_id is not None:
            require_identifier(self.recorded_id, "recorded_id")
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
        if self.recorded_id is not None:
            return self.recorded_id
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
            If the module needs an optional dependency that is not installed:
            the one ``extra`` names (``ml`` for ``SA14``). ``SA11`` loads
            without its ``stats`` extra and refuses to run without it.
        TypeError
            If the target is not a strategy.
        """
        module, name = self.target.split(":")
        loaded = getattr(importlib.import_module(module), name)
        if not (isinstance(loaded, type) and issubclass(loaded, Strategy)):
            raise TypeError(f"{self.target} is not a Strategy")
        return loaded


_STRATEGIES = "quant_backtester.strategies"

CATALOGUE: tuple[CatalogueEntry, ...] = (
    CatalogueEntry(
        Family.SA, 1, "std MA20", f"{_STRATEGIES}.SA1_world_ma20_benchmark:WorldMA20Benchmark"
    ),
    CatalogueEntry(
        Family.SA,
        2,
        "dual momentum",
        f"{_STRATEGIES}.SA2_buffered_dual_momentum:BufferedDualMomentum",
    ),
    CatalogueEntry(
        Family.SA, 3, "smooth MA", f"{_STRATEGIES}.SA3_smooth_moving_average:SmoothMovingAverage"
    ),
    CatalogueEntry(
        Family.SA, 4, "pullback", f"{_STRATEGIES}.SA4_trend_filtered_pullback:TrendFilteredPullback"
    ),
    CatalogueEntry(
        Family.SA,
        5,
        "relative tilt",
        f"{_STRATEGIES}.SA5_relative_residual_tilt:RelativeResidualTilt",
    ),
    CatalogueEntry(
        Family.SA, 6, "vol control", f"{_STRATEGIES}.SA6_realized_vol_control:RealizedVolControl"
    ),
    CatalogueEntry(
        Family.SA, 7, "factor blend", f"{_STRATEGIES}.SA7_factor_etf_blend:FactorETFBlend"
    ),
    CatalogueEntry(
        Family.SA, 8, "monetary carry", f"{_STRATEGIES}.SA8_monetary_carry:MonetaryCarry"
    ),
    CatalogueEntry(
        Family.SA, 9, "VIX relief", f"{_STRATEGIES}.SA9_vix_relief_entry:VixReliefEntry"
    ),
    CatalogueEntry(Family.SA, 10, "ensemble", f"{_STRATEGIES}.SA10_etf_ensemble:ETFEnsemble"),
    CatalogueEntry(
        Family.SA, 11, "GARCH vol control", f"{_STRATEGIES}.SA11_garch_vol_control:GarchVolControl"
    ),
    CatalogueEntry(Family.SA, 12, "ARIMA GARCH", f"{_STRATEGIES}.SA12_arima_garch:ArimaGarch"),
    CatalogueEntry(
        Family.SA,
        13,
        "Signatures Neurons",
        f"{_STRATEGIES}.SA13_signatures_neurons:SignaturesNeurons",
    ),
    CatalogueEntry(
        Family.SA,
        14,
        "neural allocation",
        f"{_STRATEGIES}.SA14_neural_allocation:NeuralAllocationStrategy",
        extra="ml",
    ),
    CatalogueEntry(
        Family.SA,
        15,
        "GPT 6 1",
        f"{_STRATEGIES}.SA15_gpt61:SA15GPT61",
        recorded_id="SA15_GPT-6.1",
    ),
    CatalogueEntry(
        Family.SA,
        16,
        "growth gold budget",
        f"{_STRATEGIES}.SA16_risk_budget:SA16RiskBudget",
    ),
)
"""Every catalogued strategy, by number.

``SA1`` to ``SA10`` are the ten ETF rules of 2026-10-03, numbered 0 to 9 in
their specification: ``SA1`` is its benchmark 0, the fund held above its
20-session average, and ``SA10`` its ensemble 9. ``SA11`` is the GARCH
volatility control of 2026-10-10; its estimator is an optional dependency (the
``stats`` extra) that its module imports only when a fit is asked for, so the
entry loads without it. ``SA12`` is the ARIMA-GARCH of the same day, on the same
extra (the label takes no hyphen). ``SA13`` is the signature model of the same
day: it keeps an SA code although its forecasts come from a small network, runs
on a schedule of models calibrated before the backtest, and is built with
``SignaturesNeurons.from_schedule``. ``SA14`` is the neural allocation of
2026-10-04: it was catalogued as ``ML1``, alone in a family of its own, until
2026-10-11, and the code ``ML1`` is not given again. Its module imports PyTorch
when it is loaded, which is what its ``extra`` says. ``SA15`` is the diversified
momentum and volatility-control strategy of 2026-10-15. Its recorded identifier
``SA15_GPT-6.1`` retains the requested spelling through ``recorded_id``.
``SA16`` is the risk budget of 2026-10-31: US technology and gold held
together at inverse-volatility weights scaled by a declared budget of risk;
the configuration its study retained is in ``results/SA16/selected.json``.
The reference books of studies (``quant_backtester.research.references``)
are not candidates and carry
no code. The exercises and the baselines that came before were removed on
2026-10-11.
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
