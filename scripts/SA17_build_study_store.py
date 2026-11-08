"""Build the store of SA17's executable run, as ``research/SA17/study.toml`` declares it.

No network and no backtest. Run from the repository root, once 2d has passed
(``scripts/SA17_acquire_fx.py`` fetch, verify and build)::

    uv run python scripts/SA17_build_study_store.py

The store is new, under ``runs/sa17_study_*``, and the script refuses an
existing folder. It holds:

- the bars of ``runs/sa17_store``, copied byte for byte (sector funds,
  ``SP500TR``, XEON, QDVE, Xetra-Gold, SXRV and the ECB rate nobody reads);
- the ten USD NAV series, replayed from the immutable issuer archive through
  :class:`SsgaNavNormalizer` built with ``declared_release=True``. Each NAV is
  available at 23:00 Paris on the next London session after its date: the
  prospectus rule the owner chose for gate 2c, a declared assumption, not an
  observed publication time. The values must equal those of the
  retrieval-floored store ``runs/sa17_nav_store_20261107_v3``, row for row;
- EUR/USD at each NYSE close, quoting USD per EUR, from the derived table of
  the Dukascopy archive, refused unless its verification passed and its
  hash is the one its coverage records. It is a ``RESTATED`` level series
  available at 16:00 New York on its date;
- the venue calendars plus SA17's ``XNYS_XLON`` grid and ``XLON``.

``study_store.json`` records the store digest, every input hash and the checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tomllib
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_backtester.data.bar_corrections import BarCorrections
from quant_backtester.data.calendars import CalendarRegistry
from quant_backtester.data.conflict_reviews import ConflictReviews
from quant_backtester.data.corporate_actions import ActionCorrections
from quant_backtester.data.crosscheck import CrossCheckPolicy
from quant_backtester.data.instruments import Instrument, InstrumentRegistry
from quant_backtester.data.known_gaps import KnownGaps
from quant_backtester.data.normalizer import (
    NORMALIZERS,
    DukascopyUsCloseNormalizer,
    Normalizer,
    SsgaNavNormalizer,
)
from quant_backtester.data.reader import MarketDataReader
from quant_backtester.data.repository import MarketDataRepository
from quant_backtester.data.revisions import AcceptedRevisions
from quant_backtester.data.sources.base import DataSource, RawDownload, make_fetch_id
from quant_backtester.data.sources.ssga_nav import SsgaNavSource
from quant_backtester.data.updater import MarketDataUpdater

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research" / "SA17" / "study.toml"
NAV_END = date(2026, 10, 30)
"""Last NAV date ingested: the window's end, as for the retrieval-floored store."""


def fx_verification_days() -> list[str]:
    """Read the committed verification dates; never redraw them during admission."""
    return json.loads((ROOT / "research/SA17/fx_verification.json").read_text())["dates"]


def load_study(path: Path = STUDY) -> dict[str, Any]:
    """Return the frozen study configuration."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def nav_instrument_toml(fund_id: str, record: Mapping[str, Any], rule: Mapping[str, Any]) -> str:
    """Return one NAV instrument under the declared release rule."""
    return f'''
[[instrument]]
id = "{fund_id.replace("ETF_", "NAV_")}"
name = "Official USD NAV {record["isin"]}"
asset_type = "ETF"
data_type = "LEVEL"
currency = "USD"
primary_source = "SSGA_NAV"
source_symbol = "{record["isin"]}:{record["ticker"]}"
tradable = false
first_session = {record["first_observation"]}
distribution_policy = "ACCUMULATING"
history_basis = "RESTATED"
history_note = """
Current issuer NAV history, not a vintage. Availability is SA17's declared
prospectus rule (research/SA17/protocol.md, executable run), not an observed
publication time. Never execution prices.
"""
  [instrument.publication_rule]
  publication_time = "{rule["publication_time"]}"
  timezone = "{rule["timezone"]}"
  lag_sessions = {rule["lag_sessions"]}
  calendar_id = "{rule["calendar_id"]}"
'''


def fx_instrument_toml(fx: Mapping[str, Any], first: date) -> str:
    """Return the US-close EUR/USD instrument."""
    return f'''
[[instrument]]
id = "{fx["id"]}"
name = "EUR/USD at each NYSE close, mid of Dukascopy bid and ask, USD per EUR"
asset_type = "FX"
data_type = "LEVEL"
currency = "USD"
primary_source = "DUKASCOPY"
source_symbol = "EURUSD"
tradable = false
first_session = {first.isoformat()}
history_basis = "{fx["history_basis"]}"
history_note = """
Quote record retrieved in 2026, not a vintage: the provider may restate it.
Read at the NYSE close (13:00 New York on a half day), released at 16:00.
"""
  [instrument.publication_rule]
  publication_time = "{fx["publication_time"]}"
  timezone = "{fx["timezone"]}"
'''


def _observation_date(value: str | date) -> date:
    """Refuse a missing observation date before deriving archive bounds."""
    parsed = pd.Timestamp(value).date()
    if pd.isna(parsed) or not isinstance(parsed, date):
        raise ValueError("FX observation date is missing")
    return parsed


class ArchivedTable:
    """Serve the verified US-close table as the Dukascopy source's one download.

    The table was derived offline from hashed bar files by
    ``scripts/SA17_acquire_fx.py build``; this replays it into the updater so
    the rate goes through the same normalisation and validation as any level.
    """

    source_id = "DUKASCOPY"

    def __init__(
        self, table: pd.DataFrame, retrieved_at: datetime, request: Mapping[str, object]
    ) -> None:
        self._table = table
        self._retrieved_at = retrieved_at
        self._request = dict(request)

    def available_from(self, instrument: Instrument) -> date | None:
        """Return the first date of the table."""
        return min(_observation_date(day) for day in self._table["observation_date"])

    def download(self, instrument: Instrument, start: date, end: date) -> RawDownload:
        """Return the rows of the table inside ``[start, end]``."""
        days = [_observation_date(day) for day in self._table["observation_date"]]
        kept = self._table.loc[[start <= day <= end for day in days]].reset_index(drop=True)
        return RawDownload(
            instrument.id,
            self.source_id,
            make_fetch_id(self._retrieved_at),
            self._retrieved_at,
            kept,
            self._request | {"start": start.isoformat(), "end": end.isoformat()},
        )

    def download_corporate_actions(
        self, instrument: Instrument, start: date, end: date
    ) -> RawDownload | None:
        """Return ``None``: a rate has no corporate actions."""
        return None


def updater(
    store: Path,
    sources: Mapping[str, DataSource],
    normalizers: Mapping[str, Normalizer],
) -> MarketDataUpdater:
    """Return the framework's updater on the new store."""
    metadata = store / "metadata"
    return MarketDataUpdater(
        repository=MarketDataRepository(store),
        instruments=InstrumentRegistry.from_toml(metadata / "instruments.toml"),
        calendars=CalendarRegistry.from_directory(metadata / "calendars"),
        sources=dict(sources),
        normalizers=dict(normalizers),
        accepted_revisions=AcceptedRevisions.from_toml(metadata / "accepted_revisions.toml"),
        action_corrections=ActionCorrections.from_toml(metadata / "corporate_actions.toml"),
        bar_corrections=BarCorrections.from_toml(metadata / "bar_corrections.toml"),
        cross_check_policy=CrossCheckPolicy.from_toml(metadata / "crosscheck.toml"),
        known_gaps=KnownGaps.from_toml(metadata / "known_gaps.toml"),
        conflict_reviews=ConflictReviews.from_toml(metadata / "conflict_reviews.toml"),
    )


def checked_fx_table(archive: Path) -> tuple[pd.DataFrame, dict[str, Any], datetime]:
    """Return the derived table, refused unless 2d's verification passed.

    Returns
    -------
    tuple[pd.DataFrame, dict[str, Any], datetime]
        The table, its coverage record, and the last retrieval instant of the
        archive's files (the download's ``retrieved_at``).
    """
    derived = archive / "derived"
    coverage = json.loads((derived / "coverage.json").read_text(encoding="utf-8"))
    table_path = derived / "eurusd_us_close.parquet"
    if hashlib.sha256(table_path.read_bytes()).hexdigest() != coverage["table_sha256"]:
        raise ValueError("the US-close table does not hash to its coverage record")
    days = coverage["verification"]["days"]
    design = json.loads((ROOT / "research/SA17/fx_verification.json").read_text())
    if (
        coverage["verification"].get("seed") != design["seed"]
        or coverage["verification"]["sample"] != design["sample"]
        or sorted(day["date"] for day in days) != design["dates"]
        or coverage["verification"].get("tolerance") != design["tolerance"]
        or coverage.get("max_staleness_seconds") != design["max_staleness_seconds"]
    ):
        raise ValueError("gate 2d verification design mismatch: seed, dates, size or tolerances")
    for day in days:
        hourly, minute = day.get("hourly"), day.get("minute")
        staleness = day.get("minute_staleness_seconds")
        if (
            any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in (hourly, minute, staleness)
            )
            or hourly <= 0
            or minute <= 0
            or not 0 <= staleness <= design["max_staleness_seconds"]
            or abs(hourly - minute) > design["tolerance"]
            or day.get("agree") is not True
        ):
            raise ValueError(
                f"gate 2d has not passed: invalid verification values on {day['date']}"
            )
    if coverage["missing_months"] or coverage["without_rate"]:
        raise ValueError(
            f"the US-close table has holes: months {coverage['missing_months']}, "
            f"sessions {coverage['without_rate'][:5]}"
        )
    retrieved = max(
        datetime.fromisoformat(json.loads(line)["retrieved_at_utc"])
        for line in (archive / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return pd.read_parquet(table_path), coverage, retrieved


def build(store: Path, study: Mapping[str, Any]) -> dict[str, Any]:
    """Build the store and return its evidence record."""
    settings = study["store"]
    if store.resolve().parent != (ROOT / "runs").resolve() or not store.name.startswith(
        "sa17_study_"
    ):
        raise ValueError("use a new runs/sa17_study_* directory")
    if store.exists():
        raise FileExistsError(f"{store} exists; a store is never rewritten")
    fx_settings = study["fx"]
    table, fx_coverage, fx_retrieved = checked_fx_table(ROOT / settings["fx_archive"])

    shutil.copytree(
        ROOT / settings["bars_from"], store, ignore=shutil.ignore_patterns(".lock", ".pending")
    )
    metadata = store / "metadata"
    for calendar in settings["study_calendars"]:
        shutil.copy2(ROOT / calendar, metadata / "calendars" / Path(calendar).name)

    archive = ROOT / settings["nav_archive"]
    records = json.loads((archive / "coverage.json").read_text(encoding="utf-8"))
    funds = study["strategy"]["sector_ids"]
    by_ticker = {record["ticker"]: record for record in records}
    registry = tomllib.loads(
        (ROOT / "research" / "SA17" / "source_instruments.toml").read_text(encoding="utf-8")
    )["instrument"]
    symbols = {item["id"]: item["source_symbol"] for item in registry}
    pairs = []
    for fund in funds:
        ticker = symbols[fund].split(".")[0].lower() + "-gy"
        pairs.append((fund, by_ticker[ticker]))
    first_fx = min(_observation_date(day) for day in table["observation_date"])
    text = (metadata / "instruments.toml").read_text(encoding="utf-8")
    text += "\n# --- SA17 executable study: NAVs under the declared release, US-close FX ---\n"
    for fund, record in pairs:
        text += nav_instrument_toml(fund, record, study["nav_publication"])
    text += fx_instrument_toml(fx_settings, first_fx)
    (metadata / "instruments.toml").write_text(text, encoding="utf-8")

    nav_checks = []
    declared = dict(NORMALIZERS) | {"SSGA_NAV": SsgaNavNormalizer(declared_release=True)}
    reference = MarketDataRepository(ROOT / settings["nav_values_must_equal"])
    for fund, record in pairs:
        nav_id = fund.replace("ETF_", "NAV_")
        payload = (archive / "raw" / f"{record['ticker']}.xlsx").read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError(f"the archived workbook of {nav_id} changed")
        fetched = datetime.fromisoformat(record["retrieved_at_utc"])
        source = SsgaNavSource(clock=lambda t=fetched: t, fetch_bytes=lambda _url, p=payload: p)
        report = updater(store, {"SSGA_NAV": source}, declared).download(
            nav_id, date.fromisoformat(record["first_observation"]), NAV_END
        )
        if not report.valid:
            raise ValueError(f"{nav_id}: {sorted({issue.code for issue in report.issues})}")
        built = MarketDataRepository(store).load_levels(nav_id)
        floored = reference.load_levels(nav_id)
        same = built["observation_date"].tolist() == floored["observation_date"].tolist() and (
            built["value"].tolist() == floored["value"].tolist()
        )
        if not same:
            raise ValueError(f"{nav_id}: values differ from the retrieval-floored store")
        nav_checks.append(
            {
                "id": nav_id,
                "rows": len(built),
                "first": built["observation_date"].min(),
                "last": built["observation_date"].max(),
                "values_equal_v3": True,
                "workbook_sha256": record["sha256"],
            }
        )

    request = {
        "pair": "EURUSD",
        "quote": fx_settings["quote"],
        "table_sha256": fx_coverage["table_sha256"],
        "archive": settings["fx_archive"],
    }
    fx_source = ArchivedTable(table, fx_retrieved, request)
    replayed = dict(NORMALIZERS) | {"DUKASCOPY": DukascopyUsCloseNormalizer()}
    fx_report = updater(store, {"DUKASCOPY": fx_source}, replayed).download(
        fx_settings["id"], first_fx, max(_observation_date(d) for d in table["observation_date"])
    )
    if not fx_report.valid:
        raise ValueError(f"FX: {sorted({issue.code for issue in fx_report.issues})}")
    fx_rows = MarketDataRepository(store).load_levels(fx_settings["id"])

    hashes = {
        str(path.relative_to(store)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(metadata.rglob("*"))
        if path.is_file()
    }
    (store / "metadata_sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    calendars = CalendarRegistry.from_directory(metadata / "calendars")
    reader = MarketDataReader(
        repository=MarketDataRepository(store),
        instruments=InstrumentRegistry.from_toml(metadata / "instruments.toml"),
        calendars=calendars,
        reference_calendar_id="XPAR",
    )
    with reader.pinned() as state:
        digest = state.digest
    evidence = {
        "store": str(store.relative_to(ROOT)),
        "digest": digest,
        "study": str(STUDY.relative_to(ROOT)),
        "bars_from": settings["bars_from"],
        "navs": nav_checks,
        "nav_release": dict(study["nav_publication"]),
        "fx": {
            "id": fx_settings["id"],
            "rows": len(fx_rows),
            "first": fx_rows["observation_date"].min(),
            "last": fx_rows["observation_date"].max(),
            "table_sha256": fx_coverage["table_sha256"],
            "verification_sample": fx_coverage["verification"]["sample"],
            "retrieved_at_utc": fx_retrieved,
        },
        "calendars": sorted(path.stem for path in (metadata / "calendars").glob("*.toml")),
        "metadata_sha256": hashes,
    }
    (store / "study_store.json").write_text(
        json.dumps(evidence, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return evidence


def main(arguments: list[str] | None = None) -> int:
    """Build the store the study configuration names."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--store", type=Path, default=None)
    parsed = parser.parse_args(arguments)
    study = load_study()
    store = parsed.store or ROOT / study["store"]["path"]
    store = store if store.is_absolute() else ROOT / store
    evidence = build(store, study)
    print(
        f"{evidence['store']}: digest {evidence['digest']}; {len(evidence['navs'])} NAVs equal "
        f"to v3; {evidence['fx']['rows']} FX rates {evidence['fx']['first']} -> "
        f"{evidence['fx']['last']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
