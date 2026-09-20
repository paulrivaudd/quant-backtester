"""ALFRED adapter: the series as it was known on a day, and the day is declared.

The routine tests inject the HTTP GET, so they are offline and never read the
wall clock. The ``network`` ones check the live endpoint on the case the whole
module exists for: US GDP for the first quarter of 2019 is not the same number
to a reader in January 2020 and to a reader in June 2021.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from quant_backtester.data.instruments import (
    AssetType,
    DataType,
    Instrument,
    PublicationRule,
    VintagePolicy,
)
from quant_backtester.data.sources.alfred import AlfredSource, vintage_column
from quant_backtester.data.sources.base import ProviderResponseError

RETRIEVED_AT = datetime(2026, 9, 20, 21, 3, 11, tzinfo=UTC)

GDP_2019_AS_OF_JANUARY_2020 = (
    "observation_date,GDP_20200131\n"
    "2019-01-01,21098.827\n"
    "2019-04-01,21340.267\n"
    "2019-07-01,21542.540\n"
    "2019-10-01,21734.266\n"
)
"""Verbatim ALFRED answer for GDP, 2019, as the archive held it on 31 January 2020."""


@dataclass
class FakeHttp:
    """Stand-in for the HTTP GET: records requested URLs, returns a fixed body."""

    body: str
    urls: list[str] = field(default_factory=list)

    def get(self, url: str) -> str:
        """Record ``url`` and return the fixed body."""
        self.urls.append(url)
        return self.body


@pytest.fixture
def http() -> FakeHttp:
    """Return a fake HTTP GET answering with the January 2020 vintage of GDP."""
    return FakeHttp(body=GDP_2019_AS_OF_JANUARY_2020)


@pytest.fixture
def gdp() -> Instrument:
    """Return US GDP, pinned to the vintage of 31 January 2020."""
    return Instrument(
        id="US_GDP",
        name="US gross domestic product",
        asset_type=AssetType.RATE,
        data_type=DataType.LEVEL,
        currency="NA",
        primary_source="ALFRED",
        source_symbol="GDP",
        tradable=False,
        publication_rule=PublicationRule(
            publication_time=time(8, 30),
            timezone="America/New_York",
            lag_sessions=1,
            calendar_id="XNYS",
        ),
        vintage_dates=(date(2020, 1, 31),),
        vintage_policy=VintagePolicy.PINNED,
    )


@pytest.fixture
def source(http: FakeHttp) -> AlfredSource:
    """Return an adapter with a fixed clock and the fake HTTP GET."""
    return AlfredSource(clock=lambda: RETRIEVED_AT, fetch_text=http.get)


def only_url(http: FakeHttp) -> str:
    """Return the single URL the adapter asked for."""
    assert len(http.urls) == 1
    return http.urls[0]


def test_the_vintage_is_sent_with_the_range(
    http: FakeHttp, gdp: Instrument, source: AlfredSource
) -> None:
    """Without it the archive answers with today's numbers, which is FRED again."""
    source.download(gdp, date(2019, 1, 1), date(2019, 12, 31))

    parts = urlsplit(only_url(http))
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https",
        "alfred.stlouisfed.org",
        "/graph/alfredgraph.csv",
    )
    assert parse_qs(parts.query) == {
        "id": ["GDP"],
        "cosd": ["2019-01-01"],
        "coed": ["2019-12-31"],
        "vintage_date": ["2020-01-31"],
    }


def test_the_raw_frame_is_kept_as_the_archive_sent_it(
    gdp: Instrument, source: AlfredSource
) -> None:
    """Including the column name, which is where ALFRED puts the vintage."""
    result = source.download(gdp, date(2019, 1, 1), date(2019, 12, 31))

    assert list(result.frame.columns) == ["observation_date", "GDP_20200131"]
    assert result.frame["GDP_20200131"].tolist()[0] == "21098.827"
    assert result.source == "ALFRED"


def test_the_request_records_which_vintage_it_holds(gdp: Instrument, source: AlfredSource) -> None:
    """A raw archive that does not say which vintage it is, is not an archive."""
    result = source.download(gdp, date(2019, 1, 1), date(2019, 12, 31))

    assert result.request["vintage_dates"] == ["2020-01-31"]
    assert result.request["value_columns"] == ["GDP_20200131"]
    assert result.request["endpoint"] == "alfredgraph.csv"


def test_a_series_with_no_vintage_declared_is_refused(
    gdp: Instrument, source: AlfredSource, http: FakeHttp
) -> None:
    """A vintage left unsaid is the restated series again, under another name."""
    unpinned = replace(gdp, vintage_dates=(), vintage_policy=None)

    with pytest.raises(ValueError, match="declares no vintage_dates"):
        source.download(unpinned, date(2019, 1, 1), date(2019, 12, 31))
    assert http.urls == []


def test_a_vintage_in_the_future_is_refused(
    gdp: Instrument, source: AlfredSource, http: FakeHttp
) -> None:
    """A restatement that has not happened yet cannot be read.

    It is the look-ahead rule applied to the archive itself: a config pinned to
    next year's vintage would quietly serve today's numbers, and the day it
    stops doing that nobody would notice the run had changed.
    """
    ahead = replace(gdp, vintage_dates=(date(2026, 9, 21),))

    with pytest.raises(ValueError, match="have not happened yet"):
        source.download(ahead, date(2019, 1, 1), date(2019, 12, 31))
    assert http.urls == []


def test_a_vintage_older_than_the_series_is_an_empty_frame(gdp: Instrument) -> None:
    """The archive answers with nothing at all, and nothing is an answer."""
    empty = AlfredSource(clock=lambda: RETRIEVED_AT, fetch_text=lambda url: "")

    result = empty.download(gdp, date(2019, 1, 1), date(2019, 12, 31))

    assert result.frame.empty
    assert list(result.frame.columns) == ["observation_date", "GDP_20200131"]


def test_an_answer_that_is_not_a_series_csv_is_refused(gdp: Instrument) -> None:
    """An HTML error page would otherwise fail inside pandas, far from here."""
    html = AlfredSource(clock=lambda: RETRIEVED_AT, fetch_text=lambda url: "<html>oops</html>")

    with pytest.raises(ValueError, match="not a series CSV"):
        html.download(gdp, date(2019, 1, 1), date(2019, 12, 31))


def test_an_inverted_range_is_refused(gdp: Instrument, source: AlfredSource) -> None:
    """A configuration mistake, caught before any I/O."""
    with pytest.raises(ValueError, match="is after"):
        source.download(gdp, date(2019, 12, 31), date(2019, 1, 1))


def test_the_column_name_is_the_series_and_the_vintage() -> None:
    """One export can hold several vintages, so the column carries the date."""
    assert vintage_column("GDP", date(2020, 1, 31)) == "GDP_20200131"


def test_corporate_actions_is_always_none_without_any_http(
    http: FakeHttp, gdp: Instrument, source: AlfredSource
) -> None:
    """A published series has no corporate actions, and asking costs nothing."""
    assert source.download_corporate_actions(gdp, date(2019, 1, 1), date(2019, 12, 31)) is None
    assert http.urls == []


@pytest.mark.network
def test_download_live_gdp_is_the_number_of_its_vintage(gdp: Instrument) -> None:
    """The case the module exists for, checked against the live archive.

    US GDP for the first quarter of 2019 was 21 098.827 to a reader in January
    2020 and 21 115.309 to a reader in June 2021. A backtest deciding in 2019
    on the second number is deciding on information that did not exist.
    """
    january = AlfredSource().download(gdp, date(2019, 1, 1), date(2019, 3, 31))
    later = AlfredSource().download(
        replace(gdp, vintage_dates=(date(2021, 6, 30),)), date(2019, 1, 1), date(2019, 3, 31)
    )

    assert january.frame["GDP_20200131"].tolist() == ["21098.827"]
    assert later.frame["GDP_20210630"].tolist() == ["21115.309"]


@pytest.mark.network
def test_download_live_unknown_series_raises_http_404(gdp: Instrument) -> None:
    """The same 404 as FRED, and the response is closed rather than leaked."""
    unknown = replace(gdp, id="UNKNOWN", source_symbol="NOT_A_SERIES_XYZ")

    with pytest.raises(ProviderResponseError) as raised:
        AlfredSource().download(unknown, date(2019, 1, 1), date(2019, 3, 31))

    assert isinstance(raised.value.__cause__, HTTPError)
    assert raised.value.__cause__.code == 404


def test_several_vintages_come_back_in_one_export(
    gdp: Instrument, source: AlfredSource, http: FakeHttp
) -> None:
    """One request, one column per vintage - and the parameters are positional.

    ALFRED reads ``id``, ``cosd`` and ``coed`` alongside ``vintage_date``, so
    each has to be repeated as many times as the series is asked for. One
    ``id`` with a list of vintages answers with the first of them and no
    complaint, which is how a run reads one vintage believing it read four.
    """
    http.body = "observation_date,GDP_20200131,GDP_20210630\n2019-01-01,21098.827,21115.309\n"
    point_in_time = replace(
        gdp,
        vintage_dates=(date(2020, 1, 31), date(2021, 6, 30)),
        vintage_policy=VintagePolicy.AS_OF_DECISION,
    )

    result = source.download(point_in_time, date(2019, 1, 1), date(2019, 3, 31))

    assert "id=GDP%2CGDP" in http.urls[0]
    assert "cosd=2019-01-01%2C2019-01-01" in http.urls[0]
    assert "vintage_date=2020-01-31%2C2021-06-30" in http.urls[0]
    assert result.request["value_columns"] == ["GDP_20200131", "GDP_20210630"]
    assert result.frame["GDP_20210630"].tolist() == ["21115.309"]


@pytest.mark.network
def test_download_live_serves_every_vintage_asked_for(gdp: Instrument) -> None:
    """The quirk above, checked against the endpoint rather than assumed.

    If ALFRED ever starts honouring a single ``id`` with several vintages, or
    stops accepting the repeated form, this is what says so - and reading one
    vintage while believing you read three is a silent look-ahead.
    """
    point_in_time = replace(
        gdp,
        vintage_dates=(date(2020, 1, 31), date(2021, 6, 30)),
        vintage_policy=VintagePolicy.AS_OF_DECISION,
    )

    result = AlfredSource().download(point_in_time, date(2019, 1, 1), date(2019, 3, 31))

    assert result.frame["GDP_20200131"].tolist() == ["21098.827"]
    assert result.frame["GDP_20210630"].tolist() == ["21115.309"]
