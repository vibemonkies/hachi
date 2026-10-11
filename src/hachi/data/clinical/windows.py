"""Onset-window labels at any cutoff grid, recomputed from a published label snapshot.

`onset_windows.parquet` holds the local-midnight grid. #13 can ask for any other grid (hourly,
say) here; the labels come from the same `labels.classify` the snapshot used, with the
definitions recorded in the snapshot's manifest, so the two never disagree at midnight.
"""

from collections.abc import Iterator, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa

from .config import Definitions
from .labels import DAY, DayRange, EpisodeBlock, Timeline, at, classify
from .snapshot import load_manifest, read_table
from .tables import UTC_US


def definitions(snapshot: Path) -> Definitions:
    return Definitions.model_validate(load_manifest(snapshot)["definitions"]["document"])


def timelines(snapshot: Path, subjects: Sequence[str] | None = None) -> dict[str, Timeline]:
    """Rebuild each participant's label timeline from the snapshot's tables."""
    blocks: dict[str, list[EpisodeBlock]] = {}
    for e in read_table(snapshot, "episodes", subjects).to_pylist():
        blocks.setdefault(e["subject_id"], []).append(
            EpisodeBlock(
                e["episode_id"],
                DayRange(e["onset_first_day"], e["onset_last_day"]),
                e["ongoing_last_day"],
                e["washout_last_day"],
            )
        )
    positives: dict[str, list[tuple[date, bool]]] = {}
    for o in read_table(snapshot, "outcomes", subjects).to_pylist():
        if o["kind"] == "test_result" and o["result"] == "positive":
            day = o["collected_earliest_utc"].date()
            positives.setdefault(o["subject_id"], []).append((day, o["episode_id"] is None))
    surveys: dict[str, dict[date, str]] = {}
    for row in read_table(snapshot, "surveys", subjects).to_pylist():
        surveys.setdefault(row["subject_id"], {})[row["local_date"]] = row["state"]
    out = {}
    for s in read_table(snapshot, "subjects", subjects).to_pylist():
        sid = s["subject_id"]
        tests = positives.get(sid, [])
        out[sid] = Timeline(
            sid,
            DayRange(s["span_first_day"], s["span_last_day"]),
            tuple(sorted(blocks.get(sid, []), key=lambda b: b.onset.first)),
            tuple(sorted(d for d, orphan in tests if orphan)),
            tuple(sorted(d for d, _ in tests)),
            surveys.get(sid, {}),
            s["undated_illness"],
        )
    return out


def _grid(timeline: Timeline, step: timedelta) -> Iterator[datetime]:
    t, end = at(timeline.span.first + DAY), at(timeline.span.last + DAY)
    while t < end:
        yield t
        t += step


def onset_labels(
    snapshot: Path,
    *,
    cutoffs: Sequence[datetime] | None = None,
    step_hours: int | None = None,
    horizons_hours: Sequence[int] | None = None,
    subjects: Sequence[str] | None = None,
) -> pa.Table:
    """Onset and positive-test labels for each participant at each cutoff.

    Give either explicit `cutoffs` (UTC-aware, on the dataset clock; those outside a
    participant's span are skipped) or `step_hours` for a regular grid from each participant's
    second day. Horizons default to the snapshot's definitions.
    """
    if (cutoffs is None) == (step_hours is None):
        raise ValueError("give exactly one of cutoffs or step_hours")
    defs = definitions(snapshot)
    horizons = list(horizons_hours or defs.onset.horizons_hours)
    dataset_id = load_manifest(snapshot)["dataset_snapshot"]["dataset_id"]
    columns: dict[str, list] = {"dataset_id": [], "subject_id": [], "cutoff_utc": []}
    for h in horizons:
        columns |= {f"onset_{h}h": [], f"onset_episode_{h}h": [], f"test_{h}h": []}
    for sid, timeline in sorted(timelines(snapshot, subjects).items()):
        if cutoffs is not None:
            lo, hi = at(timeline.span.first + DAY), at(timeline.span.last + DAY)
            grid: Iterator[datetime] = (c for c in sorted(cutoffs) if lo <= c < hi)
        else:
            assert step_hours is not None
            grid = _grid(timeline, timedelta(hours=step_hours))
        for cutoff in grid:
            columns["dataset_id"].append(dataset_id)
            columns["subject_id"].append(sid)
            columns["cutoff_utc"].append(cutoff)
            for h in horizons:
                onset, episode, test = classify(timeline, cutoff, h, defs)
                columns[f"onset_{h}h"].append(onset)
                columns[f"onset_episode_{h}h"].append(episode)
                columns[f"test_{h}h"].append(test)
    schema = pa.schema(
        [(name, UTC_US if name == "cutoff_utc" else pa.string()) for name in columns]
    )
    return pa.table(columns, schema=schema)
