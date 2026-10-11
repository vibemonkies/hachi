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

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds

from hachi.contracts.tables import Aggregate
from hachi.data.pmdata import FeatureBin, iter_aggregates, load_manifest

from .rule import ThinningRule

__all__ = [
    "ThinningRule",
    "hourly_from_samples",
    "hourly_min_coverage",
    "read_samples",
    "thin_samples",
    "thinned_bins",
]

US = 1_000_000
HOUR_US = 3600 * US


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


def hourly_from_samples(kept: pa.Table) -> dict[tuple[str, int], tuple[int, float, int, list[str]]]:
    """(subject, hour start µs) -> (count, sum, latest availability µs, source ids)."""
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
        }
    )
    grouped = table.group_by(["subject_id", "hour"]).aggregate(
        [
            ("value", "count"),
            ("value", "sum"),
            ("available", "max"),
            ("source_id", "distinct"),
        ]
    )
    return {
        (r["subject_id"], r["hour"]): (
            r["value_count"],
            r["value_sum"],
            r["available_max"],
            sorted(r["source_id_distinct"]),
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


def thinned_bins(
    snapshot: Path, rule: ThinningRule, subjects: Sequence[str] | None = None
) -> tuple[list[FeatureBin], dict[str, int]]:
    """Every original hourly HR-mean bin, recomputed from the thinned samples only.

    Slots never span subjects, so restricting to `subjects` gives exactly their bins.
    """
    samples = read_samples(snapshot, subjects)
    kept = thin_samples(samples, rule)
    hourly = hourly_from_samples(kept)
    threshold = hourly_min_coverage(snapshot)
    slots = rule.slots_per_hour
    bins: list[FeatureBin] = []
    counts = {"samples": samples.num_rows, "kept_samples": kept.num_rows, "bins": 0}
    for original in iter_aggregates(snapshot, "hour", metrics=["heart_rate"], subjects=subjects):
        row = original.aggregate
        if row.aggregation != "mean":
            continue
        start = int(row.interval_start_utc.timestamp() * US)
        end = row.interval_end_utc
        count, total, latest, sources = hourly.get((row.subject_id, start), (0, 0.0, 0, []))
        coverage = min(1.0, count / slots)
        if count == 0:
            value, reason, available = None, "no_observations", end
        else:
            value = total / count if coverage >= threshold else None
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
