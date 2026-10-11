from pathlib import Path

from hachi.contracts import SCHEMA_VERSION
from hachi.contracts.schema import DEFAULT_PATH, DOCUMENTS, build_schema, render_schema


def test_committed_schema_is_current() -> None:
    assert Path(DEFAULT_PATH).read_text() == render_schema(), "run `make build`"


def test_schema_names_every_document_and_version() -> None:
    schema = build_schema()
    assert schema["x-hachi-schema-version"] == SCHEMA_VERSION
    assert {model.__name__ for model in DOCUMENTS} <= set(schema["$defs"])


def test_top_level_documents_carry_schema_version() -> None:
    rows = {"Observation", "Aggregate", "Outcome"}  # versioned by their table snapshot
    defs = build_schema()["$defs"]
    for model in DOCUMENTS:
        if model.__name__ in rows:
            continue
        variants = defs[model.__name__].get("oneOf", [{"$ref": f"#/$defs/{model.__name__}"}])
        for variant in variants:
            target = defs[variant["$ref"].split("/")[-1]]
            assert "schema_version" in target["required"], f"{target['title']} lacks a version"


def test_only_naive_local_times_use_local_date_time() -> None:
    """RFC 3339 `date-time` needs an offset; naive wall-clock fields carry their own format."""
    schema = build_schema()
    assert schema["$defs"]["LocalDateTime"]["format"] == "local-date-time"
    users = {
        f"{name}.{field}"
        for name, definition in schema["$defs"].items()
        for field, spec in definition.get("properties", {}).items()
        if spec.get("$ref") == "#/$defs/LocalDateTime"
    }
    assert users == {"SleepSchedule.bedtime_local", "SleepSchedule.wake_time_local"}
    assert '"format": "date-time"' in render_schema()  # UTC timestamps stay strict
