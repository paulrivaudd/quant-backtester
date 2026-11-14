"""Archive official SA17 NAV inputs and sourcing evidence, without a backtest.

Run with --archive pointing to a NEW directory. Existing archives are refused.
Only identity, coverage, quotes and hashes are reported; returns are not read.
Every download goes through the State Street and Ken French adapters of
``data/``: this script parses and archives what they return, and performs no
network I/O of its own.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import date
from pathlib import Path

from quant_backtester.data.sources.base import utc_now
from quant_backtester.data.sources.ken_french import KenFrenchDataset, KenFrenchSource
from quant_backtester.data.sources.ssga_nav import NAV_ROOT, SsgaNavSource, nav_date

ROOT = Path(__file__).resolve().parents[1]


def acquire(
    archive: Path, registry: Path, source: SsgaNavSource | None = None
) -> dict[str, object]:
    """Create an immutable raw audit with issuer links, hashes and coverage only.

    Parameters
    ----------
    archive : Path
        A new directory; an existing one is refused before anything is fetched.
    registry : Path
        The sourcing registry naming each fund's ISIN and issuer page.
    source : SsgaNavSource | None
        The adapter every document is fetched through; the live one by default.

    Returns
    -------
    dict[str, object]
        The manifest written to ``archive``: per fund, identity, coverage,
        hashes and the UTC retrieval instant.
    """
    archive.mkdir(parents=True, exist_ok=False)
    source = source or SsgaNavSource()
    raw = archive / "raw"
    raw.mkdir()
    sourcing = registry.read_text(encoding="utf-8")
    entries = re.findall(r"# ISIN (IE\w+);[^\n]*\n# (https://[^\n]+)", sourcing)
    if len(entries) != 10:
        raise ValueError("Expected ten explicitly sourced sector funds")
    records = []
    for isin, url in entries:
        ticker = url.rsplit("-", 2)[-2] + "-gy"
        page_bytes = source.fetch_document(url)
        (raw / f"{ticker}.html").write_bytes(page_bytes)
        page = page_bytes.decode("utf-8")
        nav_url = f"{NAV_ROOT}/navhist-emea-en-{ticker}.xlsx"
        if f"navhist-emea-en-{ticker}.xlsx" not in page:
            raise ValueError(f"Issuer page does not link expected NAV file: {isin}")
        book = source.fetch(isin, ticker)
        (raw / f"{ticker}.xlsx").write_bytes(book.payload)
        dates = sorted(nav_date(v) for v in book.frame["Date"])
        text = html.unescape(re.sub(r"<[^>]+>", " ", page))
        text = re.sub(r"\s+", " ", text)
        market = re.search(r"Fund Market Price(.*?)Fund Net Asset Value", text)
        quotes = market.group(1).strip() if market else "UNVERIFIED"
        supplements = sorted(set(re.findall(r'[^"\s<>]*fund-sup-[^"\s<>]+\.pdf', page)))
        supplements = [html.unescape(u) for u in supplements]
        for i, supplement in enumerate(supplements):
            pdf = source.fetch_document(supplement)
            (raw / f"{ticker}-supplement-{i}.pdf").write_bytes(pdf)
        record = {
            "isin": isin,
            "ticker": ticker,
            "page": url,
            "nav_url": nav_url,
            "currency": book.currency,
            "report_date": str(book.report_date),
            "first_observation": str(dates[0]),
            "last_observation": str(dates[-1]),
            "observations": len(dates),
            "sha256": book.sha256,
            "page_sha256": hashlib.sha256(page_bytes).hexdigest(),
            "retrieved_at_utc": utc_now().isoformat(),
            "quote_evidence": quotes,
            "supplements": supplements,
            "publication_time": "NOT_ESTABLISHED",
            "history_basis": "RESTATED",
            "tradable": False,
        }
        records.append(record)
        # Preserve completed downloads even if a subsequent provider fails.
        (archive / "coverage.json").write_text(json.dumps(records, indent=2) + "\n")
        print(f"{isin}: {len(dates)} USD NAV observations {dates[0]} .. {dates[-1]}", flush=True)
    result = {
        "status": "ACQUIRED_NOT_ADMITTED",
        "funds": records,
        "performance_runs": 0,
        "historical_publication": "UNKNOWN",
    }
    (archive / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    """Acquire into a new user-selected archive; never overwrite a store."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--coverage", action="store_true", required=True)
    parser.add_argument("--ken-french", action="store_true")
    args = parser.parse_args()
    if args.ken_french:
        acquire_ken_french(args.archive)
        return
    acquire(args.archive, ROOT / "research/SA17/source_instruments.toml")


def acquire_ken_french(archive: Path) -> None:
    """Archive monthly research inputs without calculating portfolio performance."""
    archive.mkdir(parents=True, exist_ok=False)
    source = KenFrenchSource()
    records = []
    # The three tables SA17's archive holds; a dataset added to the adapter later is not one.
    for dataset in (
        KenFrenchDataset.INDUSTRY_10,
        KenFrenchDataset.INDUSTRY_49,
        KenFrenchDataset.FACTORS,
    ):
        download = source.download(dataset, date(1926, 7, 1), date(2026, 9, 1))
        (archive / f"{dataset.value}.zip").write_bytes(download.payload)
        records.append(
            {
                "dataset": dataset.value,
                "url": download.url,
                "sha256": download.sha256,
                "retrieved_at_utc": download.retrieved_at_utc.isoformat(),
                "first_month": download.rows[0][0].strip(),
                "last_month": download.rows[-1][0].strip(),
                "rows": len(download.rows),
                "columns": download.columns,
                "currency": "USD",
                "history_basis": "RESTATED",
                "tradable": False,
            }
        )
        (archive / "coverage.json").write_text(json.dumps(records, indent=2) + "\n")
        print(f"{dataset.value}: {len(download.rows)} monthly rows", flush=True)


if __name__ == "__main__":
    main()
