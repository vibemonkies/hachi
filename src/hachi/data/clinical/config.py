"""Outcome definitions, per-dataset adapter settings and the admitted files they may read."""

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import Contract, Identifier, SchemaVersion, Sha256, VersionString

OUTCOMES_DIR = Path(__file__).resolve().parents[4] / "configs" / "outcomes"
DEFINITIONS_PATH = OUTCOMES_DIR / "definitions.toml"

type Days = Annotated[int, Field(ge=0, le=365)]
type Clock = Literal["floating_local_shifted"]


class OnsetDefinition(Contract):
    horizons_hours: Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1)]
    episode_merge_days: Days
    washout_after_resolution_days: Days
    washout_after_censored_onset_days: Days
    infection_without_onset_days_before: Days
    infection_without_onset_days_after: Days

    @model_validator(mode="after")
    def _check(self) -> Self:
        if any(h % 24 for h in self.horizons_hours):
            raise ValueError("horizons must be whole days on the local-midnight cutoff grid")
        if sorted(set(self.horizons_hours)) != self.horizons_hours:
            raise ValueError("horizons must be unique and ascending")
        return self


class TestDefinition(Contract):
    __test__ = False  # not a pytest test class

    link_days_before_onset: Days
    link_days_after_onset: Days
    exclude_days_after_positive: Days


class RecoveryDefinition(Contract):
    sustained_days: Annotated[int, Field(ge=1, le=14)]
    contradiction_days: Days


class Definitions(Contract):
    schema_version: SchemaVersion
    definitions_version: VersionString
    onset: OnsetDefinition
    test: TestDefinition
    recovery: RecoveryDefinition


class SurveySettings(Contract):
    symptomatic_feelings: list[str]
    symptom_columns: Annotated[list[str], Field(min_length=1)]


class StanfordSettings(Contract):
    schema_version: SchemaVersion
    pipeline_version: VersionString
    dataset_id: Identifier
    archive: Annotated[str, Field(pattern=r"^[^/\\]{1,255}$")]
    labels_workbook: Annotated[str, Field(pattern=r"^[^/\\]{1,255}$")]
    clock: Clock
    illness_categories: dict[str, Identifier]
    survey: SurveySettings | None = None


@dataclass(frozen=True)
class Loaded[T]:
    value: T
    sha256: str
    path: Path


def _load[T](path: Path, model: type[T]) -> Loaded[T]:
    raw = path.read_bytes()
    return Loaded(model.model_validate(tomllib.loads(raw.decode("utf-8"))), _sha(raw), path)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_definitions(path: Path = DEFINITIONS_PATH) -> Loaded[Definitions]:
    return _load(path, Definitions)


def load_stanford(dataset_id: str, directory: Path = OUTCOMES_DIR) -> Loaded[StanfordSettings]:
    loaded = _load(directory / f"{dataset_id}.toml", StanfordSettings)
    if loaded.value.dataset_id != dataset_id:
        raise ValueError(f"{loaded.path.name}: dataset_id must match the file name")
    return loaded


class AdmittedFile(Contract):
    name: Annotated[str, Field(pattern=r"^[^/\\]{1,255}$")]
    bytes: Annotated[int, Field(gt=0)]
    sha256: Sha256


class Admission(Contract):
    """A dataset's admitted files, as recorded by the dataset registry (#2)."""

    dataset_id: Identifier
    dataset_version: VersionString
    files: dict[str, AdmittedFile]


def registry_admission(dataset_id: str) -> Admission:
    from hachi.data.registry import load_registry

    source = load_registry()[dataset_id]
    if source.status not in {"downloaded", "validated"} or source.version is None:
        raise ValueError(f"{dataset_id} is not admitted with held, versioned files")
    return Admission(
        dataset_id=source.dataset_id,
        dataset_version=source.version,
        files={
            f.name: AdmittedFile(name=f.name, bytes=f.bytes, sha256=f.sha256) for f in source.files
        },
    )
