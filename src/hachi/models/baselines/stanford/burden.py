"""Private, participant-held-out alert burden on surveyed symptom-free Stanford days."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hachi.contracts.base import ArtifactRef, Contract, DatasetSnapshotRef, Sha256, UtcDatetime
from hachi.contracts.manifests import ModelRef, RunManifest, SplitManifest, TimeWindow
from hachi.data.clinical import dataset_snapshot_ref, load_manifest, read_table, verify
from hachi.data.clinical.config import registry_admission
from hachi.evaluation.folds import NestedFoldConfig, nested_participant_folds
from hachi.evaluation.metrics import bootstrap_participant_mean
from hachi.evaluation.serialization import document_bytes, document_sha256
from hachi.models.baselines.nightly import NightlyRequest
from hachi.models.baselines.robust import (
    DeviationScore,
    NightlyRest,
    RobustConfig,
    nightly_deviation,
)

from .rest import StanfordRestPolicy, stanford_nightly_rest
from .source import phase1_members, read_native_nights


class BurdenProtocol(Contract):
    expected_snapshot: DatasetSnapshotRef
    folds: NestedFoldConfig
    active_outer_fold: Annotated[int, Field(ge=0)]
    rest: StanfordRestPolicy
    robust: RobustConfig
    controls: Literal["onset_24h_negative"]
    cutoff: Literal["next_floating_midnight"]
    episode_definition: Literal["consecutive_scored_alert_nights_intersecting_control_days"]
    bootstrap_samples: Annotated[int, Field(ge=2)]
    confidence: Annotated[float, Field(gt=0, lt=1)]
    sensitivities: list[Literal["start", "end"]]
    split_created_at_utc: UtcDatetime

    @model_validator(mode="after")
    def _policies(self) -> Self:
        if len(set(self.sensitivities)) != len(self.sensitivities):
            raise ValueError("sensitivity policies must be unique")
        if self.rest.step_timestamp in self.sensitivities:
            raise ValueError("primary policy must not be repeated as a sensitivity")
        if self.active_outer_fold >= self.folds.outer_folds:
            raise ValueError("active outer fold is outside the configured plan")
        return self


class StanfordAnomalyArtifact(Contract):
    """Data-only frozen algorithm configuration; personal history is supplied as of cutoff."""

    model_id: Literal["causal-nightly-mad-v1"]
    rest: StanfordRestPolicy
    robust: RobustConfig
    source_sha256: dict[str, Sha256]
    protocol_sha256: Sha256


def private_directory(path):
    if not path.exists():
        private_directory(path.parent)
        path.mkdir(mode=0o700)


def private(path, value):
    private_directory(path.parent)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(document_bytes(value))


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def aggregate(rows, protocol):
    total = Counter()
    rates, fractions = [], []
    for row in rows:
        c = row["counts"]
        total.update(c)
        scored = c.get("scored_control_days", 0)
        if scored:
            rates.append(30 * c["alert_episodes_intersecting_controls"] / scored)
            fractions.append(c.get("alerted_control_days", 0) / scored)

    def estimate(values):
        e = bootstrap_participant_mean(
            values,
            samples=protocol.bootstrap_samples,
            confidence=protocol.confidence,
            seed=protocol.folds.seed,
        )
        return asdict(e) if e is not None else None

    observed = total["observed_control_days"]
    return {
        "counts": dict(total),
        "participants_with_scored_control_days": len(rates),
        "episodes_per30_scored_control_days": estimate(rates),
        "alerted_fraction_of_scored_control_days": estimate(fractions),
        "pooled_episodes_per30_all_observed_control_days": (
            30 * total["alert_episodes_intersecting_controls"] / observed if observed else None
        ),
    }


def replay(output: Path) -> dict[str, int]:
    """Replay all saved control decisions from the frozen configuration and causal histories."""
    artifact = StanfordAnomalyArtifact.model_validate_json(
        (output / "artifact" / "model.json").read_bytes()
    )
    decisions = 0
    for path in (output / "participants").glob("*/*.json"):
        for row in json.loads(path.read_bytes())["controls"]:
            night = NightlyRest.model_validate_json(json.dumps(row["feature"]["night"]))
            history = [
                NightlyRest.model_validate_json(json.dumps(n)) for n in row["causal_baseline"]
            ]
            cutoff = datetime.fromisoformat(row["feature"]["request"]["cutoff"])
            actual = nightly_deviation(night, history, artifact.robust, cutoff=cutoff)
            if actual.model_dump(mode="json") != row["score"]:
                raise ValueError("frozen anomaly artifact replay differs")
            decisions += 1
    return {"decisions_replayed": decisions, "mismatches": 0}


def run(snapshot, archive, output, protocol):
    if not verify(snapshot)["ok"] or dataset_snapshot_ref(snapshot) != protocol.expected_snapshot:
        raise ValueError("clinical snapshot identity or verification mismatch")
    if protocol.expected_snapshot.dataset_id != "stanford-covid19-wearables":
        raise ValueError("this first burden protocol uses admitted phase1 only")
    admission = registry_admission(protocol.expected_snapshot.dataset_id)
    expected = admission.files["COVID-19-Wearables.zip"]
    if archive.stat().st_size != expected.bytes or sha(archive) != expected.sha256:
        raise ValueError("native archive admission mismatch")
    if load_manifest(snapshot)["clock"] != protocol.rest.clock:
        raise ValueError("native and label clocks differ")
    subjects = read_table(snapshot, "subjects")["subject_id"].to_pylist()
    plan = nested_participant_folds(subjects, protocol.folds)
    selected = [f for f in plan.folds if f.outer_fold == protocol.active_outer_fold]
    if not selected:
        raise ValueError("active outer fold not in grouped plan")
    development = {s for f in selected for s in f.validation_subjects}
    controls = defaultdict(set)
    for row in read_table(snapshot, "onset_windows").to_pylist():
        if row["onset_24h"] == "negative" and row["subject_id"] in development:
            controls[row["subject_id"]].add(row["cutoff_day"])
    if not controls:
        raise ValueError("no eligible observed symptom-free validation controls")
    surveys = defaultdict(dict)
    for row in read_table(snapshot, "surveys").to_pylist():
        surveys[row["subject_id"]][row["local_date"]] = row["state"]
    members = phase1_members(archive)
    repo = Path(__file__).resolve().parents[5]
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True))
    now = datetime.now(UTC)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    private(output / "protocol.json", protocol)
    private(output / "fold-plan.json", plan)
    source_root = Path(__file__).parent
    source_hashes = {p.name: sha(p) for p in source_root.glob("*.py")}
    source_hashes["robust.py"] = sha(source_root.parent / "robust.py")
    artifact = StanfordAnomalyArtifact(
        model_id="causal-nightly-mad-v1",
        rest=protocol.rest,
        robust=protocol.robust,
        source_sha256=source_hashes,
        protocol_sha256=document_sha256(protocol),
    )
    private(output / "artifact" / "model.json", artifact)
    artifact = StanfordAnomalyArtifact.model_validate_json(
        (output / "artifact" / "model.json").read_bytes()
    )
    artifact_ref = ArtifactRef(
        artifact_id="stanford-causal-nightly-mad-v1",
        artifact_sha256=document_sha256(artifact),
    )
    results = defaultdict(list)
    native_counts = Counter()
    for subject, days in sorted(controls.items()):
        first, last = min(days) - timedelta(days=protocol.robust.baseline_days), max(days)
        native = read_native_nights(archive, members, subject, first, last)
        native_counts.update(native.counts)
        for edge in [protocol.rest.step_timestamp, *protocol.sensitivities]:
            rest_policy = artifact.rest.model_copy(update={"step_timestamp": edge})
            history = []
            rows = []
            counts = Counter()
            episodes = set()
            episode = 0
            previous_alert = False
            previous_day = None
            day = first
            while day <= last:
                cutoff = datetime.combine(day + timedelta(days=1), time(), UTC)
                request = NightlyRequest(
                    dataset_id=protocol.expected_snapshot.dataset_id,
                    subject_id=subject,
                    local_date=day,
                    tz_name="UTC",
                    cutoff=cutoff,
                )
                feature = stanford_nightly_rest(
                    native.heart_rate.get(day, ()), native.steps.get(day, ()), request, rest_policy
                )
                # Source survey answers are assumed known at their day's end. No retrospective
                # episode labels, current-night values or future surveys fit the baseline.
                baseline = [
                    n for n in history if surveys[subject].get(n.local_date) != "symptomatic"
                ]
                score = nightly_deviation(feature.night, baseline, artifact.robust, cutoff=cutoff)
                alert = isinstance(score, DeviationScore) and score.alert
                if alert and (not previous_alert or previous_day != day - timedelta(days=1)):
                    episode += 1
                if day in days:
                    counts["observed_control_days"] += 1
                    if isinstance(score, DeviationScore):
                        counts["scored_control_days"] += 1
                        counts["alerted_control_days"] += int(alert)
                        if alert:
                            episodes.add(episode)
                    else:
                        counts[f"abstained_{score.reason}"] += 1
                    rows.append(
                        {
                            "feature": feature,
                            "score": score,
                            "causal_baseline": [
                                n
                                for n in baseline
                                if n.local_date
                                >= day - timedelta(days=artifact.robust.baseline_days)
                            ],
                            "known_symptomatic_baseline_nights_omitted": len(history)
                            - len(baseline),
                        }
                    )
                history.append(feature.night)
                previous_alert = alert
                previous_day = day
                day += timedelta(days=1)
            counts["alert_episodes_intersecting_controls"] = len(episodes)
            counts["confounder_records_available"] = 0
            private(
                output / "participants" / subject / f"{edge}.json",
                {"native_audit": native.counts, "counts": counts, "controls": rows},
            )
            results[edge].append({"subject_id": subject, "counts": dict(counts)})
    first = min(min(d) for d in controls.values()) + timedelta(days=1)
    last = max(max(d) for d in controls.values()) + timedelta(days=2)
    for fold in selected:
        split = SplitManifest(
            schema_version="0.1",
            manifest_id=f"stanford-anomaly-outer{fold.outer_fold}-inner{fold.inner_fold}",
            created_at_utc=protocol.split_created_at_utc,
            dataset_snapshot=protocol.expected_snapshot,
            task="anomaly",
            fold=fold.outer_fold,
            n_folds=protocol.folds.outer_folds,
            **fold.partitions(),
            lookback_hours=protocol.robust.baseline_days * 24,
            horizon_hours=24,
            embargo_hours=0,
            cutoff_stride_hours=24,
            min_history_hours=0,
            evaluation_window=TimeWindow(
                start_utc=datetime.combine(first, time(), UTC),
                end_utc=datetime.combine(last, time(), UTC),
            ),
            seed=protocol.folds.seed,
            test_opened_at_utc=None,
        )
        private(output / f"inner-{fold.inner_fold}" / "split.json", split)
        private(
            output / f"inner-{fold.inner_fold}" / "metrics.json",
            {
                edge: aggregate(
                    [r for r in rows if r["subject_id"] in fold.validation_subjects], protocol
                )
                for edge, rows in results.items()
            },
        )
        run_manifest = RunManifest(
            schema_version="0.1",
            run_id=f"stanford-anomaly-inner{fold.inner_fold}",
            created_at_utc=now,
            git_sha=git_sha,
            git_dirty=dirty,
            config_sha256=document_sha256(protocol),
            dataset_snapshot=protocol.expected_snapshot,
            split_manifest_sha256=document_sha256(split),
            task="anomaly",
            feature_order=["nightly_resting_hr"],
            model=ModelRef(
                model_id="causal-nightly-mad-v1",
                checkpoint_source=None,
                checkpoint_revision=None,
                license=None,
            ),
            environment_sha256=sha(repo / "uv.lock"),
            seed=protocol.folds.seed,
            artifact=artifact_ref,
            metrics_paths=["metrics.json"],
        )
        private(output / f"inner-{fold.inner_fold}" / "run.json", run_manifest)
    summary = {
        "data_mode": "real",
        "git_sha": git_sha,
        "git_dirty": dirty,
        "dataset_snapshot": protocol.expected_snapshot.model_dump(),
        "protocol_sha256": document_sha256(protocol),
        "nested_plan_sha256": document_sha256(plan),
        "source_sha256": source_hashes,
        "native_archive_sha256": expected.sha256,
        "outer_test_sealed": True,
        "validation_roster_participants": len(development),
        "participants_with_control_days": len(controls),
        "native_counts": dict(native_counts),
        "artifact": artifact_ref.model_dump(),
        "confounders": (
            "Exercise, alcohol, vaccination and travel unavailable; no absence inferred. "
            "Known symptomatic survey nights omitted from baseline."
        ),
        "definition": (
            "Daily decision at next floating midnight scores the prior completed night. "
            "Horizon24 is the decision cadence, not a future illness probability."
        ),
        "policies": {},
    }
    summary["policies"] = {edge: aggregate(rows, protocol) for edge, rows in results.items()}
    summary["replay"] = replay(output)
    private(output / "aggregate-summary.json", summary)
    private(
        output / "sha256.json",
        {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()},
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["snapshot", "archive", "output", "protocol"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    protocol = BurdenProtocol.model_validate_json(args.protocol.read_bytes())
    print(
        json.dumps(
            run(args.snapshot, args.archive, args.output, protocol), indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
