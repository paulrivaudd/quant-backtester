"""Archive the monthly research series of SA16's long-history study, without a backtest.

Run from the repository root, with ``--archive`` naming a NEW directory::

    uv run python scripts/SA16_acquire_long_history.py --archive runs/sa16_long_inputs_20261114

An existing archive is refused. Four files are fetched through the adapters
of ``data/`` and kept byte for byte:

- Ken French's 12 industry portfolios and research factors (monthly, USD);
- the World Bank's monthly commodity workbook, for gold's monthly average;
- FRED's daily Nasdaq Composite, ``NASDAQCOM``.

``coverage.json`` records each file's hash, retrieval instant and the months
it covers. No return, volatility or weight is computed or printed here: the
design in ``research/SA16/long_history.toml`` is frozen on coverage alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tomllib
import urllib.parse
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from quant_backtester.data.sources.base import http_get_text, utc_now
from quant_backtester.data.sources.fred import FRED_CSV_URL
from quant_backtester.data.sources.ken_french import KenFrenchDataset, KenFrenchSource
from quant_backtester.data.sources.world_bank import WorldBankPinkSheetSource

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "research" / "SA16" / "long_history.toml"
FRENCH_FIRST_MONTH = date(1926, 7, 1)
"""First month of the French monthly tables; the files are kept whole."""
NASDAQ_FILE = "NASDAQCOM.csv"
GOLD_FILE = "CMO-Historical-Data-Monthly.xlsx"


def load_study(path: Path = STUDY) -> dict[str, Any]:
    """Return the frozen study configuration."""
    with path.open("rb") as stream:
        return tomllib.load(stream)


def nasdaq_url(series: str, first: date, last: date) -> str:
    """Return the FRED CSV address of a daily series over an inclusive range."""
    query = urllib.parse.urlencode(
        {"id": series, "cosd": first.isoformat(), "coed": last.isoformat()}
    )
    return f"{FRED_CSV_URL}?{query}"


def acquire(
    archive: Path,
    study: dict[str, Any],
    french: KenFrenchSource | None = None,
    pink_sheet: WorldBankPinkSheetSource | None = None,
    fetch_text: Callable[[str], str] = http_get_text,
    today: Callable[[], date] | None = None,
) -> list[dict[str, Any]]:
    """Fetch the four files into a new archive and return its coverage record.

    Parameters
    ----------
    archive : Path
        A new directory; an existing one is refused before anything is fetched.
    study : dict[str, Any]
        The frozen configuration: which table, column and series to fetch.
    french, pink_sheet : optional
        The adapters; the live ones by default.
    fetch_text : Callable[[str], str]
        Fetches FRED's CSV; the shared HTTP helper by default.
    today : Callable[[], date] | None
        The last day asked of FRED; the UTC date of the retrieval by default.

    Returns
    -------
    list[dict[str, Any]]
        One record per file: its name, source, address, SHA-256, UTC retrieval
        instant and the first and last months (or days) it covers.
    """
    archive.mkdir(parents=True, exist_ok=False)
    try:
        return _acquire_into(archive, study, french, pink_sheet, fetch_text, today)
    except BaseException:
        # The folder did not exist before this call; half an archive would be
        # refused as existing by the next one.
        shutil.rmtree(archive, ignore_errors=True)
        raise


def _acquire_into(
    archive: Path,
    study: dict[str, Any],
    french: KenFrenchSource | None,
    pink_sheet: WorldBankPinkSheetSource | None,
    fetch_text: Callable[[str], str],
    today: Callable[[], date] | None,
) -> list[dict[str, Any]]:
    """Fill an archive that did not exist; :func:`acquire` removes it on failure."""
    french = french or KenFrenchSource()
    pink_sheet = pink_sheet or WorldBankPinkSheetSource()
    series = study["series"]
    records: list[dict[str, Any]] = []
    for dataset in (KenFrenchDataset[series["growth_dataset"]], KenFrenchDataset.FACTORS):
        probe = french.download(dataset, FRENCH_FIRST_MONTH, FRENCH_FIRST_MONTH)
        name = f"{dataset.value}.zip"
        (archive / name).write_bytes(probe.payload)
        records.append(
            {
                "file": name,
                "dataset": dataset.value,
                "source": probe.source,
                "url": probe.url,
                "sha256": probe.sha256,
                "retrieved_at_utc": probe.retrieved_at_utc.isoformat(),
                "first_month": probe.rows[0][0].strip(),
                "last_month": probe.rows[-1][0].strip(),
                "columns": list(probe.columns),
            }
        )
    gold = pink_sheet.download(series["gold_column"], series["gold_unit"])
    (archive / GOLD_FILE).write_bytes(gold.payload)
    records.append(
        {
            "file": GOLD_FILE,
            "dataset": "PINK_SHEET_MONTHLY",
            "source": gold.source,
            "url": gold.url,
            "sha256": gold.sha256,
            "retrieved_at_utc": gold.retrieved_at_utc.isoformat(),
            "first_month": f"{gold.months[0]:%Y%m}",
            "last_month": f"{gold.months[-1]:%Y%m}",
            "updated": gold.updated,
            "column": gold.name,
            "unit": gold.unit,
        }
    )
    retrieved = utc_now()
    last_day = today() if today is not None else retrieved.date()
    url = nasdaq_url(series["nasdaq_series"], series["nasdaq_first_day"], last_day)
    text = fetch_text(url)
    header = f"observation_date,{series['nasdaq_series']}"
    lines = text.splitlines()
    if not lines or lines[0] != header or len(lines) < 2:
        raise ValueError(f"FRED did not answer a {series['nasdaq_series']} series CSV")
    payload = text.encode("utf-8")
    (archive / NASDAQ_FILE).write_bytes(payload)
    records.append(
        {
            "file": NASDAQ_FILE,
            "dataset": series["nasdaq_series"],
            "source": "FRED",
            "url": url,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "retrieved_at_utc": retrieved.isoformat(),
            "first_day": lines[1].split(",")[0],
            "last_day": lines[-1].split(",")[0],
            "rows": len(lines) - 1,
        }
    )
    (archive / "coverage.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return records


def main(arguments: list[str] | None = None) -> int:
    """Archive the inputs the frozen configuration names."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--archive", type=Path, required=True)
    parsed = parser.parse_args(arguments)
    archive = parsed.archive if parsed.archive.is_absolute() else ROOT / parsed.archive
    for record in acquire(archive, load_study()):
        covered = (
            f"{record['first_month']} -> {record['last_month']}"
            if "first_month" in record
            else f"{record['first_day']} -> {record['last_day']}"
        )
        print(f"{record['file']}: {covered}; sha256 {record['sha256'][:12]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
