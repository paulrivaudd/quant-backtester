"""Check that every missing SA17 NAV date is a day the funds do not value.

Admission gate 2a of ``research/SA17/protocol.md``: fund non-valuation days
must be told apart from provider failures before a common observation grid is
defined. The umbrella prospectus of SSGA SPDR ETFs Europe II plc (19 February
2026, archived in ``runs/sa17_admission_20261107/raw``) defines a Business Day
as "a day on which markets in the United Kingdom are open and/or such other day
or days as the Directors may determine"; each sector supplement sets the
Valuation Point at 10.15 p.m. Irish time on each Business Day. A NAV missing on
an XNYS session that is a UK market holiday is therefore a non-valuation day; a
NAV missing on a UK business day would be an unexplained gap.

Run from the repository root (offline; ``exchange-calendars`` is a dev
dependency)::

    uv run python scripts/SA17_check_fund_calendar.py

It reads ``research/SA17/nav_calendar_coverage.json`` and writes
``research/SA17/fund_calendar_evidence.json``. It exits with status 1 when a
gap is unexplained.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import exchange_calendars as xcals

ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "research" / "SA17" / "nav_calendar_coverage.json"
EVIDENCE = ROOT / "research" / "SA17" / "fund_calendar_evidence.json"
PROSPECTUS = {
    "document": "SSGA SPDR ETFs Europe II plc prospectus, 19 February 2026",
    "url": "https://www.ssga.com/library-content/products/fund-docs/etfs/emea/2-GENERIC-EN-FP-IRISH-SPDR-II.pdf",
    "archive": "runs/sa17_admission_20261107/raw/umbrella-prospectus-spdr-ii.pdf",
    "sha256": "6665411ab82ce255ec7c9a3aaf9475f3db519401b4e05aaae649795dd905ea69",
    "retrieved_at_utc": "2026-11-07T21:33:20.047061+00:00",
    "quotes": {
        "business_day_pdf_page_70": (
            "a day on which markets in the United Kingdom are open and/or such other day or "
            "days as the Directors may determine and notify in advance to Shareholders"
        ),
        "dealing_day_pdf_page_71": (
            "unless specified otherwise in the Relevant Supplement for any Fund, every Business "
            "Day (excluding, for each Fund, any day on which a market on which securities "
            "included in the relevant Index are listed or traded is closed and/or the day "
            "preceding any such day provided that a list of such closed market days will be "
            "published for each Fund on the Website)"
        ),
        "publication_pdf_page_55": (
            "the Net Asset Value per Share shall be made public after the Valuation Point on "
            "the business day following the relevant Dealing Day"
        ),
    },
    "supplements": "Valuation Point 10.15 p.m. (Irish time) on each Business Day; no supplement "
    "redefines Business Day or Dealing Day (technology and consumer discretionary checked).",
    "caveat": "The 2026 edition of the prospectus; earlier editions were not acquired. The "
    "empirical check over 2015-2026 is what supports applying the rule to earlier years.",
}


def check(coverage: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify every missing and extra NAV date of every fund against XLON."""
    start, end = "2015-01-01", "2026-12-31"
    london = {day.date() for day in xcals.get_calendar("XLON", start=start, end=end).sessions}
    funds = []
    for fund in coverage:
        missing = [date.fromisoformat(day) for day in fund["missing_xnys_sessions"]]
        extra = [date.fromisoformat(day) for day in fund["extra_non_xnys_dates"]]
        unexplained = [day for day in missing if day in london]
        funds.append(
            {
                "id": fund["id"],
                "missing_xnys_sessions": len(missing),
                "missing_on_uk_holidays": len(missing) - len(unexplained),
                "unexplained_missing": [day.isoformat() for day in unexplained],
                "navs_on_non_xnys_days": len(extra),
                "navs_on_uk_holidays_when_xnys_closed": [
                    day.isoformat() for day in extra if day not in london
                ],
            }
        )
    return {
        "gate": "2a fund valuation calendar",
        "rule": PROSPECTUS,
        "calendars": {"XLON": f"exchange_calendars {xcals.__version__}", "range": [start, end]},
        "funds": funds,
        "unexplained_total": sum(len(fund["unexplained_missing"]) for fund in funds),
        "grid_candidate": {
            "definition": "XNYS sessions that are also XLON sessions",
            "why": "known in advance from two published calendars; every fund holds a NAV on "
            "every such date (no unexplained gap); drops NAVs the Directors chose to strike on "
            "some UK holidays, which a grid fixed in advance cannot anticipate",
            "status": "PROPOSED: adopted only by the executable-run amendment",
        },
    }


def main() -> int:
    """Write the evidence and fail on an unexplained gap."""
    evidence = check(json.loads(COVERAGE.read_text(encoding="utf-8")))
    EVIDENCE.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"unexplained gaps: {evidence['unexplained_total']}; written {EVIDENCE.name}")
    return 1 if evidence["unexplained_total"] else 0


if __name__ == "__main__":
    sys.exit(main())
