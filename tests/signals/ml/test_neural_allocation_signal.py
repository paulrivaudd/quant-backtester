"""The network's proposal as a signal: one input, one run, one row per tradable fund."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from quant_backtester.data.reader import MarketDataReader
from quant_backtester.ml.artifacts import NeuralArtifact
from quant_backtester.ml.features import NeuralFeatureBuilder
from quant_backtester.signals.base import SignalResult
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.ml.neural_allocation import (
    DIAGNOSTIC_COLUMNS,
    NeuralAllocationSignal,
)
from quant_backtester.signals.types import SignalStatus

FUNDS = ("ETF_EU", "ETF_OTHER")
DECISION = date(2026, 9, 14)

Compute = Callable[..., SignalResult]


def evening(day: date) -> datetime:
    """Return the decision instant of a session: 23:00 in Paris."""
    return datetime(day.year, day.month, day.day, 23, 0, tzinfo=ZoneInfo("Europe/Paris"))


def signal_of(artifact: NeuralArtifact) -> NeuralAllocationSignal:
    """Return the signal of a model, its network loaded."""
    return NeuralAllocationSignal(
        signal_id="neural_allocation_weights",
        config=artifact.config,
        model_id=artifact.model_id,
        information_cutoff=artifact.information_cutoff,
        _runtime=artifact.runtime(),
    )


@pytest.fixture
def compute(neural_artifact: NeuralArtifact, calendars) -> Compute:
    """Return the signal's answer for one decision on a given store."""

    def at(reader: MarketDataReader, day: date = DECISION) -> SignalResult:
        context = SignalContext(
            market=reader.at(evening(day)), instruments=reader.instruments, calendars=calendars
        )
        return signal_of(neural_artifact).compute(context, FUNDS)

    return at


def test_each_fund_gets_its_weight_and_cash_is_the_complement(
    compute: Compute, neural_market: MarketDataReader, neural_artifact: NeuralArtifact
) -> None:
    result = compute(neural_market)
    frame = result.frame

    assert result.instruments() == FUNDS
    assert set(DIAGNOSTIC_COLUMNS) <= set(frame.columns)
    assert list(frame["status"]) == [SignalStatus.OK, SignalStatus.OK]
    assert all(0.0 < weight < 1.0 for weight in frame["value"])
    assert frame["value"].sum() + frame["cash_weight"].iloc[0] == pytest.approx(1.0)
    assert set(frame["model_id"]) == {neural_artifact.model_id}
    assert set(frame["faulty_series"]) == {""}
    # Three series of six observations, the freshest of them today's.
    assert list(frame["observations_used"]) == [18, 18]
    assert list(frame["max_input_age_sessions"]) == [0, 0]
    assert set(frame["input_end_date"]) == {DECISION}
    assert json.loads(frame["series_ages"].iloc[0]) == {"ETF_EU": 0, "ETF_OTHER": 0, "RATE_US": 0}


def test_the_signal_predicts_what_the_offline_builder_and_the_network_give(
    compute: Compute, neural_market: MarketDataReader, neural_artifact: NeuralArtifact, calendars
) -> None:
    """One input for training and for a decision: the same vector, the same prediction."""
    context = SignalContext(
        market=neural_market.at(evening(DECISION)),
        instruments=neural_market.instruments,
        calendars=calendars,
    )
    offline = NeuralFeatureBuilder(neural_artifact.config).build(context)
    vector = offline.values  # noqa: PD011 - a FeatureVector, not a frame
    assert vector is not None
    expected, clipped = neural_artifact.runtime().propose(np.asarray(vector))

    frame = compute(neural_market).frame

    assert list(frame["value"]) == pytest.approx(list(expected[:2]), abs=1e-12)
    assert frame["cash_weight"].iloc[0] == pytest.approx(expected[2], abs=1e-12)
    assert set(frame["clipped_values"]) == {clipped}


def test_one_unusable_series_leaves_every_fund_without_a_value(
    compute: Compute, make_neural_market: Callable[..., MarketDataReader]
) -> None:
    def stop_publishing(bars, levels) -> None:
        for day in [day for day in levels if day > date(2026, 9, 9)]:
            del levels[day]

    frame = compute(make_neural_market(mutate=stop_publishing)).frame

    assert list(frame["status"]) == [SignalStatus.STALE_INPUT, SignalStatus.STALE_INPUT]
    assert all(math.isnan(value) for value in frame["value"])
    assert all(math.isnan(value) for value in frame["cash_weight"])
    assert set(frame["faulty_series"]) == {"RATE_US:STALE_INPUT"}
    assert list(frame["max_input_age_sessions"]) == [3, 3]
    assert list(frame["observations_used"].isna()) == [True, True]


def test_data_added_after_a_decision_leaves_its_answer_unchanged(
    compute: Compute,
    neural_market: MarketDataReader,
    make_neural_market: Callable[..., MarketDataReader],
) -> None:
    """The look-ahead guard, with a frozen model."""

    def rewrite_the_future(bars, levels) -> None:
        for prices in bars.values():
            for day in [day for day in prices if day > DECISION]:
                prices[day] = tuple(value * 0.3 for value in prices[day])
        for day in [day for day in levels if day > DECISION]:
            levels[day] = 70.0

    rewritten = compute(make_neural_market("future", mutate=rewrite_the_future)).frame

    pd.testing.assert_frame_equal(rewritten, compute(neural_market).frame)


def test_a_weight_follows_its_fund_whatever_order_the_engine_asks_in(
    compute: Compute,
    neural_artifact: NeuralArtifact,
    neural_market: MarketDataReader,
    calendars,
) -> None:
    """The engine asks in its canonical order, which need not be the outputs' order."""
    context = SignalContext(
        market=neural_market.at(evening(DECISION)),
        instruments=neural_market.instruments,
        calendars=calendars,
    )
    asked = compute(neural_market)

    swapped = signal_of(neural_artifact).compute(context, ("ETF_OTHER", "ETF_EU"))

    assert swapped.instruments() == ("ETF_OTHER", "ETF_EU")
    assert swapped.value("ETF_EU") == asked.value("ETF_EU")
    assert swapped.value("ETF_OTHER") == asked.value("ETF_OTHER")
    assert asked.value("ETF_EU") != asked.value("ETF_OTHER")
    for wrong in (("ETF_EU",), ("ETF_EU", "ETF_LATE"), ("ETF_EU", "ETF_OTHER", "ETF_LATE")):
        with pytest.raises(ValueError, match="for nothing else"):
            signal_of(neural_artifact).compute(context, wrong)


def test_the_definition_names_the_model_and_not_its_memory_address(
    neural_artifact: NeuralArtifact,
) -> None:
    first, second = signal_of(neural_artifact), signal_of(neural_artifact)

    assert first.definition()["model_id"] == neural_artifact.model_id
    assert first.definition()["config"] == neural_artifact.config.definition()
    assert first.fingerprint() == second.fingerprint()
    assert first == second
    assert "runtime" not in repr(first)
    json.dumps(first.definition_json())
