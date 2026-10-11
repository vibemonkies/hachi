"""Apple-like heart-rate history from PMData: deterministic 5-minute thinning and hourly bins.

Apple Watch records heart rate roughly once per 5 minutes at rest, while PMData's Fitbit
export holds a sample every few seconds. To ask how well the served models forecast *true*
hourly HR from Apple-like history, the history side is thinned and re-binned while the targets
stay on the original full-density aggregates.

Thinning rule (fixed phase, no randomness): within each UTC-aligned slot
``[k·slot, (k+1)·slot)`` keep only the sample with the earliest start, ties broken by
``record_id``. Re-binning mirrors the pipeline (``hachi.data.pmdata.aggregates``): every
original hourly bin is kept, the value is the mean of kept samples, ``observed_count`` is the
number kept, coverage is the share of the hour's slots holding a kept sample (the 5-minute
analogue of "minutes holding at least one sample"), a bin below the pipeline's hourly HR
coverage threshold is null ``insufficient_coverage``, and availability is the latest kept
sample's availability, never before the bin ends.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
from pydantic import Field

from hachi.contracts.base import Contract
from hachi.contracts.tables import Aggregate
from hachi.data.pmdata import FeatureBin, iter_aggregates, load_manifest

US = 1_000_000
HOUR_US = 3600 * US


class ThinningRule(Contract):
    metric: Literal["heart_rate"] = "heart_rate"
    slot_seconds: Annotated[int, Field(gt=0, le=3600)]
    keep: Literal["earliest_start_per_utc_slot"] = "earliest_start_per_utc_slot"
    pipeline_suffix: Annotated[str, Field(pattern=r"^[A-Za-z0-9._+-]{1,24}$")]

    @property
    def slots_per_hour(self) -> int:
        if 3600 % self.slot_seconds:
            raise ValueError("slots must tile the hour")
        return 3600 // self.slot_seconds


class AppleMinuteThinning(ThinningRule):
    """Amendment 1: re-bin exactly like the Apple serving helper (apple_health.hourly).

    Coverage is distinct sampled start minutes / 60, and a bin is null only when it holds no
    sample; density gates live in the feature policy, as they do for served Apple features.
    """

    coverage: Literal["distinct_sampled_minutes_per_60"]


def thin_samples(table: pa.Table, rule: ThinningRule) -> pa.Table:
    """Keep the earliest sample (then lowest record_id) in each subject's UTC slot."""
    ordered = table.sort_by(
        [("subject_id", "ascending"), ("start_utc", "ascending"), ("record_id", "ascending")]
    )
    start = pc.cast(ordered["start_utc"], pa.int64()).to_numpy()
    slot = start // (rule.slot_seconds * US)
    subject = pc.dictionary_encode(ordered["subject_id"]).combine_chunks().indices.to_numpy()
    first = np.ones(len(slot), dtype=bool)
    first[1:] = (slot[1:] != slot[:-1]) | (subject[1:] != subject[:-1])
    return ordered.filter(pa.array(first))


def hourly_from_samples(
    kept: pa.Table,
) -> dict[tuple[str, int], tuple[int, float, int, list[str], int]]:
    """(subject, hour start µs) -> (count, sum, latest availability µs, source ids, minutes)."""
    hour = pc.multiply(
        pc.divide(pc.cast(kept["start_utc"], pa.int64()), pa.scalar(HOUR_US)),
        pa.scalar(HOUR_US),
    )
    table = pa.table(
        {
            "subject_id": kept["subject_id"],
            "hour": hour,
            "value": kept["value"],
            "available": pc.cast(kept["available_at_utc"], pa.int64()),
            "source_id": kept["source_id"],
            "minute": pc.divide(pc.cast(kept["start_utc"], pa.int64()), pa.scalar(60 * US)),
        }
    )
    grouped = table.group_by(["subject_id", "hour"]).aggregate(
        [
            ("value", "count"),
            ("value", "sum"),
            ("available", "max"),
            ("source_id", "distinct"),
            ("minute", "count_distinct"),
        ]
    )
    return {
        (r["subject_id"], r["hour"]): (
            r["value_count"],
            r["value_sum"],
            r["available_max"],
            sorted(r["source_id_distinct"]),
            r["minute_count_distinct"],
        )
        for r in grouped.to_pylist()
    }


def hourly_min_coverage(snapshot: Path) -> float:
    """The snapshot pipeline's own hourly heart-rate coverage threshold."""
    return float(load_manifest(snapshot)["config"]["content"]["min_coverage"]["heart_rate"]["hour"])


def read_samples(snapshot: Path, subjects: Sequence[str] | None = None) -> pa.Table:
    expression = ds.field("metric") == "heart_rate"
    if subjects is not None:
        expression = expression & ds.field("subject_id").isin(list(subjects))
    return ds.dataset(snapshot / "observations.parquet", format="parquet").to_table(
        columns=["subject_id", "record_id", "source_id", "value", "start_utc", "available_at_utc"],
        filter=expression,
    )


def thinned_bins(snapshot: Path, rule: ThinningRule) -> tuple[list[FeatureBin], dict[str, int]]:
    """Every original hourly HR-mean bin, recomputed from the thinned samples only."""
    samples = read_samples(snapshot)
    kept = thin_samples(samples, rule)
    hourly = hourly_from_samples(kept)
    threshold = hourly_min_coverage(snapshot)
    slots = rule.slots_per_hour
    bins: list[FeatureBin] = []
    counts = {"samples": samples.num_rows, "kept_samples": kept.num_rows, "bins": 0}
    for original in iter_aggregates(snapshot, "hour", metrics=["heart_rate"]):
        row = original.aggregate
        if row.aggregation != "mean":
            continue
        start = int(row.interval_start_utc.timestamp() * US)
        end = row.interval_end_utc
        count, total, latest, sources, minutes = hourly.get(
            (row.subject_id, start), (0, 0.0, 0, [], 0)
        )
        if isinstance(rule, AppleMinuteThinning):
            coverage = minutes / 60
            floor = 0.0  # like the Apple helper: only an empty bin is null
        else:
            coverage = min(1.0, count / slots)
            floor = threshold
        if count == 0:
            value, reason, available = None, "no_observations", end
        else:
            value = total / count if coverage >= floor else None
            reason = None if value is not None else "insufficient_coverage"
            available = max(end, datetime.fromtimestamp(latest / US, UTC))
        aggregate = Aggregate.model_validate(
            {
                **row.model_dump(),
                "value": value,
                "null_reason": reason,
                "observed_count": count,
                "coverage": coverage,
                "source_ids": sources if count else [],
                "pipeline_version": f"{row.pipeline_version}+{rule.pipeline_suffix}",
            }
        )
        bins.append(FeatureBin(aggregate, available))
        counts["bins"] += 1
    return bins, counts
