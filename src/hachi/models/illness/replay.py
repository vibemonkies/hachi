"""Base-only replay worker, loaded beside an explicitly archived scoring implementation."""

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scoring-source", type=Path, required=True)
    parser.add_argument("--packets", nargs="+", type=Path, required=True)
    args = parser.parse_args()
    # -I ignores ambient import paths; use only the explicitly archived producing revision.
    sys.path.insert(0, str(args.scoring_source))
    from pydantic import TypeAdapter

    from hachi.contracts.base import ArtifactRef
    from hachi.models.illness.artifacts import load
    from hachi.models.illness.metrics import Score

    absent = {name: importlib.util.find_spec(name) is None for name in ("numpy", "sklearn")}
    if not all(absent.values()):
        raise ValueError("replay requires a base environment without fitting dependencies")
    artifacts, count, decisions, max_difference = 0, 0, 0, 0.0
    for root in args.packets:
        summary = json.loads((root / "summary.json").read_bytes())
        for entry in summary["fold_evidence"]:
            if entry["status"] != "fitted":
                continue
            packet = root / (
                f"inner-{entry['inner_fold']}-{entry['horizon_hours']}h-{entry['candidate']}"
            )
            model = load(packet / "model", ArtifactRef.model_validate(entry["artifact"]))
            artifacts += 1
            rows = TypeAdapter(list[Score]).validate_json(
                (packet / "predictions.json").read_bytes()
            )
            for saved in rows:
                actual = model.predict([saved.window])[0]
                max_difference = max(max_difference, abs(actual.probability - saved.probability))
                decisions += actual.alert != saved.alert
                count += 1
    if max_difference >= 1e-12 or decisions:
        raise ValueError("saved artifact inference differs from scoring predictions")
    print(
        json.dumps(
            {
                "numpy_absent": absent["numpy"],
                "sklearn_absent": absent["sklearn"],
                "artifacts_reloaded": artifacts,
                "predictions_replayed": count,
                "max_probability_difference": max_difference,
                "decision_mismatches": decisions,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError):
        print("Replay validation failed; private rows withheld.", file=sys.stderr)
        raise SystemExit(1) from None
