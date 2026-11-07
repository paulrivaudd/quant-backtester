"""Reproducible notice audits with synthetic offline inputs and immutable outputs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_backtester.data.sources.base import ProviderResponseError
from quant_backtester.data.sources.lse_nav import NAV_HEADER

SPEC = importlib.util.spec_from_file_location(
    "check_nav_notice", Path(__file__).resolve().parents[2] / "scripts/SA17_check_nav_notice.py"
)
assert SPEC is not None and SPEC.loader is not None
SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)


@pytest.fixture
def audit_inputs(tmp_path, monkeypatch):
    registry = tmp_path / "registry.toml"
    entries = []
    for number, isin in enumerate(SCRIPT.SECTORS):
        identifier = "SA17_NAV_COMMUNICATION" if isin == "IE00BFWFPX50" else f"NAV_{number}"
        entries.append(f'''[[instrument]]
id = "{identifier}"
source_symbol = "{isin}:fund-{number}"
currency = "USD"
data_type = "LEVEL"
tradable = false
primary_source = "SSGA_NAV"
''')
    registry.write_text("\n".join(entries))
    identities = SCRIPT.registry_identities(registry)
    rows = [NAV_HEADER] + [
        (item.fund_name, "05/11/2026", item.isin, "1", "USD", "10", "USD", "10.0000")
        for item in identities
    ]
    html = (
        '<div data-article-type="RNS" '
        'data-article-published-time="2026-11-06T10:20:21Z"></div><table>'
    )
    html += (
        "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
        + "</table>"
    )
    replay = tmp_path / "original"
    replay.mkdir()
    payload = html.encode()
    (replay / "notice.html").write_bytes(payload)
    (replay / "acquisition.json").write_text(
        json.dumps(
            {
                "url": SCRIPT.NOTICE_URL,
                "retrieved_at_utc": "2026-11-07T00:00:00+00:00",
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    )
    primary = tmp_path / "primary"
    (primary / "raw").mkdir(parents=True)
    funds = []
    for number, identity in enumerate(identities):
        body = identity.isin.encode()
        (primary / "raw" / f"fund-{number}.xlsx").write_bytes(body)
        funds.append(
            {
                "isin": identity.isin,
                "ticker": f"fund-{number}",
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    (primary / "manifest.json").write_text(json.dumps({"funds": funds}))

    def workbook(payload, *, isin) -> SimpleNamespace:
        assert payload == isin.encode()
        return SimpleNamespace(
            sha256=hashlib.sha256(payload).hexdigest(),
            frame={"Date": ["05-Nov-2026"], "NAV": ["10"]},
        )

    monkeypatch.setattr(SCRIPT, "parse_nav_workbook", workbook)
    return registry, replay, primary


def test_replay_correct_mapping_and_no_overwrite(tmp_path, audit_inputs):
    registry, replay, primary = audit_inputs
    before = {p.name: p.read_bytes() for p in replay.iterdir()}
    output = tmp_path / "v2"
    result = SCRIPT.check_notice(output, primary, registry, replay=replay)
    assert result["validated_funds"] == 10
    assert all(item["status"] == "MATCH" for item in result["comparisons"])
    rows = json.loads((output / "canonical_rows.json").read_text())
    comms = next(row for row in rows if row["isin"] == "IE00BFWFPX50")
    assert comms["instrument_id"] == "SA17_NAV_COMMUNICATION"
    assert result["historical_publication_evidence"] is False
    assert {p.name: p.read_bytes() for p in replay.iterdir()} == before
    with pytest.raises(FileExistsError):
        SCRIPT.check_notice(output, primary, registry, replay=replay)
    repeat = tmp_path / "repeat"
    SCRIPT.check_notice(repeat, primary, registry, replay=replay)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {
        p.name: p.read_bytes() for p in repeat.iterdir()
    }


@pytest.mark.parametrize("target", ["notice", "workbook"])
def test_input_hash_tampering_refused(tmp_path, audit_inputs, target):
    registry, replay, primary = audit_inputs
    path = replay / "notice.html" if target == "notice" else primary / "manifest.json"
    if target == "notice":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        manifest = json.loads(path.read_text())
        manifest["funds"][0]["sha256"] = "wrong"
        path.write_text(json.dumps(manifest))
    with pytest.raises(ProviderResponseError, match="hash mismatch"):
        SCRIPT.check_notice(tmp_path / "v2", primary, registry, replay=replay)


@pytest.mark.parametrize("value,status", [("11", "CONFLICT"), (None, "SECONDARY_ONLY")])
def test_conflicts_refused_and_missing_dates_not_invented(
    tmp_path, audit_inputs, monkeypatch, value, status
):
    registry, replay, primary = audit_inputs

    def workbook(payload, *, isin) -> SimpleNamespace:
        return SimpleNamespace(
            sha256=hashlib.sha256(payload).hexdigest(),
            frame={
                "Date": ["05-Nov-2026"] if value else [],
                "NAV": [value] if value else [],
            },
        )

    monkeypatch.setattr(SCRIPT, "parse_nav_workbook", workbook)
    output = tmp_path / "v2"
    if status == "CONFLICT":
        with pytest.raises(ProviderResponseError, match="conflicts refused"):
            SCRIPT.check_notice(output, primary, registry, replay=replay)
    else:
        SCRIPT.check_notice(output, primary, registry, replay=replay)
    result = json.loads((output / "validation.json").read_text())
    assert len(result["comparisons"]) == 10
    assert {item["status"] for item in result["comparisons"]} == {status}
    assert {item["observation_date"] for item in result["comparisons"]} == {"2026-11-05"}
