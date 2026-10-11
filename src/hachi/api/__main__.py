"""Run and operate the local Hachi API.

    python -m hachi.api serve --owner justin06lee [--port 8716]
    python -m hachi.api stage-artifact --model DIR --packet DIR --serving JSON
    python -m hachi.api check-artifact <artifact_id>@<artifact_sha256>

Output is aggregate only: ids, hashes and counts, never participant rows.
"""

import argparse
import ipaddress
import json
import os
import sys
from pathlib import Path

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
    stage.add_argument("--serving", type=Path, required=True, help="ServingSpec JSON file")
    stage.add_argument("--artifact-root", type=Path)
    check = sub.add_parser("check-artifact", help="verify a pinned artifact loads for serving")
    check.add_argument("pin", help="<artifact_id>@<artifact_sha256>")
    check.add_argument("--artifact-root", type=Path)
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
    root = _artifact_root(args.artifact_root)
    try:
        if args.command == "stage-artifact":
            serving = ServingSpec.model_validate_json(args.serving.read_bytes())
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
                "fit_as_of": served.model.fit_as_of.isoformat(),
                "lookback_hours": served.split.lookback_hours,
                "min_history_hours": served.split.min_history_hours,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
