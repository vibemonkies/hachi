"""Where a subject's data comes from: an Apple Health import or an approved dataset snapshot.

Both readers apply the cutoff rule at read time (`hachi.contracts.causality`): a record informs
an as-of only if it had ended and become available by then.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from hachi.contracts.base import DataMode, DatasetSnapshotRef
from hachi.contracts.metrics import Metric
from hachi.contracts.tables import Observation, SourceKind
from hachi.data import pmdata
from hachi.data.apple_health import iter_observations as apple_observations
from hachi.data.apple_health.hourly import apple_hourly_features
from hachi.evaluation.context import ContextIndex, ContextPolicy, context_index
from hachi.evaluation.features import HourlyFeature, HourlyFeaturePolicy, hourly_features
from hachi.models.density.rule import AppleMinuteThinning
from hachi.storage import child


class SnapshotRefused(ValueError):
    """A configured dataset snapshot failed verification or admission."""


@dataclass(frozen=True)
class Presence:
    """One span during which a metric had usable data, for coverage."""

    metric: Metric
    start_utc: datetime
    end_utc: datetime
    source_kind: SourceKind


@dataclass(frozen=True)
class DatasetSnapshot:
    snapshot_id: str
    path: Path
    ref: DatasetSnapshotRef
    subjects: frozenset[str]
    tz_name: str
    source_kind: SourceKind
    data_mode: DataMode


def open_dataset_snapshot(
    data_root: Path, snapshot_id: str, *, allow_unadmitted: bool = False
) -> DatasetSnapshot:
    """Verify checksums, manifest identity and archive admission before serving a snapshot."""
    path = child(child(data_root, "derived"), snapshot_id)
    if not path.is_dir():
        raise SnapshotRefused(f"snapshot {snapshot_id} is not under the approved data root")
    outcome = pmdata.verify(path)
    if not outcome["ok"]:
        raise SnapshotRefused(f"snapshot {snapshot_id} failed verification")
    manifest = pmdata.load_manifest(path)
    ref = DatasetSnapshotRef.model_validate(manifest["dataset_snapshot"])
    try:
        admission = pmdata.registry_admission(ref.dataset_id)
        admitted = (
            manifest["source"]["archive_sha256"] == admission.archive_sha256
            and ref.dataset_version == admission.dataset_version
        )
    except (KeyError, ValueError):
        admitted = False
    if not admitted and not allow_unadmitted:
        raise SnapshotRefused(f"snapshot {snapshot_id} was not built from an admitted archive")
    content = manifest["config"]["content"]
    return DatasetSnapshot(
        snapshot_id=snapshot_id,
        path=path,
        ref=ref,
        subjects=frozenset(manifest["subjects"]),
        tz_name=content["local_timezone"],
        source_kind=content["source_kind"],
        data_mode="real" if admitted else "synthetic",
    )


@dataclass(frozen=True)
class SubjectData:
    """A resolved, read-only view of one subject's history."""

    subject_id: str
    kind: Literal["apple_import", "dataset_snapshot"]
    data_mode: DataMode
    snapshot: DatasetSnapshotRef
    tz_name: str
    path: Path
    dataset_source_kind: SourceKind | None = None

    @property
    def provides_hourly_features(self) -> bool:
        return self.kind == "dataset_snapshot"

    @property
    def source(self) -> str:
        """The input source a serving profile admits: the training snapshot, or Apple Health."""
        return "apple_health" if self.kind == "apple_import" else "dataset_snapshot"

    def observations(
        self, metric: Metric, as_of: datetime, start: datetime | None = None
    ) -> list[Observation]:
        """Recorded observations of one metric available by `as_of` and starting at `start`."""
        if self.kind == "apple_import":
            rows = (o for o in apple_observations(self.path, as_of=as_of) if o.metric == metric)
        else:
            rows = pmdata.iter_observations(
                self.path, as_of=as_of, subjects=[self.subject_id], metrics=[metric], start=start
            )
        return [o for o in rows if start is None or o.start_utc >= start]

    def hourly_features(
        self,
        policy: HourlyFeaturePolicy,
        as_of: datetime,
        start: datetime | None = None,
        thinning: AppleMinuteThinning | None = None,
    ) -> list[HourlyFeature]:
        """Derived hourly bins final by `as_of`, selected by the model's own feature policy.

        Apple imports are sealed at each hour end by #78's source rule; the policy must carry
        that rule, so a PMData policy can never be stamped onto Apple bins. `thinning` rebuilds
        bins the way a density-variant artifact was evaluated (#102), for either source; both
        then report coverage as sampled minutes / 60.
        """
        if self.kind == "apple_import":
            slot = thinning.slot_seconds if thinning is not None else None
            view = apple_hourly_features(self.path, policy, as_of, start, thin_slot_seconds=slot)
            return [f for f in view.features if start is None or f.start_utc >= start]
        if thinning is None:
            bins = pmdata.iter_aggregates(
                self.path, "hour", as_of=as_of, subjects=[self.subject_id], metrics=[policy.metric]
            )
        else:
            # numpy, from the baselines extra, is needed only to thin snapshot history.
            from hachi.models.density.thinning import thinned_bins

            thinned, _ = thinned_bins(self.path, thinning, subjects=[self.subject_id])
            bins = [  # the same cutoff rule iter_aggregates applies
                b
                for b in thinned
                if b.aggregate.interval_end_utc <= as_of and b.available_at_utc <= as_of
            ]
        view = hourly_features(bins, policy)
        return [f for f in view.features if start is None or f.start_utc >= start]

    def context_index(self, policy: ContextPolicy, cutoff: datetime) -> ContextIndex:
        """Each policy channel's bins in [cutoff - hours, cutoff), final by the cutoff (#12).

        Built exactly as the evaluator's `context_index`, for one subject: a longer model
        context reads these, while the harness history stays the protocol's lookback.
        """
        if self.kind == "apple_import":
            raise ValueError("longer contexts are built from dataset snapshots only")
        start = cutoff - timedelta(hours=policy.hours)
        bins = [
            b
            for b in pmdata.iter_aggregates(
                self.path,
                "hour",
                as_of=cutoff,
                subjects=[self.subject_id],
                metrics=[c.metric for c in policy.channels],
            )
            if b.aggregate.interval_start_utc >= start
        ]
        return context_index(bins, policy)

    def presence(self, as_of: datetime | None) -> Iterator[Presence]:
        """Spans with usable data, for coverage. Snapshots use their hourly and daily bins."""
        if self.kind == "apple_import":
            for o in apple_observations(self.path, as_of=as_of):
                yield Presence(o.metric, o.start_utc, o.end_utc, o.source_kind)
            return
        assert self.dataset_source_kind is not None
        hourly: set[str] = set()
        for resolution in ("hour", "day"):
            for aggregate, _ in pmdata.iter_aggregates(
                self.path, resolution, as_of=as_of, subjects=[self.subject_id]
            ):
                if aggregate.value is None:
                    continue
                if resolution == "hour":
                    hourly.add(aggregate.metric)
                elif aggregate.metric in hourly:
                    continue  # day bins only stand in for metrics without hourly bins
                yield Presence(
                    aggregate.metric,
                    aggregate.interval_start_utc,
                    aggregate.interval_end_utc,
                    self.dataset_source_kind,
                )
