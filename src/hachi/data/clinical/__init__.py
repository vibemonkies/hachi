"""Illness and recovery outcome labels from admitted cohorts (#8).

Snapshots hold canonical outcome rows plus the onset-window and recovery tables that #13 and #14
read. See README.md beside this file for the definitions, tables and clocks.
"""

from .config import Definitions, load_definitions
from .labels import DayRange, Timeline, classify
from .snapshot import (
    dataset_snapshot_ref,
    labels_known_by,
    load_manifest,
    read_outcomes,
    read_table,
    verify,
)
from .windows import onset_labels, timelines

__all__ = [
    "DayRange",
    "Definitions",
    "Timeline",
    "classify",
    "dataset_snapshot_ref",
    "labels_known_by",
    "load_definitions",
    "load_manifest",
    "onset_labels",
    "read_outcomes",
    "read_table",
    "timelines",
    "verify",
]
