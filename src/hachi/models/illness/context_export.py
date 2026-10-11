"""Export private bounded clinical physiology requests; no pretrained inference or scoring."""

import argparse
import csv
import hashlib
import json
import os
import subprocess
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from hachi.contracts.base import Contract, Sha256
from hachi.data.clinical.snapshot import dataset_snapshot_ref, read_table
from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos.inference import check_request, read_requests, request_id

from .hourly import (
    ContextProtocol,
    causal_hours,
    load_context_protocol,
    read_native_context,
    verify_archive,
)
from .run import write_private

REPO = Path(__file__).resolve().parents[4]


class ContextSummary(Contract):
    """A private summary must not become an arbitrary public health-data payload."""

    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    protocol_sha256: Sha256
    shared_protocol_sha256: Sha256
    fold_plan_sha256: Sha256
    archive_sha256: Sha256
    clock: Literal["floating_local_shifted"]
    counts: dict[str, Annotated[int, Field(ge=0)]]
    unique_requests: Annotated[int, Field(ge=0)]
    unique_encoder_requests: Annotated[int, Field(ge=0)]
    request_file_sha256: Sha256
    encoder_request_file_sha256: Sha256
    development_subjects_with_eligible_cutoffs: Annotated[int, Field(ge=0)]
    request_rows_have_identities_or_labels: Literal[False]
    outer_test_status: Literal["sealed"]
    inference_status: Literal["not_run"]
    comparison_status: Literal["pending"]


def verify_packet(snapshot: Path, output: Path) -> dict:
    """Validate real request files and role joins; return only reproducible aggregate evidence."""
    protocol = ContextProtocol.model_validate_json((output / "protocol.json").read_bytes())
    clinical = ClinicalProtocol.model_validate_json(
        (output / "clinical-protocol.json").read_bytes()
    )
    if (
        clinical.active_outer_fold != protocol.active_outer_fold
        or clinical.nested_plan_sha256 != protocol.nested_plan_sha256
    ):
        raise ValueError("context packet changed sealed participant plan")
    plan = clinical_fold_plan(snapshot, clinical)
    if dataset_snapshot_ref(snapshot).snapshot_sha256 != protocol.snapshot_sha256:
        raise ValueError("context verification snapshot differs from frozen policy")
    if document_sha256(plan) != document_sha256(
        json.loads((output / "fold-plan.json").read_bytes())
    ):
        raise ValueError("saved context plan differs from verified roster")
    summary = ContextSummary.model_validate_json((output / "summary.json").read_bytes()).model_dump(
        mode="json"
    )
    if summary["protocol_sha256"] != document_sha256(protocol):
        raise ValueError("context policy hash differs")
    if summary["shared_protocol_sha256"] != document_sha256(clinical) or summary[
        "fold_plan_sha256"
    ] != document_sha256(plan):
        raise ValueError("context summary differs from frozen participant protocol")
    chronos_path = output / "requests.jsonl"
    chronos = read_requests(chronos_path) if chronos_path.stat().st_size else []
    encoder_rows = [
        json.loads(line) for line in (output / "encoder-requests.jsonl").read_text().splitlines()
    ]
    encoder_ids, contexts = set(), {}
    for row in encoder_rows:
        rid = row.pop("request_sha256")
        if rid != document_sha256(row) or rid in encoder_ids:
            raise ValueError("invalid/duplicate encoder request hash")
        if (
            set(row) != {"context_policy_sha256", "hours", "first_hour_local", "channels", "units"}
            or row["context_policy_sha256"] != document_sha256(protocol)
            or row["hours"] != protocol.context_hours
            or row["first_hour_local"] != (-protocol.context_hours) % 24
            or set(row["channels"]) != {"heart_rate"}
            or row["units"] != {"heart_rate": "bpm"}
        ):
            raise ValueError("encoder metadata differs from frozen HR-only policy")
        context = row["channels"]["heart_rate"]
        # Share the actual #12 finite-float/null transport boundary.
        check_request(
            {
                "request_id": request_id(context, protocol.prediction_hours),
                "context": context,
                "prediction_length": protocol.prediction_hours,
            }
        )
        if (
            len(context) != protocol.context_hours
            or sum(v is not None for v in context) < protocol.min_observed_hr_hours
        ):
            raise ValueError("encoder context violates coverage policy")
        encoder_ids.add(rid)
        contexts[request_id(context, protocol.prediction_hours)] = rid
    if {r.request_id for r in chronos} != set(contexts) or len(encoder_rows) != len(contexts):
        raise ValueError("encoder and Chronos requests differ")
    active = {f.inner_fold: f for f in plan.folds if f.outer_fold == protocol.active_outer_fold}
    development = sorted({s for f in active.values() for s in f.validation_subjects})
    eligible = {
        (r["subject_id"], r["cutoff_utc"].isoformat())
        for r in read_table(snapshot, "onset_windows", development).to_pylist()
        if any(r[f"onset_{h}h"] in {"positive", "negative"} for h in (24, 48, 72))
    }
    joins = json.loads((output / "joins.json").read_bytes())
    keys, joined_contexts = set(), {}
    observed_by_request = {r.request_id: sum(v is not None for v in r.context) for r in chronos}
    for join in joins:
        fold = active[join["inner_fold"]]
        subject, cutoff = join["subject_id"], join["cutoff_floating"]
        key = (join["inner_fold"], subject, cutoff)
        expected_role = (
            "validation"
            if subject in fold.validation_subjects
            else "train"
            if subject in fold.train_subjects
            else None
        )
        if (
            key in keys
            or expected_role != join["role"]
            or expected_role is None
            or join["outer_fold"] != protocol.active_outer_fold
            or join["as_of_floating"] != cutoff
            or join["clock"] != protocol.clock
        ):
            raise ValueError("private context join differs from sealed role/availability")
        keys.add(key)
        rid = join["request_id"]
        if (rid is None and join["encoder_request_sha256"] is not None) or (
            rid is not None
            and (rid not in contexts or contexts[rid] != join["encoder_request_sha256"])
        ):
            raise ValueError("private join differs from request content")
        observed = join["observed_hr_hours"]
        if (
            type(observed) is not int
            or not 0 <= observed <= protocol.context_hours
            or (rid is None and observed >= protocol.min_observed_hr_hours)
            or (rid is not None and observed != observed_by_request[rid])
        ):
            raise ValueError("join coverage differs from actual request")
        signature = (rid, join["encoder_request_sha256"], observed)
        if joined_contexts.setdefault((subject, cutoff), signature) != signature:
            raise ValueError("context differs across participant folds")
    expected_keys = {(i, subject, cutoff) for i in active for subject, cutoff in eligible}
    if keys != expected_keys or len(eligible) != summary["counts"]["eligible_cutoffs"]:
        raise ValueError("private context joins are incomplete")
    if {j["request_id"] for j in joins if j["request_id"] is not None} != set(contexts):
        raise ValueError("transport contains physiology without an eligible private join")
    requested = sum(j["role"] == "validation" and j["request_id"] is not None for j in joins)
    if (
        requested != summary["counts"].get("requested_cutoffs", 0)
        or len(eligible) - requested != summary["counts"].get("insufficient_hourly_context", 0)
        or len({s for s, _ in eligible}) != summary["development_subjects_with_eligible_cutoffs"]
    ):
        raise ValueError("summary context coverage differs from verified joins")
    if output.stat().st_mode & 0o777 != 0o700 or any(
        p.stat().st_mode & 0o777 != 0o600 for p in output.iterdir()
    ):
        raise ValueError("context packet permissions differ from private policy")
    for name, field in [
        ("requests.jsonl", "request_file_sha256"),
        ("encoder-requests.jsonl", "encoder_request_file_sha256"),
    ]:
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != summary[field]:
            raise ValueError("context transport file hash differs")
    if (
        len(chronos) != summary["unique_requests"]
        or len(encoder_rows) != summary["unique_encoder_requests"]
    ):
        raise ValueError("summary request counts differ from actual transport")
    # Select explicit exporter fields; arbitrary additions to a private summary never publish.
    public = summary
    allowed_counts = {"eligible_cutoffs", "requested_cutoffs", "insufficient_hourly_context"} | {
        f"{metric}:{counter}"
        for metric in ("heart_rate", "steps")
        for counter in (
            "source_rows",
            "quarantined_subject",
            "quarantined_value_time",
            "outside_requested_windows",
            "bounded_points",
        )
    }
    if not set(public["counts"]) <= allowed_counts or any(
        type(v) is not int or v < 0 for v in public["counts"].values()
    ):
        raise ValueError("private summary has unsupported aggregate counters")
    public["boundary_verification"] = {
        "producing_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "git_dirty": bool(
            subprocess.check_output(
                ["git", "diff", "HEAD", "--name-only", "--", "src/hachi"], cwd=REPO, text=True
            )
        ),
        "chronos_requests_checked": len(chronos),
        "encoder_content_hashes_checked": len(encoder_rows),
        "request_context_hours": protocol.context_hours,
        "private_fold_joins_checked": len(joins),
        "outer_test_join_rows": 0,
        "private_files_mode": "0600",
        "private_directory_mode": "0700",
        "inference_run": False,
        "packet_files_sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in (
                "protocol.json",
                "clinical-protocol.json",
                "fold-plan.json",
                "sources.json",
                "joins.json",
                "requests.jsonl",
                "encoder-requests.jsonl",
                "summary.json",
            )
        },
    }
    return public


def export(
    snapshot: Path, archive: Path, output: Path, protocol_path: Path, clinical_path: Path
) -> dict:
    protocol = load_context_protocol(protocol_path)
    clinical = ClinicalProtocol.model_validate_json(clinical_path.read_bytes())
    if (
        clinical.active_outer_fold != protocol.active_outer_fold
        or clinical.nested_plan_sha256 != protocol.nested_plan_sha256
    ):
        raise ValueError("clinical contexts require the frozen outer0 participant plan")
    plan = clinical_fold_plan(snapshot, clinical)
    if dataset_snapshot_ref(snapshot).snapshot_sha256 != protocol.snapshot_sha256:
        raise ValueError("label snapshot differs from context protocol")
    if protocol.clock != clinical.clock:
        raise ValueError("source context and clinical split clocks differ")
    archive_sha = verify_archive(archive, protocol)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True):
        raise ValueError("commit context implementation before real extraction")
    folds = [f for f in plan.folds if f.outer_fold == clinical.active_outer_fold]
    development = sorted({s for f in folds for s in f.validation_subjects})
    cutoffs = defaultdict(set)
    for row in read_table(snapshot, "onset_windows", development).to_pylist():
        if any(row[f"onset_{h}h"] in {"positive", "negative"} for h in [24, 48, 72]):
            cutoffs[row["subject_id"]].add(row["cutoff_utc"])
    requests, encoder_requests, joins, counts = {}, {}, [], Counter()
    sources = {}
    for subject, times in sorted(cutoffs.items()):
        native = read_native_context(archive, subject, sorted(times), protocol)
        sources[subject] = native.source_sha256
        counts.update(native.counts)
        for cutoff in sorted(times):
            if cutoff.hour:
                raise ValueError("clinical contexts require floating-midnight cutoffs")
            hours = causal_hours(native.points, cutoff, protocol)
            context = [h.hr_bpm for h in hours]
            observed = sum(v is not None for v in context)
            counts["eligible_cutoffs"] += 1
            rid = None
            encoder_id = None
            if observed >= protocol.min_observed_hr_hours:
                rid = request_id(context, protocol.prediction_hours)
                row = {
                    "request_id": rid,
                    "context": context,
                    "prediction_length": protocol.prediction_hours,
                }
                check_request(row)  # Exercise the actual #12 transport boundary.
                requests.setdefault(rid, row)
                encoder = {
                    "context_policy_sha256": document_sha256(protocol),
                    "hours": protocol.context_hours,
                    "first_hour_local": hours[0].start.hour,
                    "channels": {"heart_rate": context},
                    "units": {"heart_rate": "bpm"},
                }
                encoder_id = document_sha256(encoder)
                encoder_requests.setdefault(encoder_id, {"request_sha256": encoder_id, **encoder})
                counts["requested_cutoffs"] += 1
            else:
                counts["insufficient_hourly_context"] += 1
            for fold in folds:
                role = "validation" if subject in fold.validation_subjects else "train"
                joins.append(
                    {
                        "outer_fold": fold.outer_fold,
                        "inner_fold": fold.inner_fold,
                        "subject_id": subject,
                        "cutoff_floating": cutoff,
                        "role": role,
                        "request_id": rid,
                        "encoder_request_sha256": encoder_id,
                        "observed_hr_hours": observed,
                        "as_of_floating": cutoff,
                        "clock": protocol.clock,
                    }
                )
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_private(output / "protocol.json", protocol)
    write_private(output / "clinical-protocol.json", clinical)
    write_private(output / "fold-plan.json", plan)
    write_private(output / "joins.json", joins)
    write_private(output / "sources.json", sources)
    descriptor = os.open(output / "requests.jsonl", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        for _, row in sorted(requests.items()):
            stream.write(document_bytes(row))
    encoder_descriptor = os.open(
        output / "encoder-requests.jsonl", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
    )
    with os.fdopen(encoder_descriptor, "wb") as stream:
        for _, row in sorted(encoder_requests.items()):
            stream.write(document_bytes(row))
    summary = {
        "git_sha": sha,
        "protocol_sha256": document_sha256(protocol),
        "shared_protocol_sha256": document_sha256(clinical),
        "fold_plan_sha256": document_sha256(plan),
        "archive_sha256": archive_sha,
        "clock": protocol.clock,
        "counts": dict(sorted(counts.items())),
        "unique_requests": len(requests),
        "unique_encoder_requests": len(encoder_requests),
        "request_file_sha256": hashlib.sha256((output / "requests.jsonl").read_bytes()).hexdigest(),
        "encoder_request_file_sha256": hashlib.sha256(
            (output / "encoder-requests.jsonl").read_bytes()
        ).hexdigest(),
        "development_subjects_with_eligible_cutoffs": len(cutoffs),
        "request_rows_have_identities_or_labels": False,
        "outer_test_status": "sealed",
        "inference_status": "not_run",
        "comparison_status": "pending",
    }
    write_private(output / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--archive", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--verify-only", action="store_true")
    p.add_argument("--public-report", type=Path)
    p.add_argument(
        "--protocol", type=Path, default=REPO / "configs/experiments/illness/clinical-contexts.toml"
    )
    p.add_argument(
        "--clinical-protocol",
        type=Path,
        default=REPO / "configs/evaluation/stanford-phase1-clinical.json",
    )
    args = p.parse_args(argv)
    try:
        if not args.verify_only:
            if args.archive is None:
                raise ValueError("archive is required for extraction")
            export(args.snapshot, args.archive, args.output, args.protocol, args.clinical_protocol)
        result = verify_packet(args.snapshot, args.output)
        if args.public_report:
            if result["boundary_verification"]["git_dirty"]:
                raise ValueError("commit context verification before publishing receipt")
            args.public_report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, csv.Error):
        print("Clinical context export failed validation or I/O; private rows withheld.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
