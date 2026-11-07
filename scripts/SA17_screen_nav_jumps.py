"""Screen SA17's NAV histories for jumps the market does not explain.

Admission gate 2b of ``research/SA17/protocol.md``: an unrecorded split,
consolidation or restatement would show as a daily NAV change far from the
market's. This flags every change above 15% in absolute value, or more than 8
points away from the S&P 500 total return over the same dates, for review.
It is a data check, not a strategy computation: no score, weight or portfolio
return is formed.

Run from the repository root (offline)::

    uv run python scripts/SA17_screen_nav_jumps.py

Reads ``runs/sa17_nav_store_20261107_v3`` and ``runs/sa17_store``, writes
``research/SA17/nav_jump_screen.json``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NAV_STORE = ROOT / "runs" / "sa17_nav_store_20261107_v3" / "clean" / "levels"
MARKET = ROOT / "runs" / "sa17_store" / "clean" / "bars" / "SP500TR.parquet"
OUTPUT = ROOT / "research" / "SA17" / "nav_jump_screen.json"
ABSOLUTE = 0.15
RELATIVE = 0.08

EXPLANATIONS = {
    ("SA17_NAV_ENERGY", "2020-03-09"): "oil price war: crude fell about 25% that day",
    ("SA17_NAV_ENERGY", "2020-03-18"): "Covid crash; crude fell about 24% that day",
    ("SA17_NAV_ENERGY", "2020-03-24"): "Covid rebound, the market's best day since 1933",
    ("SA17_NAV_ENERGY", "2020-11-09"): "first vaccine efficacy announcement; cyclical rotation",
}


def screen() -> dict[str, object]:
    """Flag every NAV change the thresholds catch, with its market change."""
    market = pd.read_parquet(MARKET).set_index("session_date")["close"]
    market.index = pd.to_datetime(market.index)
    funds: list[dict[str, object]] = []
    flags: list[dict[str, object]] = []
    for path in sorted(NAV_STORE.glob("*.parquet")):
        levels = pd.read_parquet(path)
        name = str(levels["instrument_id"].iloc[0])
        series = levels.set_index(pd.to_datetime(levels["observation_date"]))["value"].sort_index()
        # The market's close on or before each NAV date: a NAV struck on a US
        # holiday is compared with the last US close.
        aligned = market.reindex(series.index, method="ffill")
        changes = series.pct_change().dropna()
        dates = [day.date().isoformat() for day in pd.DatetimeIndex(changes.index)]
        nav_changes = [float(value) for value in changes.to_numpy()]
        market_changes = [
            float(value) for value in aligned.pct_change().reindex(changes.index).to_numpy()
        ]
        distances = [abs(a - b) for a, b in zip(nav_changes, market_changes, strict=True)]
        funds.append(
            {
                "id": name,
                "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "changes": len(nav_changes),
                "max_abs_change": max(abs(value) for value in nav_changes),
                "max_distance_from_market": max(distances),
            }
        )
        for day, change, move, distance in zip(
            dates, nav_changes, market_changes, distances, strict=True
        ):
            if abs(change) > ABSOLUTE or distance > RELATIVE:
                flags.append(
                    {
                        "id": name,
                        "date": day,
                        "nav_change": change,
                        "market_change": move,
                        "explanation": EXPLANATIONS.get((name, day), "UNEXPLAINED"),
                    }
                )
    unexplained = sum(1 for flag in flags if flag["explanation"] == "UNEXPLAINED")
    return {
        "gate": "2b fund actions",
        "thresholds": {"absolute": ABSOLUTE, "distance_from_market": RELATIVE},
        "market": "SP500TR close on or before each NAV date",
        "funds": funds,
        "flags": flags,
        "flag_count": len(flags),
        "unexplained": unexplained,
    }


def main() -> int:
    """Write the screen and fail on an unexplained flag."""
    result = screen()
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['flag_count']} flags, {result['unexplained']} unexplained")
    return 1 if result["unexplained"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
