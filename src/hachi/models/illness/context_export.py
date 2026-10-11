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

from hachi.data.clinical.snapshot import dataset_snapshot_ref, read_table
from hachi.evaluation.clinical_protocol import ClinicalProtocol, clinical_fold_plan
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.chronos.inference import check_request, request_id

from .hourly import causal_hours, load_context_protocol, read_native_context, verify_archive
from .run import write_private

REPO = Path(__file__).resolve().parents[4]


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
    p.add_argument("--archive", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
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
        print(
            json.dumps(
                export(
                    args.snapshot, args.archive, args.output, args.protocol, args.clinical_protocol
                ),
                indent=2,
            )
        )
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, csv.Error):
        print("Clinical context export failed validation or I/O; private rows withheld.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
