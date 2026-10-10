"""The log-signature adapter: its basis, its algebra, and the features built from it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

import numpy as np
import pytest

from quant_backtester.data.calendars import TradingCalendar
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.signals.context import SignalContext
from quant_backtester.signals.models.garch import MissingDependency
from quant_backtester.signals.signatures import logsignature
from quant_backtester.signals.signatures.logsignature import (
    BACKEND,
    HALL_KEYS,
    BackendMismatch,
    FeatureKind,
    FeatureSpec,
    SignatureFeatureBuilder,
    kept_keys,
    log_signature,
    require_esig,
    select_backend,
)
from quant_backtester.signals.signatures.path import (
    SignaturePathConfig,
    build_signature_path,
    load_path_inputs,
)
from quant_backtester.signals.types import SignalStatus

pytest.importorskip("esig")
pytest.importorskip("roughpy")

A = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.5], [1.0, 1.0, 1.0]])
B = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.5], [1.0, 1.0, 1.0]])
"""The price moves first, then the volume; and the other way round."""


def test_the_basis_is_the_hall_basis_recorded() -> None:
    import esig

    assert select_backend() == BACKEND == "esig_roughpy"
    for depth, size in ((2, 6), (3, 14)):
        assert tuple(str(esig.logsigkeys(3, depth)).split()) == HALL_KEYS[depth]
        assert esig.logsigdim(3, depth) == len(HALL_KEYS[depth]) == size
    assert len(kept_keys(2)) == 5 and len(kept_keys(3)) == 13


def test_only_the_displacement_of_time_is_removed() -> None:
    kept = kept_keys(3)

    assert "3" not in kept
    assert {"[1,3]", "[2,3]", "[1,[1,3]]", "[3,[1,2]]", "[3,[2,3]]"} <= set(kept)
    assert kept == tuple(key for key in HALL_KEYS[3] if key != "3")  # never re-sorted
    with pytest.raises(ValueError, match="order 2 or 3"):
        kept_keys(4)


def test_the_reference_example_of_the_specification() -> None:
    """Same displacements, opposite areas: the order of the moves is what is measured."""
    first, second = log_signature(A, 2), log_signature(B, 2)

    assert list(first[:2]) == pytest.approx([1.0, 1.0])
    assert list(second[:2]) == pytest.approx([1.0, 1.0])
    assert list(first[2:]) == pytest.approx([0.5, 0.25, -0.25])
    assert list(second[2:]) == pytest.approx([-0.5, -0.25, 0.25])
    assert log_signature(A, 3).shape == (13,)


def test_a_straight_segment_has_a_displacement_and_nothing_above() -> None:
    line = np.outer(np.linspace(0.0, 1.0, 5), [2.0, -1.0, 1.0])

    values = log_signature(line, 3)

    assert list(values[:2]) == pytest.approx([2.0, -1.0])
    assert np.allclose(values[2:], 0.0, atol=1e-12)


def test_a_translation_changes_nothing_and_neither_does_a_point_on_a_segment() -> None:
    moved = A + np.array([7.0, -3.0, 0.0])
    subdivided = np.array([[0.0, 0.0, 0.0], [0.5, 0.0, 0.25], [1.0, 0.0, 0.5], [1.0, 1.0, 1.0]])

    assert np.allclose(log_signature(moved, 3), log_signature(A, 3), atol=1e-12)
    assert np.allclose(log_signature(subdivided, 3), log_signature(A, 3), atol=1e-12)


def test_the_adapter_takes_points_not_increments() -> None:
    """The first level is the last point less the first: a cumulated path would double it."""
    rng = np.random.default_rng(1)
    increments = np.column_stack(
        [rng.normal(0.0, 1.0, 9), rng.uniform(0.0, 1.0, 9), np.full(9, 1.0 / 9)]
    )
    points = np.vstack([np.zeros(3), np.cumsum(increments, axis=0)])

    values = log_signature(points, 3)

    assert list(values[:2]) == pytest.approx(list(points[-1, :2] - points[0, :2]))
    assert not np.allclose(log_signature(np.cumsum(points, axis=0), 3)[:2], values[:2])


@pytest.mark.parametrize(
    ("path", "match"),
    [
        (A[:, :2], "points"),
        (A[:1], "points"),
        (np.where(A == 0.5, np.nan, A), "not finite"),
        (A[::-1], "strictly increase"),
        (np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 1.0]]), "strictly increase"),
    ],
)
def test_a_path_the_adapter_does_not_accept_is_refused(path: np.ndarray, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        log_signature(path, 3)


def test_a_backend_that_answers_another_basis_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    import esig

    monkeypatch.setattr(esig, "logsigkeys", lambda width, depth: " 2 1 3 [1,2] [1,3] [2,3]")

    with pytest.raises(BackendMismatch, match="basis at order 2"):
        log_signature(A, 2)


def test_missing_libraries_stop_the_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logsignature.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(MissingDependency, match="signatures extra"):
        require_esig()
    with pytest.raises(MissingDependency):
        log_signature(A, 2)


# --- the features of one decision ----------------------------------------------------------

SignatureMarketBuilder = Callable[..., MarketDataReader]
Contexts = Callable[[MarketDataReader, date], SignalContext]


@pytest.fixture
def year(xpar: TradingCalendar) -> list[date]:
    """Return every Paris session of 2026 from the funds' first one."""
    return [session.session_date for session in xpar.sessions(date(2026, 1, 5), date(2026, 12, 31))]


@pytest.fixture
def at(
    make_context: Callable[[MarketDataReader, datetime], SignalContext],
    evening: Callable[[date], datetime],
) -> Contexts:
    """Return the context of a decision after the close of a day."""
    return lambda market, day: make_context(market, evening(day))


def spec_of(
    path: SignaturePathConfig,
    kind: FeatureKind = FeatureKind.LOGSIGNATURE,
    depth: int = 3,
    instruments: tuple[str, ...] = ("ETF_EU",),
) -> FeatureSpec:
    """Return a specification on the short path of the tests."""
    return FeatureSpec(kind, path, depth, instruments)


def test_the_names_are_qualified_by_their_process_in_the_order_of_the_blocks(
    signature_path: SignaturePathConfig,
) -> None:
    core = spec_of(signature_path)
    context = spec_of(signature_path, instruments=("ETF_EU", "ETF_OTHER"))

    assert len(core.names()) == 13 and len(spec_of(signature_path, depth=2).names()) == 5
    assert core.names()[:3] == ("ETF_EU:1", "ETF_EU:2", "ETF_EU:[1,2]")
    assert len(context.names()) == 26
    assert context.names()[:13] == core.names()
    assert context.names()[13] == "ETF_OTHER:1" and context.names()[-1] == "ETF_OTHER:[3,[2,3]]"
    assert len(spec_of(signature_path, FeatureKind.CLASSICAL).names()) == 9
    assert len(spec_of(signature_path, FeatureKind.RAW_TRAJECTORY).names()) == 20
    definition = core.definition()
    assert (definition["backend"], definition["basis"], definition["drop_keys"]) == (
        "esig_roughpy",
        "HALL",
        ["3"],
    )
    assert "backend" not in spec_of(signature_path, FeatureKind.CLASSICAL).definition()


@pytest.mark.parametrize(
    "build",
    [
        lambda path: FeatureSpec(FeatureKind.LOGSIGNATURE, path, 3, ()),
        lambda path: FeatureSpec(FeatureKind.LOGSIGNATURE, path, 3, ("ETF_EU", "ETF_EU")),
        lambda path: FeatureSpec(FeatureKind.LOGSIGNATURE, path, 4, ("ETF_EU",)),
        lambda path: FeatureSpec("LOGSIGNATURE", path, 3, ("ETF_EU",)),  # type: ignore[arg-type]
    ],
)
def test_a_specification_no_vector_can_come_from_is_refused(
    build: Callable[[SignaturePathConfig], object], signature_path: SignaturePathConfig
) -> None:
    with pytest.raises(ValueError):
        build(signature_path)


def test_each_window_is_recomputed_from_its_own_points(
    make_signature_market: SignatureMarketBuilder,
    at: Contexts,
    year: list[date],
    signature_path: SignaturePathConfig,
) -> None:
    """A sliding window is not updated by adding and removing a term: it is rebuilt."""
    market = make_signature_market()
    builder = SignatureFeatureBuilder(spec_of(signature_path))

    for day in year[60:64]:
        context = at(market, day)
        built = builder.build(context)
        inputs = load_path_inputs(context, "ETF_EU", signature_path)
        path = build_signature_path(
            inputs.adjusted_closes, inputs.raw_closes, inputs.volumes, signature_path
        )
        assert built.status is SignalStatus.OK and built.values is not None
        assert np.array_equal(np.asarray(built.values), log_signature(path, 3))
        assert (built.window_start, built.window_end) == (inputs.dates[0], day)
        assert built.names == spec_of(signature_path).names()


def test_two_blocks_are_concatenated_in_order_and_one_missing_makes_no_vector(
    make_signature_market: SignatureMarketBuilder,
    at: Contexts,
    year: list[date],
    signature_path: SignaturePathConfig,
) -> None:
    def late(frames: dict) -> None:
        frames["ETF_OTHER"] = frames["ETF_OTHER"].loc[
            frames["ETF_OTHER"]["session_date"] >= year[90]
        ]

    both = spec_of(signature_path, instruments=("ETF_EU", "ETF_OTHER"))
    whole = SignatureFeatureBuilder(both).build(at(make_signature_market("a"), year[100]))
    core = SignatureFeatureBuilder(spec_of(signature_path)).build(
        at(make_signature_market("b"), year[100])
    )
    other = SignatureFeatureBuilder(spec_of(signature_path, instruments=("ETF_OTHER",))).build(
        at(make_signature_market("c"), year[100])
    )
    partial = SignatureFeatureBuilder(both).build(
        at(make_signature_market("d", mutate=late), year[100])
    )

    assert whole.values is not None and core.values is not None and other.values is not None
    assert len(whole.values) == 26
    assert whole.values == (*core.values, *other.values)
    # A required block that is missing does not fall back on the blocks that are there.
    assert partial.values is None and partial.status is SignalStatus.INSUFFICIENT_HISTORY
    assert partial.reason is not None and partial.reason.startswith("ETF_OTHER:")
    assert partial.names == both.names()


def test_what_happens_after_the_decision_changes_no_feature_of_either_block(
    make_signature_market: SignatureMarketBuilder,
    at: Contexts,
    year: list[date],
    signature_path: SignaturePathConfig,
) -> None:
    def later(frames: dict) -> None:
        for frame in frames.values():
            after = frame["session_date"] > year[100]
            frame.loc[after, ["open", "high", "low", "close"]] *= 0.5
            frame.loc[after, "volume"] *= 9.0

    builder = SignatureFeatureBuilder(spec_of(signature_path, instruments=("ETF_EU", "ETF_OTHER")))

    before = builder.build(at(make_signature_market("a"), year[100]))
    after = builder.build(at(make_signature_market("b", mutate=later), year[100]))

    assert after == before


def test_a_window_without_a_reference_or_without_a_trade_is_invalid_input(
    make_signature_market: SignatureMarketBuilder,
    at: Contexts,
    year: list[date],
    signature_path: SignaturePathConfig,
) -> None:
    def no_reference(frames: dict) -> None:
        frame = frames["ETF_EU"]
        frame.loc[frame["session_date"].isin(year[81:91]), "volume"] = 0.0

    built = SignatureFeatureBuilder(spec_of(signature_path)).build(
        at(make_signature_market(mutate=no_reference), year[100])
    )

    assert built.status is SignalStatus.INVALID_INPUT and built.values is None
    assert built.reason == "ETF_EU:ZERO_VOLUME_REFERENCE"


def test_the_two_controls_are_built_from_the_same_window(
    make_signature_market: SignatureMarketBuilder,
    at: Contexts,
    year: list[date],
    signature_path: SignaturePathConfig,
) -> None:
    context = at(make_signature_market(), year[100])
    signature = SignatureFeatureBuilder(spec_of(signature_path)).build(context)
    raw = SignatureFeatureBuilder(spec_of(signature_path, FeatureKind.RAW_TRAJECTORY)).build(
        context
    )

    assert signature.values is not None and raw.values is not None
    assert len(raw.values) == 20
    # The first level of the log-signature is the sum of the increments the control reads.
    assert signature.values[0] == pytest.approx(sum(raw.values[:10]))
    assert signature.values[1] == pytest.approx(sum(raw.values[10:]) / 10)
    assert (raw.window_start, raw.window_end) == (signature.window_start, signature.window_end)
