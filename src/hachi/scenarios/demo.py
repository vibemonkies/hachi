"""Offline CLI: one simulation supplies both contract JSON and an SVG."""

import argparse
import json
import subprocess
import tomllib
from datetime import UTC, datetime
from hashlib import sha256
from html import escape
from pathlib import Path

from hachi.contracts.requests import ScenarioRequest

from .contract import build_result, scenario_from_request
from .model import Curve, ModelConfig, simulate


def render_svg(curves: tuple[Curve, ...]) -> str:
    start = min(c.points[0].time_utc for c in curves)
    end = max(c.points[-1].time_utc for c in curves)
    duration = (end - start).total_seconds()
    colors = ("#1967a3", "#ba441b", "#6b448c", "#247548")
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="760" '
        'viewBox="0 0 1100 760" role="img">',
        "<title>Conditional synthetic sleep scenarios</title>",
        '<rect width="1100" height="760" fill="white"/>',
        '<g font-family="sans-serif" font-size="14" fill="#20252b">',
        '<text x="80" y="28">Illustrative simulation; no measured alertness or validation</text>',
    ]
    for i, curve in enumerate(curves):
        parts.append(
            f'<text x="{80 + i * 240}" y="55" fill="{colors[i]}">{escape(curve.schedule_id)}</text>'
        )
    panels = (
        ("pressure", "Sleep pressure S", 0, 1),
        ("circadian", "Circadian C (fixed phase)", -1, 1),
        ("alertness", "Relative alertness A (higher = more simulated alertness)", 0, 1),
    )
    for panel, (field, label, low, high) in enumerate(panels):
        top = 95 + panel * 210
        parts.append(f'<text x="80" y="{top - 10}">{label}</text>')
        for value in (low, (low + high) / 2, high):
            y = top + 150 * (high - value) / (high - low)
            parts.append(
                f'<path d="M80 {y} H1060" stroke="#dce1e6"/>'
                f'<text x="35" y="{y + 5}">{value:g}</text>'
            )
        for i, curve in enumerate(curves):
            coords = " ".join(
                f"{80 + 980 * (p.time_utc - start).total_seconds() / duration:.2f},"
                f"{top + 150 * (high - getattr(p, field)) / (high - low):.2f}"
                for p in curve.points
            )
            parts.append(
                f'<polyline points="{coords}" fill="none" stroke="{colors[i]}" stroke-width="2"/>'
            )
        for fraction in (0, 0.25, 0.5, 0.75, 1):
            instant = (start + (end - start) * fraction).astimezone(UTC)
            x = 80 + 980 * fraction
            parts.append(
                f'<text x="{x}" y="{top + 175}" text-anchor="middle" '
                f'font-size="11">{instant:%m-%d %H:%M}Z</text>'
            )
    parts.append(
        '<text x="80" y="745">Elapsed UTC time; waking intervals only; '
        "alternatives share synthetic prehistory</text></g></svg>"
    )
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request_data = (
        tomllib.loads(args.request.read_text(encoding="utf-8"))
        if args.request.suffix == ".toml"
        else json.loads(args.request.read_text(encoding="utf-8"))
    )
    request = ScenarioRequest.model_validate_json(json.dumps(request_data))
    model_bytes = args.model.read_bytes()
    config = ModelConfig(**tomllib.loads(model_bytes.decode("utf-8")))
    scenario = scenario_from_request(request, config)
    curves = simulate(scenario, config)
    source = Path(__file__).parent
    bundle = {"model.toml": model_bytes.decode("utf-8")}
    for name in ("__init__.py", "model.py", "contract.py", "demo.py", "README.md"):
        bundle[name] = (source / name).read_text(encoding="utf-8")
    bundle_bytes = json.dumps(bundle, sort_keys=True, ensure_ascii=True).encode("utf-8")
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    result = build_result(
        request,
        scenario,
        config,
        curves,
        generated_at=datetime.now(UTC),
        git_sha=git_sha,
        artifact_sha256=sha256(bundle_bytes).hexdigest(),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "model-artifact.json").write_bytes(bundle_bytes)
    (args.output / "request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
    (args.output / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (args.output / "curves.svg").write_text(render_svg(curves), encoding="utf-8")
    print(f"Wrote {len(curves)} synthetic curves to {args.output.resolve()}")


if __name__ == "__main__":
    main()
