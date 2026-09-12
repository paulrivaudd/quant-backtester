"""Ingestion: revision policy and the reproducibility property."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Exercice 9.5 - test 3/3")
def test_rebuild_is_idempotent(market_root):
    """Rebuilding the clean layer twice produces identical files.

    This is the test everyone forgets to write, and the one that proves the
    pipeline has no hidden state: no clock read, no dictionary ordering, no
    absolute path leaking into the output.
    """


@pytest.mark.skip(reason="Exercice 7.5")
def test_unaccepted_revision_leaves_history_unchanged(market_root):
    """A provider changing a stored value is logged and ignored by default.

    The same backtest must not print a different number three weeks later
    because Yahoo adjusted a past close by a cent.
    """


@pytest.mark.skip(reason="Exercice 7.5")
def test_accepted_revision_is_applied(market_root):
    """A revision listed in accepted_revisions.toml does get applied."""


@pytest.mark.skip(reason="Exercice 7.4")
def test_new_observations_are_not_reported_as_revisions(market_root):
    """A date present only in the incoming frame is new data, not a revision."""


@pytest.mark.skip(reason="Exercice 9.3")
def test_constant_factor_shift_triggers_a_full_refetch(market_root):
    """A whole-series rebasing is not a revision and must not be merged partially.

    If the overlap differs from the stored rows by a constant factor, the
    provider changed convention. Merging five days into an old basis would
    fabricate a fake move in the middle of the series - one that passes every
    other check.
    """


@pytest.mark.skip(reason="Exercice 3.1")
def test_interrupted_write_leaves_the_previous_file_intact(market_root):
    """An exception mid-write must not destroy the existing dataset."""


@pytest.mark.skip(reason="Exercice 9.2")
def test_invalid_frame_is_archived_raw_but_not_promoted(market_root):
    """A failed validation keeps the raw snapshot and leaves clean untouched."""
