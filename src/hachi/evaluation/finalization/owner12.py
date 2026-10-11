"""Read #12's original experiment documents from their producing Git revision."""

import ast
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from hachi.contracts.base import GitSha
from hachi.evaluation.context import ContextPolicy
from hachi.evaluation.features import HourlyFeaturePolicy
from hachi.evaluation.pmdata_run import PMDataProtocol
from hachi.evaluation.serialization import document_sha256
from hachi.models.chronos.pmdata import ChronosPMDataConfig, check_binding
from hachi.models.ensemble.selection import SelectionRule

from .integrity import EvidenceRefused, digest, read_producing_file


@dataclass(frozen=True)
class OwnerExperiment:
    protocol: PMDataProtocol
    rule: SelectionRule
    chronos: ChronosPMDataConfig
    context: ContextPolicy
    variants: dict[str, tuple[int, tuple[str, ...]]]
    adaptation_sha256: str
    adaptation: dict[str, object]
    documents_sha256: dict[str, str]


def owner_experiment(repo: Path, revision: str) -> OwnerExperiment:
    """Mirror the original loader's document binding without loading data or predictors."""
    revision = TypeAdapter(GitSha).validate_python(revision)
    names = {
        "protocol": "configs/evaluation/pmdata-hourly-validation.json",
        "rule": "configs/experiments/pmdata-hourly-selection.json",
        "chronos": "configs/models/chronos/pmdata-hourly-hr.json",
        "adaptation": "configs/experiments/pmdata-hourly-adaptation.json",
        "producer": "src/hachi/models/training/pmdata.py",
    }
    raw = {k: read_producing_file(repo, revision, p) for k, p in names.items()}
    protocol = PMDataProtocol.model_validate_json(raw["protocol"])
    rule = SelectionRule.model_validate_json(raw["rule"])
    chronos = ChronosPMDataConfig.model_validate_json(raw["chronos"])
    adaptation = json.loads(raw["adaptation"])
    check_binding(protocol, chronos)
    if (
        rule.protocol_sha256 != document_sha256(protocol)
        or adaptation["protocol_sha256"] != document_sha256(protocol)
        or adaptation["selection_rule_sha256"] != document_sha256(rule)
    ):
        raise EvidenceRefused("owner experiment documents have inconsistent protocol identities")
    # Read the literal constants that the producing loader actually used. Never
    # execute historical/private source or infer new variants from candidate names.
    constants = {}
    for node in ast.parse(raw["producer"]).body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in {"CONTEXT_HOURS", "VARIANTS"}:
                constants[target.id] = ast.literal_eval(node.value)
    variants = TypeAdapter(dict[str, tuple[int, tuple[str, ...]]]).validate_python(
        constants["VARIANTS"], strict=True
    )
    steps = adaptation["history_accessor"]["steps_policy"]
    context = ContextPolicy(
        hours=constants["CONTEXT_HOURS"],
        channels=[
            protocol.feature_policy,
            HourlyFeaturePolicy(
                **steps, availability_rule=protocol.feature_policy.availability_rule
            ),
        ],
    )
    return OwnerExperiment(
        protocol,
        rule,
        chronos,
        context,
        variants,
        digest(raw["adaptation"]),
        adaptation,
        {names[k]: digest(v) for k, v in raw.items()},
    )
