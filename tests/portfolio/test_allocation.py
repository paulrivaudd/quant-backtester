"""From what a strategy asked for to what the book may hold: both kept, every cut named."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from quant_backtester.data.instruments import InstrumentRegistry
from quant_backtester.portfolio.allocation import (
    ConstrainedTarget,
    PortfolioDecision,
    PortfolioModel,
)
from quant_backtester.portfolio.constraints import (
    CurrencyMismatch,
    NonTradableInstrument,
    OutsideTradingUniverse,
)
from quant_backtester.portfolio.limits import LimitAdjustment, PortfolioLimits
from quant_backtester.portfolio.targets import TargetAllocation
from quant_backtester.signals.types import SignalStatus

AS_OF = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)
UNIVERSE = ("ETF_EU", "ETF_OTHER")


def decide(
    model: PortfolioModel, weights: dict[str, float], instruments: InstrumentRegistry
) -> PortfolioDecision:
    """Hold a request to the model's rules, for a euro book over the usual universe."""
    return model.decide(
        TargetAllocation(as_of=AS_OF, weights=weights),
        instruments=instruments,
        universe=UNIVERSE,
        base_currency="EUR",
    )


# -- the model ---------------------------------------------------------------------


def test_an_admissible_target_inside_the_limits_is_accepted_as_asked(
    instruments: InstrumentRegistry,
) -> None:
    """Fifty-fifty asked, fifty-fifty allowed, nothing to explain."""
    decision = decide(PortfolioModel(), {"ETF_EU": 0.5, "ETF_OTHER": 0.5}, instruments)

    assert dict(decision.accepted_weights) == {"ETF_EU": 0.5, "ETF_OTHER": 0.5}
    assert not decision.constrained.was_adjusted


def test_a_known_limit_clips_explicitly_and_keeps_what_was_asked(
    instruments: InstrumentRegistry,
) -> None:
    """Seventy asked against a fifty cap: fifty allowed, seventy remembered, the reason named."""
    model = PortfolioModel(PortfolioLimits(max_weight_per_instrument=0.5))

    decision = decide(model, {"ETF_EU": 0.7, "ETF_OTHER": 0.3}, instruments)

    assert dict(decision.constrained.requested_weights) == {"ETF_EU": 0.7, "ETF_OTHER": 0.3}
    assert dict(decision.accepted_weights) == {"ETF_EU": 0.5, "ETF_OTHER": 0.3}
    assert dict(decision.constrained.adjustments) == {
        "ETF_EU": (LimitAdjustment.CAPPED_AT_MAX_WEIGHT,)
    }
    assert decision.constrained.requested_invested == pytest.approx(1.0)
    assert decision.constrained.invested == pytest.approx(0.8)


def test_an_instrument_nobody_can_buy_is_an_error_and_never_a_silent_clip(
    instruments: InstrumentRegistry,
) -> None:
    """Clipping an index to zero would report a rotation whose orders were never sent."""
    with pytest.raises(NonTradableInstrument):
        decide(PortfolioModel(), {"ETF_EU": 0.5, "IDX_US": 0.5}, instruments)


def test_a_fund_in_another_currency_is_an_error(instruments: InstrumentRegistry) -> None:
    """A euro book cannot hold a dollar fund without an FX engine."""
    with pytest.raises(CurrencyMismatch):
        decide(PortfolioModel(), {"ETF_US": 1.0}, instruments)


def test_a_fund_outside_the_day_s_universe_is_an_error(instruments: InstrumentRegistry) -> None:
    """A dated universe decides what may be held on the day, not the strategy."""
    with pytest.raises(OutsideTradingUniverse):
        decide(PortfolioModel(), {"ETF_LATE": 1.0}, instruments)


def test_what_the_strategy_said_about_its_choice_is_carried_through(
    instruments: InstrumentRegistry,
) -> None:
    """A limit changes sizes; it does not change what the signals said."""
    requested = TargetAllocation(
        as_of=AS_OF,
        weights={"ETF_EU": 0.9},
        selected=("ETF_EU",),
        considered=2,
        skipped={"ETF_OTHER": SignalStatus.STALE_INPUT},
    )

    decision = PortfolioModel(PortfolioLimits(max_weight_per_instrument=0.4)).decide(
        requested, instruments=instruments, universe=UNIVERSE, base_currency="EUR"
    )

    assert decision.requested is requested
    assert decision.selected == ("ETF_EU",)
    assert decision.considered == 2
    assert dict(decision.skipped) == {"ETF_OTHER": SignalStatus.STALE_INPUT}
    assert decision.as_of == AS_OF


def test_the_model_describes_itself_for_the_record() -> None:
    """A result says which limits the book was held to."""
    assert PortfolioModel(PortfolioLimits(max_gross=0.8)).definition() == {
        "limits": {
            "max_weight_per_instrument": 1.0,
            "max_gross": 0.8,
            "long_only": True,
            "applies_to": "target weights, before costs",
        }
    }


# -- the constrained target -----------------------------------------------------------


def constrained(**overrides: object) -> ConstrainedTarget:
    """Build a constrained target with a cap applied to A."""
    parameters: dict[str, object] = {
        "as_of": AS_OF,
        "requested_weights": {"A": 0.7, "B": 0.3},
        "accepted_weights": {"A": 0.5, "B": 0.3},
        "adjustments": {"A": (LimitAdjustment.CAPPED_AT_MAX_WEIGHT,)},
    }
    parameters.update(overrides)
    return ConstrainedTarget(**parameters)  # type: ignore[arg-type]


def test_a_weight_that_moved_without_a_reason_is_refused() -> None:
    """A difference nobody can explain is the one thing an audit trail must not contain."""
    with pytest.raises(ValueError, match="do not say why"):
        constrained(adjustments={})


def test_a_reason_for_a_weight_that_did_not_move_is_refused() -> None:
    """A reason with nothing to explain is as misleading as a change with none."""
    with pytest.raises(ValueError, match="do not say why"):
        constrained(
            adjustments={
                "A": (LimitAdjustment.CAPPED_AT_MAX_WEIGHT,),
                "B": (LimitAdjustment.SCALED_TO_MAX_GROSS,),
            }
        )


def test_a_limit_only_ever_takes_out() -> None:
    """An accepted weight above its request is not a limit at work."""
    with pytest.raises(ValueError, match="only ever takes out"):
        constrained(
            accepted_weights={"A": 0.8, "B": 0.3},
            adjustments={"A": (LimitAdjustment.CAPPED_AT_MAX_WEIGHT,)},
        )


def test_both_sides_speak_about_the_same_instruments() -> None:
    """An instrument dropped between the two would be a silent rejection."""
    with pytest.raises(ValueError, match="not the same instruments"):
        constrained(accepted_weights={"A": 0.5})


def test_a_reason_must_be_a_limit() -> None:
    """A free-text reason cannot be counted in a report."""
    with pytest.raises(ValueError, match="not a limit"):
        constrained(adjustments={"A": ("too big",)})


def test_an_adjustment_of_something_never_requested_is_refused() -> None:
    """There is nothing to have cut."""
    with pytest.raises(ValueError, match="never requested"):
        constrained(
            adjustments={
                "A": (LimitAdjustment.CAPPED_AT_MAX_WEIGHT,),
                "C": (LimitAdjustment.CAPPED_AT_MAX_WEIGHT,),
            }
        )


def test_a_constrained_target_is_stamped_with_a_timezone() -> None:
    """It answers for one decision."""
    with pytest.raises(ValueError, match="timezone-aware"):
        constrained(as_of=datetime(2026, 9, 14, 21, 0))


def test_a_constrained_target_cannot_be_edited_afterwards() -> None:
    """It is part of the record of a run."""
    target = constrained()

    with pytest.raises(TypeError):
        target.accepted_weights["A"] = 0.7  # type: ignore[index]
    with pytest.raises(TypeError):
        target.adjustments["B"] = ()  # type: ignore[index]


def test_a_constrained_target_says_how_much_was_asked_and_allowed() -> None:
    """Target against target, before either is compared with what was held."""
    target = constrained()

    assert target.requested_invested == pytest.approx(1.0)
    assert target.invested == pytest.approx(0.8)
    assert target.gross == pytest.approx(0.8)
    assert target.was_adjusted


# -- the decision -------------------------------------------------------------------------


def test_a_decision_answers_for_one_instant() -> None:
    """A request and a constraint of two different decisions are not one decision."""
    requested = TargetAllocation(as_of=AS_OF, weights={"A": 0.7, "B": 0.3})

    with pytest.raises(ValueError, match="answered for"):
        PortfolioDecision(
            requested=requested, constrained=constrained(as_of=AS_OF + timedelta(days=1))
        )


def test_a_decision_constrains_exactly_what_was_requested() -> None:
    """The constrained side starts from the weights the strategy returned, not others."""
    requested = TargetAllocation(as_of=AS_OF, weights={"A": 0.6, "B": 0.4})

    with pytest.raises(ValueError, match="does not start from what was requested"):
        PortfolioDecision(requested=requested, constrained=constrained())


# -- keeping the book --------------------------------------------------------------------


def test_a_book_kept_within_the_limits_is_kept(instruments: InstrumentRegistry) -> None:
    """Nothing to cut, so nothing to trade: the hold goes through."""
    requested = TargetAllocation(
        as_of=AS_OF, weights={"ETF_EU": 0.4, "ETF_OTHER": 0.5}, hold_positions=True
    )

    decision = PortfolioModel().decide(
        requested, instruments=instruments, universe=UNIVERSE, base_currency="EUR"
    )

    assert decision.holds_positions
    assert dict(decision.accepted_weights) == {"ETF_EU": 0.4, "ETF_OTHER": 0.5}


def test_a_limit_the_kept_book_breaches_overrules_the_hold(
    instruments: InstrumentRegistry,
) -> None:
    """A position that drifted past a cap is traded down to it: policy wins over inertia."""
    requested = TargetAllocation(
        as_of=AS_OF, weights={"ETF_EU": 0.7, "ETF_OTHER": 0.3}, hold_positions=True
    )

    decision = PortfolioModel(PortfolioLimits(max_weight_per_instrument=0.5)).decide(
        requested, instruments=instruments, universe=UNIVERSE, base_currency="EUR"
    )

    assert not decision.holds_positions
    assert dict(decision.accepted_weights) == {"ETF_EU": 0.5, "ETF_OTHER": 0.3}
    assert dict(decision.constrained.adjustments) == {
        "ETF_EU": (LimitAdjustment.CAPPED_AT_MAX_WEIGHT,)
    }


def test_a_constrained_target_cannot_both_hold_and_be_cut() -> None:
    """A cut is a trade; a hold is the absence of one."""
    with pytest.raises(ValueError, match="cannot be kept as it is"):
        constrained(hold_positions=True)


def test_holding_on_a_constrained_target_is_said_as_a_boolean() -> None:
    """Truthy is not a decision."""
    with pytest.raises(ValueError, match="hold_positions"):
        ConstrainedTarget(
            as_of=AS_OF,
            requested_weights={},
            accepted_weights={},
            hold_positions=1,  # type: ignore[arg-type]
        )


def test_a_limit_that_cuts_a_kept_line_trades_it_and_keeps_the_others(
    instruments: InstrumentRegistry,
) -> None:
    """The partial form of the rule above: the cut line is traded, the other kept."""
    requested = TargetAllocation(
        as_of=AS_OF,
        weights={"ETF_EU": 0.7, "ETF_OTHER": 0.2},
        kept=frozenset({"ETF_EU", "ETF_OTHER"}),
    )

    decision = PortfolioModel(PortfolioLimits(max_weight_per_instrument=0.5)).decide(
        requested, instruments=instruments, universe=UNIVERSE, base_currency="EUR"
    )

    assert decision.kept == frozenset({"ETF_OTHER"})
