"""Private JSON commands; stdout reports only receipt hashes and aggregate state."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .journal import Journal
from .policy import ProspectiveRefused
from .specification import FollowUp, Prediction, Protocol


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ProspectiveRefused("invalid command arguments")


def main() -> int:
    parser = PrivateArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("register")
    create.add_argument("journal", type=Path)
    create.add_argument("protocol", type=Path)
    create.add_argument("analysis_plan", type=Path)
    for name, document in (("predict", "input_document"), ("follow-up", "outcome_document")):
        command = sub.add_parser(name)
        command.add_argument("journal", type=Path)
        command.add_argument("record", type=Path)
        command.add_argument(document, type=Path)
        command.add_argument("--expected-head", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("journal", type=Path)
    verify.add_argument("--expected-head", required=True)
    sub.add_parser("generated-proof")
    try:
        args = parser.parse_args()
        if args.command == "generated-proof":
            from .synthetic import generated_proof

            print(json.dumps(generated_proof(), sort_keys=True))
            return 0
        journal = Journal(args.journal)
        if args.command == "register":
            receipt = Journal.create(
                args.journal,
                Protocol.model_validate_json(args.protocol.read_bytes()),
                analysis_plan=args.analysis_plan.read_bytes(),
            )
        elif args.command == "predict":
            receipt = journal.predict(
                Prediction.model_validate_json(args.record.read_bytes()),
                expected_head=args.expected_head,
                input_document=args.input_document.read_bytes(),
            )
        elif args.command == "follow-up":
            receipt = journal.follow_up(
                FollowUp.model_validate_json(args.record.read_bytes()),
                expected_head=args.expected_head,
                outcome_document=args.outcome_document.read_bytes(),
            )
        else:
            receipts = journal.verify(args.expected_head)
            print(
                json.dumps(
                    {
                        "verified_receipts": len(receipts),
                        "head_sha256": args.expected_head,
                        "trusted_attestation": False,
                        "data_mode": "synthetic",
                    }
                )
            )
            return 0
        print(
            json.dumps(
                {
                    "head_sha256": receipt.sha256,
                    "sequence": receipt.body.sequence,
                    "trusted_attestation": False,
                    "data_mode": "synthetic",
                }
            )
        )
        return 0
    except (ProspectiveRefused, ValidationError, OSError, ValueError):
        # Pydantic/OS exceptions can include participant values and private paths.
        print(json.dumps({"status": "refused", "code": "PROSPECTIVE_INPUT_OR_STATE_REFUSED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
