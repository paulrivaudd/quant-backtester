"""The rules, as pure functions: signal values in, target weights out.

Each function takes the numbers its rule reads - ``None`` for one that could
not be computed - and every parameter of the rule, none defaulted. It returns
the complete theoretical target, before any rebalancing band: an instrument
that is not in the weights has a target of zero.

A rule missing a mandatory input returns an empty target with
:data:`MISSING_INPUT`. Nothing else inherits its capital.

Returns and volatilities are decimal fractions: ``0.12`` is 12%.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

MISSING_INPUT: Final[str] = "MISSING_INPUT"
"""A mandatory input could not be computed: the rule is inactive."""

INVESTED: Final[str] = "INVESTED"
"""The rule holds something."""

STANDS_ASIDE: Final[str] = "STANDS_ASIDE"
"""Every input was read and the rule holds nothing."""

NEUTRAL: Final[str] = "NEUTRAL"
"""A tilt rule with nothing to tilt on: the neutral split."""


@dataclass(frozen=True, slots=True)
class RuleTarget:
    """What one rule wants to hold, and how it got there.

    Attributes
    ----------
    weights : Mapping[str, float]
        Fraction of the rule's own capital per instrument, each strictly
        positive, together at most one. What is left is cash.
    reason : str
        :data:`MISSING_INPUT`, :data:`INVESTED`, :data:`STANDS_ASIDE` or
        :data:`NEUTRAL`.
    diagnostics : Mapping[str, float]
        The intermediate numbers of the rule, by name.
    """

    weights: Mapping[str, float]
    reason: str
    diagnostics: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        """Drop the zero weights and freeze both mappings."""
        kept = {name: float(weight) for name, weight in self.weights.items() if weight > 0.0}
        object.__setattr__(self, "weights", MappingProxyType(kept))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def active(self) -> bool:
        """Return whether every mandatory input of the rule was read."""
        return self.reason != MISSING_INPUT


def clip(value: float, low: float, high: float) -> float:
    """Return ``value`` bounded to ``[low, high]``."""
    return max(low, min(high, value))


def _missing() -> RuleTarget:
    """Return the empty target of a rule that could not read an input."""
    return RuleTarget({}, MISSING_INPUT)


def _settled(weights: Mapping[str, float], diagnostics: Mapping[str, float]) -> RuleTarget:
    """Return a target that says whether it holds anything."""
    invested = any(weight > 0.0 for weight in weights.values())
    return RuleTarget(weights, INVESTED if invested else STANDS_ASIDE, diagnostics)


def above_average_rule(instrument_id: str, distance: float | None) -> RuleTarget:
    """Rule 0: all of the fund while its close is strictly above its average.

    Parameters
    ----------
    instrument_id : str
        The fund.
    distance : float | None
        ``P_t / MA_N(t) - 1``.

    Returns
    -------
    RuleTarget
        100% of the fund for a strictly positive distance, cash on the average
        or below it, and an inactive rule without a distance.
    """
    if distance is None:
        return _missing()
    return _settled({instrument_id: 1.0 if distance > 0.0 else 0.0}, {"distance": distance})


def dual_momentum_rule(
    first_id: str,
    second_id: str,
    *,
    first_medium: float | None,
    first_long: float | None,
    second_medium: float | None,
    second_long: float | None,
    full_tilt_gap: float,
    neutral_weight: float,
    tilt: float,
    single_weight: float,
) -> RuleTarget:
    """Rule 1: lean towards the fund with the stronger momentum, among the rising ones.

    Parameters
    ----------
    first_id, second_id : str
        The two funds.
    first_medium, first_long, second_medium, second_long : float | None
        Each fund's medium and long momentum, as fractions.
    full_tilt_gap : float
        Difference of scores at which the tilt is complete.
    neutral_weight : float
        Weight of the first fund when the scores are equal.
    tilt : float
        Largest move away from the neutral weight.
    single_weight : float
        Weight of a fund that is the only eligible one.

    Returns
    -------
    RuleTarget
        ``score = (medium + long) / 2`` and a fund is eligible when its long
        momentum is strictly positive. Both eligible:
        ``w_first = neutral + tilt * clip((score_first - score_second) / gap, -1, 1)``
        and the rest in the second. One eligible: ``single_weight`` of it.
        None: cash.
    """
    if first_medium is None or first_long is None or second_medium is None or second_long is None:
        return _missing()
    first_score = (first_medium + first_long) / 2.0
    second_score = (second_medium + second_long) / 2.0
    diagnostics = {"first_score": first_score, "second_score": second_score}
    first_eligible, second_eligible = first_long > 0.0, second_long > 0.0
    if first_eligible and second_eligible:
        lean = clip((first_score - second_score) / full_tilt_gap, -1.0, 1.0)
        first_weight = neutral_weight + tilt * lean
        return _settled(
            {first_id: first_weight, second_id: 1.0 - first_weight}, {**diagnostics, "lean": lean}
        )
    if first_eligible:
        return _settled({first_id: single_weight}, diagnostics)
    if second_eligible:
        return _settled({second_id: single_weight}, diagnostics)
    return _settled({}, diagnostics)


def smooth_trend_rule(
    instrument_id: str, cross: float | None, *, full_exposure_gap: float
) -> RuleTarget:
    """Rule 2: an exposure growing with the gap between two moving averages.

    Parameters
    ----------
    instrument_id : str
        The fund.
    cross : float | None
        ``MA_fast / MA_slow - 1``.
    full_exposure_gap : float
        Gap at which the rule is fully invested.

    Returns
    -------
    RuleTarget
        ``w = clip(cross / full_exposure_gap, 0, 1)``.
    """
    if cross is None:
        return _missing()
    return _settled({instrument_id: clip(cross / full_exposure_gap, 0.0, 1.0)}, {"cross": cross})


def pullback_rule(
    instrument_id: str,
    pullback: float | None,
    trend_distance: float | None,
    *,
    maximum_weight: float,
    entry_z: float,
    z_range: float,
) -> RuleTarget:
    """Rule 3: buy an unusual fall, moderately, and only above the long average.

    Parameters
    ----------
    instrument_id : str
        The fund.
    pullback : float | None
        The recent fall in earlier standard deviations, positive after a fall.
    trend_distance : float | None
        ``P_t / MA_N(t) - 1`` for the long average.
    maximum_weight : float
        Weight reached at ``entry_z + z_range`` and never exceeded.
    entry_z : float
        Fall at or below which nothing is held.
    z_range : float
        Width over which the weight grows from zero to its maximum.

    Returns
    -------
    RuleTarget
        ``w = maximum_weight * clip((z - entry_z) / z_range, 0, 1)``, and zero
        when the close is on its long average or below it.
    """
    if pullback is None or trend_distance is None:
        return _missing()
    diagnostics = {"pullback": pullback, "trend_distance": trend_distance}
    if trend_distance <= 0.0:
        return _settled({}, diagnostics)
    weight = maximum_weight * clip((pullback - entry_z) / z_range, 0.0, 1.0)
    return _settled({instrument_id: weight}, diagnostics)


def relative_tilt_rule(
    first_id: str,
    second_id: str,
    residual_z: float | None,
    *,
    full_tilt_z: float,
    neutral_weight: float,
    tilt: float,
) -> RuleTarget:
    """Rule 4: overweight the fund that lately lagged what the other explains of it.

    Parameters
    ----------
    first_id, second_id : str
        The fund the residual is measured on, and its reference.
    residual_z : float | None
        Minus the first fund's recent residual in its own spreads: positive
        when it lagged. Zero when the fit is not one to lean on.
    full_tilt_z : float
        Residual at which the tilt is complete.
    neutral_weight : float
        Weight of the first fund without a residual to act on.
    tilt : float
        Largest move away from the neutral weight.

    Returns
    -------
    RuleTarget
        ``w_first = neutral + tilt * clip(z / full_tilt_z, -1, 1)`` and the
        rest in the second. A residual that has no value leaves the rule
        inactive: cash, not the neutral split.
    """
    if residual_z is None:
        return _missing()
    lean = clip(residual_z / full_tilt_z, -1.0, 1.0)
    first_weight = neutral_weight + tilt * lean
    reason = NEUTRAL if lean == 0.0 else INVESTED
    return RuleTarget(
        {first_id: first_weight, second_id: 1.0 - first_weight},
        reason,
        {"residual_z": residual_z, "lean": lean},
    )


def conservative_volatility(
    short_volatility: float | None, long_volatility: float | None, *, floor: float
) -> float | None:
    """Return ``max(short, long, floor)``, or ``None`` when either estimate is missing."""
    if short_volatility is None or long_volatility is None:
        return None
    return max(short_volatility, long_volatility, floor)


def volatility_control_rule(
    instrument_id: str,
    short_volatility: float | None,
    long_volatility: float | None,
    *,
    target_volatility: float,
    floor: float,
) -> RuleTarget:
    """Rule 5: scale the exposure down when the fund's realised volatility rises.

    Parameters
    ----------
    instrument_id : str
        The fund.
    short_volatility, long_volatility : float | None
        Two annualised realised volatilities, as fractions.
    target_volatility : float
        The estimated annualised risk aimed at.
    floor : float
        Smallest volatility the estimate may take.

    Returns
    -------
    RuleTarget
        ``w = min(1, target / max(short, long, floor))``. The book does not
        borrow, so a quiet market is held at 100% and no more.
    """
    estimate = conservative_volatility(short_volatility, long_volatility, floor=floor)
    if estimate is None:
        return _missing()
    return _settled(
        {instrument_id: min(1.0, target_volatility / estimate)}, {"volatility": estimate}
    )


def forecast_volatility_rule(
    instrument_id: str,
    forecast_volatility: float | None,
    *,
    target_volatility: float,
    floor: float,
) -> RuleTarget:
    """Scale the exposure to one forecast of the fund's volatility, never above 100%.

    Parameters
    ----------
    instrument_id : str
        The fund.
    forecast_volatility : float | None
        The annualised volatility forecast for the next session, as a fraction.
    target_volatility : float
        The estimated annualised risk aimed at.
    floor : float
        Smallest volatility the forecast may take in the allocation.

    Returns
    -------
    RuleTarget
        ``w = min(1, target / max(forecast, floor))``: rule 5 with a single
        estimate in place of the larger of two. A forecast that has no value
        leaves the rule inactive: cash.
    """
    if forecast_volatility is None:
        return _missing()
    estimate = max(forecast_volatility, floor)
    return _settled(
        {instrument_id: min(1.0, target_volatility / estimate)}, {"volatility": estimate}
    )


def direction_gate(
    mean: float, *, held: bool, entry_threshold: float, exit_threshold: float
) -> bool:
    """Return whether a forecast mean keeps, or opens, a position: a gate with hysteresis.

    Parameters
    ----------
    mean : float
        The forecast return of the next period a position can be held over.
    held : bool
        Whether the fund is actually held at the decision - the book, not the
        target asked for the day before.
    entry_threshold : float
        A book in cash enters strictly above it.
    exit_threshold : float
        A held position is kept strictly above it, and sold at it.

    Returns
    -------
    bool
        ``mean > exit_threshold`` for a position held, ``mean >
        entry_threshold`` from cash. Equality at the entry does not buy;
        equality at the exit sells.
    """
    return mean > (exit_threshold if held else entry_threshold)


def gated_volatility_rule(
    instrument_id: str,
    mean: float | None,
    volatility: float | None,
    *,
    held: bool,
    entry_threshold: float,
    exit_threshold: float,
    target_volatility: float,
    floor: float,
    gated: bool,
) -> RuleTarget:
    """Hold a fund sized to its risk while a forecast mean lets it be held.

    Parameters
    ----------
    instrument_id : str
        The fund.
    mean : float | None
        The forecast return the gate reads, as a fraction.
    volatility : float | None
        The annualised volatility the position is sized on, as a fraction.
    held : bool
        Whether the fund is actually held at the decision.
    entry_threshold, exit_threshold : float
        The two thresholds of :func:`direction_gate`.
    target_volatility : float
        The estimated annualised risk aimed at.
    floor : float
        Smallest volatility the sizing may take.
    gated : bool
        ``False`` for the control that sizes the same risk with the gate
        always open, whatever the mean says.

    Returns
    -------
    RuleTarget
        ``w = g * min(1, target / max(volatility, floor))`` with ``g`` the
        gate. Either input missing leaves the rule inactive: cash. The mean is
        never used to size the position.
    """
    if mean is None or volatility is None:
        return _missing()
    active = direction_gate(
        mean, held=held, entry_threshold=entry_threshold, exit_threshold=exit_threshold
    )
    estimate = max(volatility, floor)
    weight = min(1.0, target_volatility / estimate) if (active or not gated) else 0.0
    return _settled(
        {instrument_id: weight},
        {"mean": mean, "volatility": estimate, "gate": 1.0 if active else 0.0},
    )


def factor_blend_rule(
    volatilities: Mapping[str, float | None],
    *,
    floor: float,
    maximum_weight: float,
    equal_share: float,
) -> RuleTarget:
    """Rule 6: half equal weights, half inverse volatility, each fund capped.

    Parameters
    ----------
    volatilities : Mapping[str, float | None]
        Annualised realised volatility of each fund of the blend.
    floor : float
        Smallest volatility a fund is given.
    maximum_weight : float
        Cap on each fund. What it cuts stays in cash: nothing is renormalised.
    equal_share : float
        Share of the capital split equally; the rest is split by inverse
        volatility.

    Returns
    -------
    RuleTarget
        ``a_i = 1 / max(vol_i, floor)``, ``q_i = a_i / sum(a)`` and
        ``w_i = min(maximum_weight, equal_share / n + (1 - equal_share) * q_i)``.
        Inactive unless every fund has a volatility.
    """
    if not volatilities or any(value is None for value in volatilities.values()):
        return _missing()
    inverse = {
        name: 1.0 / max(value, floor) for name, value in volatilities.items() if value is not None
    }
    total = math.fsum(inverse.values())
    weights = {
        name: min(
            maximum_weight,
            equal_share / len(inverse) + (1.0 - equal_share) * strength / total,
        )
        for name, strength in inverse.items()
    }
    return _settled(weights, {})


def monetary_carry_rule(
    instrument_id: str,
    momentum: float | None,
    volatility: float | None,
    *,
    lookback_sessions: int,
    annualization: int,
    horizon_years: float,
    round_trip_cost: float,
    maximum_volatility: float,
) -> RuleTarget:
    """Rule 7: hold a money-market fund when its recent carry pays for the round trip.

    Parameters
    ----------
    instrument_id : str
        The money-market fund.
    momentum : float | None
        ``P_t / P_{t-L} - 1`` over ``lookback_sessions``.
    volatility : float | None
        Its annualised realised volatility.
    lookback_sessions : int
        ``L``, the sessions the momentum was measured over.
    annualization : int
        Sessions per year.
    horizon_years : float
        How long the carry is given to cover the cost, in years.
    round_trip_cost : float
        Estimated cost of buying then selling, as a fraction.
    maximum_volatility : float
        Largest annualised volatility a money-market fund may show.

    Returns
    -------
    RuleTarget
        ``c = (annualization / L) * ln(1 + momentum)``, a backward-looking
        annual carry, and 100% of the fund when
        ``exp(c * horizon_years) - 1 > round_trip_cost`` and
        ``volatility <= maximum_volatility``; cash otherwise.
    """
    if momentum is None or volatility is None or momentum <= -1.0:
        return _missing()
    carry = (annualization / lookback_sessions) * math.log1p(momentum)
    eligible = (
        math.expm1(carry * horizon_years) > round_trip_cost and volatility <= maximum_volatility
    )
    return _settled(
        {instrument_id: 1.0 if eligible else 0.0}, {"carry": carry, "volatility": volatility}
    )


def relief_entry_rule(
    instrument_id: str, relief: float | None, recovery: float | None, *, weight: float
) -> RuleTarget:
    """Rule 8: a small position once a panic eases and the fund starts to rise.

    Parameters
    ----------
    instrument_id : str
        The fund bought.
    relief : float | None
        ``1.0`` when the volatility gauge has left a panic peak behind,
        ``0.0`` otherwise.
    recovery : float | None
        The fund's return over the last few sessions.
    weight : float
        The position taken.

    Returns
    -------
    RuleTarget
        ``weight`` of the fund when the gauge is in a relief and the recovery
        is strictly positive; cash as soon as either stops.
    """
    if relief is None or recovery is None:
        return _missing()
    held = relief > 0.5 and recovery > 0.0
    return _settled(
        {instrument_id: weight if held else 0.0}, {"relief": relief, "recovery": recovery}
    )


def risk_scale(
    weights: Mapping[str, float],
    volatilities: Mapping[str, float],
    *,
    target_volatility: float,
    cash_volatility: float,
) -> float:
    """Return the factor that brings a book's estimated risk down to its target.

    Parameters
    ----------
    weights : Mapping[str, float]
        ``v_i``, the weight of each equity fund before the control.
    volatilities : Mapping[str, float]
        ``s_i``, the annualised volatility estimate of each of them.
    target_volatility : float
        The estimated annualised risk the book may carry.
    cash_volatility : float
        ``s_m``, the volatility of what the rest of the book is placed in:
        zero for cash.

    Returns
    -------
    float
        ``lambda = min(1, max(0, (target - s_m) / (S - V * s_m)))`` with
        ``V = sum(v_i)`` and ``S = sum(v_i * s_i)``, and ``0.0`` for an empty
        book. Every correlation is taken as ``+1``, which bounds the estimate
        from above without a covariance matrix.

    Raises
    ------
    KeyError
        If a weighted fund has no volatility.
    ValueError
        If the funds are not riskier than what the rest is placed in.
    """
    total = math.fsum(weights.values())
    if total <= 0.0:
        return 0.0
    risk = math.fsum(weight * volatilities[name] for name, weight in weights.items())
    excess = risk - total * cash_volatility
    if excess <= 0.0:
        raise ValueError(
            f"the funds carry {risk} of risk for {total} of weight, not more than "
            f"{cash_volatility} per unit: there is nothing to scale"
        )
    return clip((target_volatility - cash_volatility) / excess, 0.0, 1.0)
