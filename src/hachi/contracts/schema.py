"""Export the authoritative JSON Schema that TypeScript types are generated from.

python -m hachi.contracts.schema           # write contracts/schema/hachi.schema.json
python -m hachi.contracts.schema --check   # fail if the committed schema is stale
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, models_json_schema

from .api import ApiError, Coverage, HealthStatus, ImportStatus, ReportJob, SelfReportHistory
from .base import SCHEMA_VERSION
from .manifests import RunManifest, SplitManifest
from .requests import ReportRequest, ScenarioRequest, SelfReportRequest
from .results import ReportResult
from .tables import Aggregate, Observation, Outcome

DOCUMENTS: tuple[type[BaseModel], ...] = (
    Observation,
    Aggregate,
    Outcome,
    SplitManifest,
    RunManifest,
    ReportRequest,
    ScenarioRequest,
    SelfReportRequest,
    SelfReportHistory,
    ReportJob,
    ReportResult,
    ImportStatus,
    Coverage,
    ApiError,
    HealthStatus,
)

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "schema" / "hachi.schema.json"


class _UntitledFields(GenerateJsonSchema):
    """Omit per-field titles, which otherwise become spurious named types in TypeScript."""

    def field_title_should_be_set(self, schema) -> bool:
        return False


def build_schema() -> dict:
    _, schema = models_json_schema(
        [(model, "validation") for model in DOCUMENTS],
        schema_generator=_UntitledFields,
        title="HachiContracts",
        description=f"Hachi contracts v{SCHEMA_VERSION}. Generated from src/hachi/contracts.",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "x-hachi-schema-version": SCHEMA_VERSION,
        **schema,
    }


def render_schema() -> str:
    return json.dumps(build_schema(), indent=2, ensure_ascii=False) + "\n"


def schema_for(model: type[BaseModel]) -> dict:
    """A standalone schema validating one top-level document against the shared definitions."""
    schema = build_schema()
    return {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{model.__name__}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the schema file is stale")
    parser.add_argument("--out", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    rendered = render_schema()
    if args.check:
        if not args.out.exists() or args.out.read_text() != rendered:
            print(f"{args.out} is stale; run `make build`", file=sys.stderr)
            return 1
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
