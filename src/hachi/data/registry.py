"""Dataset admission registry: what each source is, what its terms allow, and who holds it.

One TOML file per source in configs/datasets/. A catalog entry is not proof of access; only
`downloaded` and `validated` sources name the archives someone actually holds, by checksum.

    python -m hachi.data.registry                         # summary table
    python -m hachi.data.registry verify [ROOT]           # prove every held archive is present
    python -m hachi.data.registry verify ROOT --dataset ID  # ... for named sources only
    python -m hachi.data.registry verify ROOT --partial   # catalog audit; tolerates missing
    python -m hachi.data.registry sums DATASET_ID         # SHA256SUMS lines, for `sha256sum -c`

ROOT defaults to $HACHI_DATA_ROOT. Archives live at ROOT/<dataset_id>/<file name>, or at
ROOT/<dataset_id>/<version>/<file name> as on the GX10 (~/hachi/data). `verify` exits 0 only
when every selected archive is present and matches; `--partial` exits 0 unless one is altered
and says that it proves nothing about acquisition.
"""

import argparse
import hashlib
import os
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from hachi.contracts.base import (
    Contract,
    Identifier,
    SchemaVersion,
    Sha256,
    TaskName,
    Text,
    VersionString,
    require_unique,
)

REGISTRY_DIR = Path(__file__).resolve().parents[3] / "configs" / "datasets"

type SourceStatus = Literal[
    "candidate", "access_pending", "downloaded", "validated", "rejected_for_task"
]
type AccessType = Literal[
    "public",
    "registration",
    "credentialed",
    "institutional_application",
    "not_released",
    "private_consented",
]
type HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://\S+$")]
type GitHubHandle = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")]
type FileName = Annotated[str, StringConstraints(pattern=r"^[^/\\]{1,255}$")]


class Evidence(Contract):
    """A primary-source statement backing a recorded term."""

    url: HttpsUrl
    quote: Text
    checked_on: date


class Terms(Contract):
    license: Text = Field(description="License or agreement name and version.")
    license_url: HttpsUrl | None = None
    commercial_use: Literal["allowed", "prohibited", "unclear"]
    redistribution: Literal[
        "allowed_with_attribution", "only_to_users_who_accepted", "prohibited", "unclear"
    ]
    team_access: Literal[
        "shareable_within_team",
        "each_user_must_accept",
        "each_user_must_be_credentialed",
        "unclear",
    ] = Field(description="Whether one person's access covers teammates.")
    shared_gx10_account: Literal["allowed", "only_if_all_users_authorized", "prohibited"] = Field(
        description="Whether a copy may sit on the GX10 Unix account all three teammates share."
    )
    analysis_registration_required: bool
    evidence: Annotated[list[Evidence], Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> Self:
        individual = self.team_access in {"each_user_must_accept", "each_user_must_be_credentialed"}
        if individual and self.shared_gx10_account == "allowed":
            raise ValueError(
                "data that each user must accept individually cannot be marked allowed on the "
                "shared GX10 account"
            )
        if (
            self.team_access == "each_user_must_be_credentialed"
            and self.shared_gx10_account != "prohibited"
        ):
            raise ValueError(
                "credentialed data must be prohibited on the shared GX10 account: a shared "
                "login shares access"
            )
        return self


class ArchiveFile(Contract):
    name: FileName
    bytes: Annotated[int, Field(gt=0)]
    sha256: Sha256


class TaskUse(Contract):
    task: TaskName
    role: Literal[
        "features", "outcome_labels", "evaluation", "baseline_reproduction", "exploratory"
    ]
    notes: Text


class DatasetSource(Contract):
    schema_version: SchemaVersion
    dataset_id: Identifier
    name: Text
    version: VersionString | None = Field(
        default=None, description="Release identifier; absent if unversioned."
    )
    status: SourceStatus
    access: AccessType
    primary_url: HttpsUrl
    doi: Annotated[str, StringConstraints(pattern=r"^10\.\d{4,9}/\S+$")] | None = None
    catalog_checked_on: date
    terms: Terms
    citation: Text
    acknowledgement: Text | None = None
    access_steps: Annotated[list[Text], Field(min_length=1)] = Field(
        description="Ordered human steps; agents never accept agreements on someone's behalf."
    )
    access_owner: GitHubHandle | None = Field(
        default=None, description="Teammate responsible for access."
    )
    approved_users: list[GitHubHandle] = Field(
        default_factory=list,
        description="Teammates who have themselves accepted the terms or been credentialed.",
    )
    storage: Text = Field(description="Where copies may live; never in Git.")
    checksum_strategy: Text
    files: list[ArchiveFile] = Field(default_factory=list)
    tasks: list[TaskUse] = Field(default_factory=list)
    blocked_capabilities: list[Text] = Field(default_factory=list)
    notes: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Self:
        require_unique([f.name for f in self.files], "files")
        require_unique(self.approved_users, "approved_users")
        held = self.status in {"downloaded", "validated"}
        if held:
            if not self.files:
                raise ValueError(f"a {self.status} source must list its archives by checksum")
            if self.access_owner is None or self.access_owner not in self.approved_users:
                raise ValueError("a held source needs an access owner who accepted the terms")
        elif self.files:
            raise ValueError("only downloaded or validated sources list held archives")
        if self.status == "rejected_for_task" and not self.notes:
            raise ValueError("a rejected source must say why in notes")
        if self.status == "access_pending" and self.access_owner is None:
            raise ValueError("pending access needs an owner pursuing it")
        return self


def load_registry(directory: Path = REGISTRY_DIR) -> dict[str, DatasetSource]:
    sources: dict[str, DatasetSource] = {}
    for path in sorted(directory.glob("*.toml")):
        with path.open("rb") as handle:
            source = DatasetSource.model_validate(tomllib.load(handle))
        if source.dataset_id != path.stem:
            raise ValueError(f"{path.name}: dataset_id must match the file name")
        sources[source.dataset_id] = source
    return sources


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(root: Path, sources: dict[str, DatasetSource]) -> list[tuple[str, str, str]]:
    """Check registered archives under root, root/<id>/ or root/<id>/<version>/.

    Returns (dataset id, file name, state) per registered archive.
    """
    results = []
    for source in sources.values():
        for archive in source.files:
            base = root / source.dataset_id
            candidates = [root / archive.name, base / archive.name]
            if source.version:
                candidates.append(base / source.version / archive.name)
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                state = "missing"
            elif path.stat().st_size != archive.bytes or _sha256(path) != archive.sha256:
                state = "MISMATCH"
            else:
                state = "ok"
            results.append((source.dataset_id, archive.name, state))
    return results


def verdict(results: list[tuple[str, str, str]], *, partial: bool) -> tuple[int, str]:
    """Exit code and summary. Acquisition needs every selected archive present and matching."""
    states = [state for *_, state in results]
    ok, missing, altered = states.count("ok"), states.count("missing"), states.count("MISMATCH")
    tally = f"{ok} ok, {missing} missing, {altered} mismatched"
    if partial:
        return (1 if altered else 0), f"partial audit: {tally}; not proof of acquisition"
    if not results or missing or altered:
        return 1, f"FAILED: {tally}"
    return 0, f"verified: all {ok} registered archives present and matching"


def sha256sums(source: DatasetSource) -> str:
    """Registered archives in `sha256sum -c` format, for machines without this package."""
    return "".join(f"{archive.sha256}  {archive.name}\n" for archive in source.files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("verify", help="prove registered archives are held and unaltered")
    check.add_argument("root", type=Path, nargs="?", help="defaults to $HACHI_DATA_ROOT")
    check.add_argument(
        "--dataset", action="append", default=[], metavar="ID", help="only these held sources"
    )
    check.add_argument(
        "--partial", action="store_true", help="catalog audit: report missing without failing"
    )
    sums = sub.add_parser("sums", help="print SHA256SUMS lines for one dataset")
    sums.add_argument("dataset_id")
    args = parser.parse_args(argv)
    sources = load_registry()
    if args.command == "sums":
        if args.dataset_id not in sources:
            parser.error(f"unknown dataset {args.dataset_id}")
        print(sha256sums(sources[args.dataset_id]), end="")
        return 0
    if args.command == "verify":
        root = args.root or (
            Path(os.environ["HACHI_DATA_ROOT"]) if "HACHI_DATA_ROOT" in os.environ else None
        )
        if root is None:
            parser.error("give ROOT or set HACHI_DATA_ROOT")
        if unknown := [d for d in args.dataset if d not in sources]:
            parser.error(f"unknown dataset {', '.join(unknown)}")
        if unheld := [d for d in args.dataset if not sources[d].files]:
            parser.error(f"not held, nothing to verify: {', '.join(unheld)}")
        selected = {d: sources[d] for d in args.dataset} if args.dataset else sources
        results = verify(root.expanduser(), selected)
        for dataset_id, name, state in results:
            print(f"{state:9} {dataset_id:34} {name}")
        code, summary = verdict(results, partial=args.partial)
        print(summary)
        return code
    for s in sources.values():
        owner = s.access_owner or "-"
        print(f"{s.dataset_id:34} {s.status:18} {s.access:26} {owner}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
