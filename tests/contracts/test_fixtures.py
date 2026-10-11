"""Every shared fixture is accepted or rejected exactly as documented, in Python and in the
generated JSON Schema the TypeScript types come from."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from hachi.contracts.schema import DOCUMENTS, schema_for

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
MODELS = {model.__name__: model for model in DOCUMENTS}
EXPECTATIONS: dict[str, str] = json.loads((FIXTURES / "invalid" / "expectations.json").read_text())

VALID = sorted(p for p in FIXTURES.glob("*/*.json") if p.parent.name != "invalid")
INVALID = sorted((FIXTURES / "invalid").glob("*/*.json"))

# Errors the JSON Schema can express on its own; the rest are cross-field rules.
STRUCTURAL = (
    "Extra inputs are not permitted",
    "Expected status ok",
    "Field required",
    "Input should be",
    "valid integer",
    "should match pattern",
    "at least 1 item",
    "physiology_forecast without a resolution",
)

SYNTHETIC_MARKERS = {"subject_id", "dataset_id", "artifact_id", "request_id", "entry_id"}


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def _validator(document: str) -> Draft202012Validator:
    return Draft202012Validator(schema_for(MODELS[document]))


@pytest.mark.parametrize("path", VALID, ids=_id)
def test_valid_fixture_is_accepted_and_canonical(path: Path) -> None:
    model = MODELS[path.parent.name]
    text = path.read_text()
    parsed = model.model_validate_json(text)
    assert parsed.model_dump(mode="json") == json.loads(text), "fixture is not in canonical form"
    _validator(path.parent.name).validate(json.loads(text))


@pytest.mark.parametrize("path", VALID, ids=_id)
def test_valid_fixture_is_marked_synthetic(path: Path) -> None:
    found: list[tuple[str, object]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in SYNTHETIC_MARKERS or key == "data_mode":
                    found.append((key, value))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(json.loads(path.read_text()))
    assert found, "fixture carries no synthetic marker"
    for key, value in found:
        if key == "data_mode":
            assert value == "synthetic"
        elif value is not None:
            assert str(value).startswith("synthetic"), f"{key}={value!r} is not synthetic"


@pytest.mark.parametrize("path", INVALID, ids=_id)
def test_invalid_fixture_is_rejected_for_its_documented_reason(path: Path) -> None:
    expected = EXPECTATIONS[f"{path.parent.name}/{path.name}"]
    with pytest.raises(ValidationError) as error:
        MODELS[path.parent.name].model_validate_json(path.read_text())
    assert expected in str(error.value)
    if expected.startswith(STRUCTURAL):
        assert not _validator(path.parent.name).is_valid(json.loads(path.read_text()))


def test_expectations_match_invalid_files() -> None:
    files = {f"{p.parent.name}/{p.name}" for p in INVALID}
    assert files == set(EXPECTATIONS)


def test_every_document_has_a_valid_fixture() -> None:
    assert {p.parent.name for p in VALID} == set(MODELS)


def test_required_states_are_covered() -> None:
    results = [json.loads(p.read_text()) for p in VALID if p.parent.name == "ReportResult"]
    tasks = {"physiology_forecast", "anomaly", "illness_onset", "recovery", "alertness"}
    assert {r["task"] for r in results if r["status"] == "ok"} == tasks
    assert {r["status"] for r in results} == {"ok", "unavailable", "error"}
    assert any(r.get("reason_code") == "INSUFFICIENT_HISTORY" for r in results)

    requests = [json.loads(p.read_text()) for p in VALID if p.parent.name == "ReportRequest"]
    assert {r["task"] for r in requests} == tasks - {"alertness"}  # alertness uses scenarios

    imports = [json.loads(p.read_text()) for p in VALID if p.parent.name == "ImportStatus"]
    assert {i["state"] for i in imports} == {"pending", "running", "succeeded", "failed"}

    coverages = [json.loads(p.read_text()) for p in VALID if p.parent.name == "Coverage"]
    assert {c["history"] for c in coverages} == {"empty", "insufficient", "sufficient"}
