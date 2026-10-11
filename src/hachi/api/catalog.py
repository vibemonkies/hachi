"""What this API instance serves: verified dataset snapshots, served artifacts and subjects."""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hachi.storage import Metadata, Workspace

from .artifacts import ArtifactRefused, ServedArtifact, load_served_artifact
from .gpu import Gx10Target, SshTransport
from .settings import Settings
from .sources import DatasetSnapshot, SnapshotRefused, SubjectData, open_dataset_snapshot

if TYPE_CHECKING:
    from .scenarios import ScenarioModel

log = logging.getLogger("hachi.api")


@dataclass
class Catalog:
    datasets: tuple[DatasetSnapshot, ...] = ()
    artifacts: tuple[ServedArtifact, ...] = ()
    scenario_model: "ScenarioModel | None" = None
    # Sanitized reasons a configured snapshot or artifact is not served; health is degraded.
    problems: list[str] = field(default_factory=list)
    gx10: Gx10Target | None = None

    @classmethod
    def load(cls, settings: Settings) -> "Catalog":
        catalog = cls(gx10=gx10_target(settings))
        datasets = []
        for snapshot_id in settings.dataset_snapshots:
            assert settings.data_root is not None
            try:
                datasets.append(
                    open_dataset_snapshot(
                        settings.data_root,
                        snapshot_id,
                        allow_unadmitted=settings.allow_unadmitted_snapshots,
                    )
                )
            except (SnapshotRefused, OSError, ValueError) as exc:
                catalog.problems.append(f"dataset snapshot {snapshot_id}: {exc}")
        owners: dict[str, str] = {}
        for snapshot in datasets:
            for subject in snapshot.subjects:
                if subject in owners:
                    catalog.problems.append(
                        f"subject ids overlap between {owners[subject]} and {snapshot.snapshot_id}"
                    )
                owners.setdefault(subject, snapshot.snapshot_id)
        catalog.datasets = tuple(datasets)
        artifacts = []
        for pin in settings.served_artifacts:
            try:
                artifacts.append(load_served_artifact(settings.artifact_root, pin, catalog.gx10))
            except (ArtifactRefused, OSError, ValueError) as exc:
                catalog.problems.append(f"artifact {pin.artifact_id}: {exc}")
        catalog.artifacts = tuple(artifacts)
        from .scenarios import load_scenario_model

        try:
            catalog.scenario_model = load_scenario_model(settings.scenario_model)
        except (OSError, ValueError) as exc:
            catalog.problems.append(f"scenario model: {exc}")
        for problem in catalog.problems:
            log.warning("not served: %s", problem)
        return catalog

    def dataset_for(self, subject_id: str) -> DatasetSnapshot | None:
        return next((d for d in self.datasets if subject_id in d.subjects), None)

    def dataset_subject(self, subject_id: str) -> SubjectData | None:
        dataset = self.dataset_for(subject_id)
        if dataset is None:
            return None
        return SubjectData(
            subject_id=subject_id,
            kind="dataset_snapshot",
            data_mode=dataset.data_mode,
            snapshot=dataset.ref,
            tz_name=dataset.tz_name,
            path=dataset.path,
            dataset_source_kind=dataset.source_kind,
        )

    def subject(
        self, subject_id: str, metadata: Metadata, workspace: Workspace
    ) -> SubjectData | None:
        """A dataset subject, else the subject's latest succeeded import, else None."""
        if (dataset := self.dataset_subject(subject_id)) is not None:
            return dataset
        record = metadata.latest_succeeded_import(subject_id)
        if record is None or record.snapshot is None:
            return None
        return SubjectData(
            subject_id=subject_id,
            kind="apple_import",
            data_mode=record.status.data_mode,
            snapshot=record.snapshot,
            tz_name=record.status.declared_tz_name,
            path=workspace.import_directory(record.import_id) / "snapshot.sqlite3",
        )


def gx10_target(settings: Settings) -> Gx10Target | None:
    if not settings.gx10_ssh or not settings.gx10_checkout:
        return None
    return Gx10Target(
        transport=SshTransport(settings.gx10_ssh),
        owner=settings.owner,
        checkout=settings.gx10_checkout,
        timeout_seconds=settings.gx10_timeout_seconds,
    )
