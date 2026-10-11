import io
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from hachi.data.pmdata import parse
from hachi.data.pmdata.clock import intraday_us, local_us, to_us
from hachi.data.pmdata.config import PipelineConfig, load_config


def stream(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode())


@pytest.mark.parametrize("chunk", [1, 2, 7, 64])
def test_array_elements_survive_any_chunk_boundary(monkeypatch, chunk):
    monkeypatch.setattr(parse, "CHUNK_CHARS", chunk)
    rows = [{"dateTime": f"2020-01-01 00:0{i}:00", "value": str(i)} for i in range(6)]
    text = " [ " + ",\n".join(json.dumps(r) for r in rows) + " ] \n"
    assert list(parse.iter_json_array(stream(text))) == rows
    assert list(parse.iter_json_array(stream("[]"))) == []


@pytest.mark.parametrize(
    "text",
    ['{"a": 1}', "[1, 2]", '[{"a": 1} {"b": 2}]', '[{"a": 1},]', '[{"a": 1}] trailing', '[{"a":'],
)
def test_malformed_arrays_are_refused(text):
    with pytest.raises(parse.ParseError):
        list(parse.iter_json_array(stream(text)))


def test_intraday_rows_are_strict():
    good = '[{"dateTime": "2020-01-01 00:01:00", "value": "12"}]'
    assert [r.value for r in parse.iter_intraday(stream(good))] == [12.0]
    for bad in (
        '[{"dateTime": "01/01/20 00:01:00", "value": "12"}]',
        '[{"dateTime": "2020-01-01 00:01:00", "value": 12}]',
        '[{"dateTime": "2020-01-01 00:01:00", "value": "12", "extra": 1}]',
    ):
        with pytest.raises(parse.ParseError):
            list(parse.iter_intraday(stream(bad)))


def rhr(stamp: str, inner: str, value: float, error: float = 1) -> str:
    body = {"date": None if inner == "null" else inner, "value": value, "error": error}
    return json.dumps([{"dateTime": stamp, "value": body}])


def test_resting_hr_sentinel_is_only_accepted_with_zero():
    sentinel = (
        '[{"dateTime": "2020-01-02 00:00:00", "value": {"date": null, "value": 0.0, "error": 0.0}}]'
    )
    assert next(parse.iter_resting_heart_rate(stream(sentinel))).value == 0
    for bad in (
        rhr("2020-01-02 00:00:00", "null", 55.0),
        rhr("2020-01-02 00:00:00", "01/03/20", 55.0),
        rhr("2020-01-02 07:00:00", "01/02/20", 55.0),
    ):
        with pytest.raises(parse.ParseError):
            list(parse.iter_resting_heart_rate(stream(bad)))


def test_wellness_needs_utc_timestamps():
    header = ",".join(parse.WELLNESS_COLUMNS) + "\n"
    good = header + '2020-01-02T07:00:00.123Z,3,3,5,7,3,3,"[1, 2]",3\n'
    report = next(parse.iter_wellness(stream(good)))
    assert report.reported_at == datetime(2020, 1, 2, 7, 0, 0, 123000, tzinfo=UTC)
    with pytest.raises(parse.ParseError):
        next(parse.iter_wellness(stream(header + "2020-01-02T07:00:00,3,3,5,7,3,3,[],3\n")))


def test_clock_mappings():
    oslo = ZoneInfo("Europe/Oslo")
    assert intraday_us("2020-03-29 02:30:00") == to_us(datetime(2020, 3, 29, 2, 30, tzinfo=UTC))
    assert local_us(datetime(2020, 1, 15, 23, 0), oslo) == to_us(
        datetime(2020, 1, 15, 22, 0, tzinfo=UTC)
    )
    assert local_us(datetime(2020, 6, 15, 23, 0), oslo) == to_us(
        datetime(2020, 6, 15, 21, 0, tzinfo=UTC)
    )
    assert local_us(datetime(2020, 3, 29, 2, 30), oslo) is None  # skipped by spring-forward
    assert local_us(datetime(2020, 10, 25, 2, 30), oslo) is None  # repeated by fall-back


def test_config_must_cover_every_metric_and_resolution():
    raw = load_config().config.model_dump()
    raw["min_coverage"].pop("steps")
    with pytest.raises(ValueError, match="min_coverage"):
        PipelineConfig.model_validate(raw)
    raw = load_config().config.model_dump()
    raw["min_coverage"]["resting_heart_rate_vendor"] = {"hour": 0.5, "day": 1.0}
    with pytest.raises(ValueError, match="resting_heart_rate_vendor"):
        PipelineConfig.model_validate(raw)
    raw = load_config().config.model_dump()
    raw["aggregations"]["heart_rate"] = ["sum"]
    with pytest.raises(ValueError, match="cannot be aggregated"):
        PipelineConfig.model_validate(raw)
    assert load_config().config.local_timezone == "Europe/Oslo"
