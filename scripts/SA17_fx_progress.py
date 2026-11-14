"""Read acquisition progress against expected filenames, without fetching or writing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def expected_files(kind: str) -> tuple[str, ...]:
    """Return expected relative archive paths from the committed FX design."""
    design = json.loads((ROOT / "research/SA17/fx_verification.json").read_text())
    if kind == "hours":
        first, last = [int(day[:4]) * 12 + int(day[5:7]) - 1 for day in design["range"]]
        names = [f"{month // 12:04d}-{month % 12 + 1:02d}" for month in range(first, last + 1)]
    elif kind == "minutes":
        names = design["dates"]
    else:
        raise ValueError(f"unknown acquisition kind: {kind}")
    return tuple(f"raw/{kind}/{side}/{name}.bi5" for name in names for side in ("BID", "ASK"))


def progress(archive: Path, kind: str) -> tuple[int, int]:
    """Count expected complete files only; a manifest need not exist yet."""
    expected = expected_files(kind)
    return sum((archive / name).is_file() for name in expected), len(expected)


def main() -> None:
    """Print the completed and expected counts for the watchdog."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("kind", choices=("hours", "minutes"))
    args = parser.parse_args()
    print(*progress(args.archive, args.kind))


if __name__ == "__main__":
    main()
