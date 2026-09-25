"""Membership is dated, because a list of names is a list of the survivors.

The arithmetic here is trivial - a date falls inside a window or it does not -
and that is the point: the whole value of the module is that the question gets
asked at all, on the session the decision was taken, rather than once with
today's index.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    Instrument,
    InstrumentRegistry,
)
from quant_backtester.data.universes import (
    Membership,
    StaticUniverse,
    Universe,
    UniverseRegistry,
    universe_definition,
)


@pytest.fixture
def registry() -> InstrumentRegistry:
    """Return two funds, one of them delisted in the middle of 2026."""
    return InstrumentRegistry(
        [
            Instrument(
                id="ALIVE",
                name="A fund that is still there",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="ALIVE.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=date(2026, 1, 5),
            ),
            Instrument(
                id="GONE",
                name="A fund that was delisted",
                asset_type=AssetType.ETF,
                data_type=DataType.BAR,
                currency="EUR",
                primary_source="YAHOO",
                source_symbol="GONE.PA",
                tradable=True,
                calendar_id="XPAR",
                first_session=date(2026, 1, 5),
                last_session=date(2026, 6, 30),
            ),
        ]
    )


def write(path: Path, text: str) -> Path:
    """Write a universes file and return its path."""
    path.write_text(text, encoding="utf-8")
    return path


def test_a_name_that_left_is_still_in_the_universe_before_it_did() -> None:
    """The whole point: the run sees what was there, not what is there now."""
    universe = Universe(
        universe_id="TWO",
        name="Two funds",
        memberships=(
            Membership("ALIVE"),
            Membership("GONE", until_date=date(2026, 6, 30)),
        ),
    )

    assert universe.members_at(date(2026, 3, 2)) == ("ALIVE", "GONE")
    assert universe.members_at(date(2026, 6, 30)) == ("ALIVE", "GONE")
    assert universe.members_at(date(2026, 7, 1)) == ("ALIVE",)


def test_a_name_that_joined_later_is_not_there_before(registry: InstrumentRegistry) -> None:
    """A member added to an index in June was not in it in March."""
    universe = Universe(
        universe_id="ONE",
        name="One fund, from June",
        memberships=(Membership("ALIVE", from_date=date(2026, 6, 1)),),
    )

    assert universe.members_at(date(2026, 3, 2)) == ()
    assert universe.members_at(date(2026, 6, 1)) == ("ALIVE",)


def test_a_universe_can_be_empty_on_a_day() -> None:
    """An answer, not a failure: the strategy has nothing to choose from."""
    universe = Universe(
        universe_id="GAP",
        name="A universe with a gap",
        memberships=(Membership("ALIVE", until_date=date(2026, 3, 31)),),
    )

    assert universe.members_at(date(2026, 4, 1)) == ()


def test_a_name_that_came_back_has_two_stays() -> None:
    """Leaving an index and rejoining it is ordinary, and it is two windows."""
    universe = Universe(
        universe_id="BACK",
        name="Out and back",
        memberships=(
            Membership("ALIVE", until_date=date(2026, 3, 31)),
            Membership("ALIVE", from_date=date(2026, 9, 1)),
        ),
    )

    assert universe.members_at(date(2026, 2, 2)) == ("ALIVE",)
    assert universe.members_at(date(2026, 5, 4)) == ()
    assert universe.members_at(date(2026, 9, 2)) == ("ALIVE",)


def test_two_stays_that_overlap_are_a_mistake() -> None:
    """The file was edited twice for the same period and nobody noticed."""
    with pytest.raises(ValueError, match="overlapping stays"):
        Universe(
            universe_id="TWICE",
            name="Twice over",
            memberships=(
                Membership("ALIVE", until_date=date(2026, 6, 30)),
                Membership("ALIVE", from_date=date(2026, 6, 1)),
            ),
        )


def test_a_stay_that_ends_before_it_starts_is_refused() -> None:
    """A typo, and the day it is read is the day to say so."""
    with pytest.raises(ValueError, match="before it started"):
        Membership("ALIVE", from_date=date(2026, 6, 1), until_date=date(2026, 3, 1))


def test_a_universe_with_no_member_is_refused() -> None:
    """Nobody could choose from it, and a run over it would say nothing."""
    with pytest.raises(ValueError, match="holds no member"):
        Universe(universe_id="EMPTY", name="Empty", memberships=())


# --- the committed file ------------------------------------------------------


def test_a_file_is_read_with_its_dates(tmp_path: Path, registry: InstrumentRegistry) -> None:
    """TOML dates are dates; reading them as strings is how a bound gets lost."""
    path = write(
        tmp_path / "universes.toml",
        """
[[universe]]
id = "ROTATION"
name = "A rotation of two"

[[universe.member]]
instrument_id = "ALIVE"

[[universe.member]]
instrument_id = "GONE"
until_date = 2026-06-30
""",
    )

    universes = UniverseRegistry.from_toml(path, registry)

    rotation = universes.get("ROTATION")
    assert rotation.name == "A rotation of two"
    assert rotation.members_at(date(2026, 5, 4)) == ("ALIVE", "GONE")
    assert rotation.members_at(date(2026, 7, 1)) == ("ALIVE",)
    assert rotation.instruments() == ("ALIVE", "GONE")


def test_a_member_nobody_declared_is_refused(tmp_path: Path, registry: InstrumentRegistry) -> None:
    """Caught when the file is read, not when a backtest reaches that date."""
    path = write(
        tmp_path / "universes.toml",
        """
[[universe]]
id = "ROTATION"

[[universe.member]]
instrument_id = "NEVER_HEARD_OF_IT"
""",
    )

    with pytest.raises(KeyError, match="NEVER_HEARD_OF_IT"):
        UniverseRegistry.from_toml(path, registry)


def test_a_stay_outside_the_listing_window_is_refused(
    tmp_path: Path, registry: InstrumentRegistry
) -> None:
    """A name cannot be in an index after it stopped existing.

    The file says GONE was a member until September; the registry says it was
    delisted in June. One of the two is wrong, and a backtest that trusted the
    file would be holding a fund nobody could deal in.
    """
    path = write(
        tmp_path / "universes.toml",
        """
[[universe]]
id = "ROTATION"

[[universe.member]]
instrument_id = "GONE"
until_date = 2026-09-30
""",
    )

    with pytest.raises(ValueError, match="outside its listing window"):
        UniverseRegistry.from_toml(path, registry)


def test_a_date_time_is_not_a_date(tmp_path: Path, registry: InstrumentRegistry) -> None:
    """Membership changes at a session boundary, not at an instant."""
    path = write(
        tmp_path / "universes.toml",
        """
[[universe]]
id = "ROTATION"

[[universe.member]]
instrument_id = "ALIVE"
from_date = 2026-06-01T09:00:00Z
""",
    )

    with pytest.raises(ValueError, match="must be a TOML date"):
        UniverseRegistry.from_toml(path, registry)


def test_an_unknown_key_is_a_typo(tmp_path: Path, registry: InstrumentRegistry) -> None:
    """``form_date`` would silently mean "a member since the beginning"."""
    path = write(
        tmp_path / "universes.toml",
        """
[[universe]]
id = "ROTATION"

[[universe.member]]
instrument_id = "ALIVE"
form_date = 2026-06-01
""",
    )

    with pytest.raises(ValueError, match="unknown key"):
        UniverseRegistry.from_toml(path, registry)


def test_two_universes_cannot_share_an_id(tmp_path: Path, registry: InstrumentRegistry) -> None:
    """One would hide the other, and a config file is not a place for that."""
    path = write(
        tmp_path / "universes.toml",
        """
[[universe]]
id = "ROTATION"

[[universe.member]]
instrument_id = "ALIVE"

[[universe]]
id = "ROTATION"

[[universe.member]]
instrument_id = "GONE"
""",
    )

    with pytest.raises(ValueError, match="share the id"):
        UniverseRegistry.from_toml(path, registry)


def test_asking_for_a_universe_nobody_declared_is_loud(
    tmp_path: Path, registry: InstrumentRegistry
) -> None:
    """A wiring mistake in a strategy config, named as one."""
    path = write(
        tmp_path / "universes.toml",
        """
[[universe]]
id = "ROTATION"

[[universe.member]]
instrument_id = "ALIVE"
""",
    )
    universes = UniverseRegistry.from_toml(path, registry)

    assert "ROTATION" in universes
    assert len(universes) == 1
    with pytest.raises(KeyError, match="MOMENTUM"):
        universes.get("MOMENTUM")


# --- the static one ----------------------------------------------------------


def test_a_static_universe_answers_the_same_thing_every_day() -> None:
    """For two funds that both existed throughout, and nothing else."""
    static = StaticUniverse(("ETF_EU", "IDX_US"))

    assert static.members_at(date(2020, 1, 1)) == ("ETF_EU", "IDX_US")
    assert static.members_at(date(2030, 1, 1)) == ("ETF_EU", "IDX_US")


def test_a_static_universe_refuses_a_repeated_name() -> None:
    """Twice in a universe would weight it twice in a ranking."""
    with pytest.raises(ValueError, match="more than once"):
        StaticUniverse(("ETF_EU", "ETF_EU"))


def test_a_static_universe_does_not_remember_the_order_it_was_written_in() -> None:
    """The same names in two orders are the same universe, and record the same definition."""
    forward = StaticUniverse(("ETF_EU", "ETF_OTHER"))
    backward = StaticUniverse(("ETF_OTHER", "ETF_EU"))

    assert forward == backward
    assert backward.members_at(date(2026, 9, 1)) == ("ETF_EU", "ETF_OTHER")
    assert universe_definition(forward) == universe_definition(backward)


def test_an_open_bound_is_closed_with_the_listing_window(
    tmp_path: Path, registry: InstrumentRegistry
) -> None:
    """A fund launched in 2026 was not a member of anything in 2025.

    The file says nothing about when ALIVE joined, which reads as "since it
    existed" and not as "since the beginning of time". Left open, a run
    reaching back a year would hand the strategy a name to rank that had not
    been listed yet.
    """
    path = write(
        tmp_path / "universes.toml",
        """
[[universe]]
id = "ROTATION"

[[universe.member]]
instrument_id = "ALIVE"

[[universe.member]]
instrument_id = "GONE"
""",
    )

    rotation = UniverseRegistry.from_toml(path, registry).get("ROTATION")

    assert rotation.members_at(date(2025, 6, 2)) == ()
    assert rotation.members_at(date(2026, 1, 5)) == ("ALIVE", "GONE")
    # GONE was delisted on 30 June and the file did not have to say so.
    assert rotation.members_at(date(2026, 7, 1)) == ("ALIVE",)


def test_the_committed_universes_hold_together() -> None:
    """The file a result is reproduced from is read, checked and dated.

    A universe naming an instrument nobody declared, or a member dated outside
    its listing window, would only show up when a backtest reached that date.
    This reads it on every run of the suite instead.
    """
    metadata = Path(__file__).resolve().parents[2] / "market_data" / "metadata"
    instruments = InstrumentRegistry.from_toml(metadata / "instruments.toml")

    universes = UniverseRegistry.from_toml(metadata / "universes.toml", instruments)

    rotation = universes.get("ROTATION_2")
    assert rotation.members_at(date(2026, 9, 17)) == ("ETF_SP500_PEA", "ETF_WORLD")
    # Both funds are PEA-eligible, both are quoted in euros, and both can be
    # dealt at the open a decision is filled at - which is what makes them a
    # trading universe rather than a list of things worth reading.
    assert all(
        instruments.get(member).tradable and instruments.get(member).currency == "EUR"
        for member in rotation.members_at(date(2026, 9, 17))
    )
    # The world ETF's first session is in 2018, and the universe starts with it.
    assert rotation.members_at(date(2015, 1, 5)) == ()
