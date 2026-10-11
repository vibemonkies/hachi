"""Run and operate the local Hachi API.

    python -m hachi.api serve --owner justin06lee [--port 8716]
    python -m hachi.api stage-artifact --model DIR --packet DIR (--serving JSON | --protocol JSON)
    python -m hachi.api check-artifact <artifact_id>@<artifact_sha256>
    python -m hachi.api handoff --base-url http://127.0.0.1:8716 --packet DIR

Output is aggregate only: ids, hashes and counts, never participant rows.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import sys
from pathlib import Path

from hachi.evaluation.features import HourlyFeaturePolicy
from hachi.storage import DEFAULT_ARTIFACTS

from .artifacts import ArtifactRefused, ServingSpec, load_served_artifact, stage_artifact
from .settings import Settings, SettingsError, parse_pin


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _artifact_root(value: Path | None) -> Path:
    return (
        value or Path(os.environ.get("HACHI_ARTIFACT_ROOT", str(DEFAULT_ARTIFACTS)))
    ).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the API for one owner on loopback")
    serve.add_argument("--owner", help="GitHub login (default HACHI_OWNER)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int)
    serve.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="bind beyond loopback; only when exposure is deliberately authorized",
    )
    stage = sub.add_parser("stage-artifact", help="assemble a served artifact directory")
    stage.add_argument("--model", type=Path, required=True, help="directory save_artifact wrote")
    stage.add_argument("--packet", type=Path, required=True, help="evaluation packet directory")
    spec = stage.add_mutually_exclusive_group(required=True)
    spec.add_argument("--serving", type=Path, help="ServingSpec JSON file")
    spec.add_argument(
        "--protocol",
        type=Path,
        help="the run's protocol.json: serve hourly features with its feature_policy",
    )
    stage.add_argument("--artifact-root", type=Path)
    check = sub.add_parser("check-artifact", help="verify a pinned artifact loads for serving")
    check.add_argument("pin", help="<artifact_id>@<artifact_sha256>")
    check.add_argument("--artifact-root", type=Path)
    handoff = sub.add_parser("handoff", help="compare a running API with a real packet")
    handoff.add_argument("--base-url", required=True)
    handoff.add_argument("--packet", type=Path, required=True, help="evaluations/<model> dir")
    handoff.add_argument("--owner", help="GitHub login (default HACHI_OWNER)")
    handoff.add_argument(
        "--no-direct",
        action="store_true",
        help="compare with the packet only (skip re-running the model; saves GPU jobs)",
    )
    handoff.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        help="largest absolute difference counted as agreement (default exact)",
    )
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from .app import create_app

        if not _loopback(args.host) and not args.allow_non_loopback:
            parser.error("refusing a non-loopback host without --allow-non-loopback")
        try:
            settings = Settings.from_environment(args.owner)
        except SettingsError as exc:
            parser.error(str(exc))
        port = args.port or int(os.environ.get("HACHI_API_PORT", settings.port))
        extra = frozenset() if _loopback(args.host) else frozenset({args.host})
        uvicorn.run(create_app(settings, extra_hosts=extra), host=args.host, port=port)
        return 0
    if args.command == "handoff":
        return _handoff(args, parser)
    root = _artifact_root(args.artifact_root)
    try:
        if args.command == "stage-artifact":
            serving = (
                ServingSpec.model_validate_json(args.serving.read_bytes())
                if args.serving
                else serving_from_protocol(args.protocol, args.model)
            )
            pin = stage_artifact(root, args.model, args.packet, serving)
        else:
            pin = parse_pin(args.pin)
        served = load_served_artifact(root, pin)
    except (ArtifactRefused, SettingsError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "pin": f"{pin.artifact_id}@{pin.artifact_sha256}",
                "model_id": served.model.model_id,
                "metric": served.metric,
                "aggregation": served.aggregation,
                "input": served.serving.input,
                "dataset_snapshot": served.run.dataset_snapshot.model_dump(),
                "fit_as_of": (
                    fit.isoformat() if (fit := getattr(served.model, "fit_as_of", None)) else None
                ),
                "requires_gpu": served.serving.requires_gpu,
                "interval_nominal_coverage": served.serving.interval_nominal_coverage,
                "lookback_hours": served.split.lookback_hours,
                "min_history_hours": served.split.min_history_hours,
            },
            indent=2,
        )
    )
    return 0


def serving_from_protocol(path: Path, model_dir: Path) -> ServingSpec:
    """Hourly-feature serving bound to the exact protocol file the run wrote.

    A Chronos-2 artifact (#10/#12) is served on the GX10 with its own q0.1-q0.9 coverage;
    a #9 baseline is served on the CPU and is point-only.
    """
    data = path.read_bytes()
    protocol = json.loads(data)
    model = json.loads((model_dir / "model.json").read_bytes())
    chronos = model.get("format_version") == "chronos-2-artifact-1"
    if chronos:
        lower, upper = model["chronos"]["interval_lower"], model["chronos"]["interval_upper"]
    return ServingSpec(
        format_version="hachi-serving-1",
        task="physiology_forecast",
        resolution="hour",
        entry_point="hachi.models.chronos.artifacts.load_artifact"
        if chronos
        else "hachi.models.baselines.load_artifact",
        input="hourly_features",
        feature_policy=HourlyFeaturePolicy.model_validate_json(
            json.dumps(protocol["feature_policy"])
        ),
        interval_nominal_coverage=round(upper - lower, 10) if chronos else None,
        requires_gpu=chronos,
        protocol_sha256=hashlib.sha256(data).hexdigest(),
    )


def _handoff(args, parser) -> int:
    from .catalog import Catalog
    from .handoff import load_packet, run_handoff

    try:
        settings = Settings.from_environment(args.owner)
    except SettingsError as exc:
        parser.error(str(exc))
    catalog = Catalog.load(settings)
    run, evaluation = load_packet(args.packet)
    served = next((a for a in catalog.artifacts if a.ref == run.artifact), None)
    if served is None:
        print(json.dumps({"ok": False, "error": "the packet's artifact is not served here"}))
        return 1
    subjects = {}
    for prediction in evaluation["predictions"]:
        subject_id = prediction["origin"]["subject_id"]
        subject = catalog.dataset_subject(subject_id)
        if subject is None:
            print(json.dumps({"ok": False, "error": "a packet subject is not in a served dataset"}))
            return 1
        subjects[subject_id] = subject
    outcome = run_handoff(
        args.base_url,
        args.packet,
        served,
        subjects,
        direct=not args.no_direct,
        tolerance=args.tolerance,
    )
    print(json.dumps(outcome, indent=2, sort_keys=True))
    return 0 if outcome["agrees"] else 1


if __name__ == "__main__":
    sys.exit(main())
