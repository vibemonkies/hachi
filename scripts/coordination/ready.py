#!/usr/bin/env python3
"""Read-only candidate queue derived from Hachi's live GitHub issues."""

import argparse
import json
import re
import subprocess
import sys

REPOSITORY = "vibemonkies/hachi"


def dependencies(issue):
    match = re.search(r"^## Dependencies\s*\n+([^\n]+)", issue.get("body") or "", re.M)
    if not match:
        raise ValueError(f"#{issue['number']}: missing Dependencies section; inspect manually")
    line = match[1].strip()
    if line == "None. Start now.":
        return []
    if not re.fullmatch(r"#\d+(?:\s*,\s*#\d+)*", line):
        raise ValueError(f"#{issue['number']}: unsupported dependency syntax: {line!r}")
    return [int(number) for number in re.findall(r"#(\d+)", line)]


def label_names(issue):
    return {label["name"] for label in issue.get("labels", [])}


def issue_graph(records):
    issues = {
        issue["number"]: issue
        for issue in records
        if "pull_request" not in issue and "tracking" not in label_names(issue)
    }
    graph = {number: dependencies(issue) for number, issue in issues.items()}
    visited, active = set(), set()

    def visit(number):
        if number not in issues:
            raise ValueError(f"Dependency #{number} is absent from the work queue")
        if number in active:
            raise ValueError(f"Dependency cycle at #{number}")
        if number in visited:
            return
        active.add(number)
        for parent in graph[number]:
            visit(parent)
        active.remove(number)
        visited.add(number)

    for number in issues:
        visit(number)
    return issues, graph


def queue_status(number, issues, graph, manually_active):
    issue = issues[number]
    labels = label_names(issue)
    unresolved = [
        parent for parent in graph[number]
        if not (issues[parent]["state"] == "closed"
                and issues[parent].get("state_reason") == "completed")
    ]
    if number in manually_active or "status:in-progress" in labels:
        status = "ACTIVE"
    elif "status:review" in labels:
        status = "REVIEW"
    elif unresolved:
        status = "WAIT"
    elif "status:blocked" in labels:
        status = "CHECK BLOCKER"
    else:
        status = "DEPENDENCIES MET"
    detail = "needs completed " + ", ".join(f"#{n}" for n in unresolved) if unresolved else ""
    if status == "CHECK BLOCKER":
        detail = "dependencies completed; confirm whether blocked label is external or stale"
    return status, detail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", help="Filter by GitHub assignee, case-insensitively")
    parser.add_argument("--active", nargs="*", type=int, default=[],
                        help="Known active issue numbers when labels lag reality")
    args = parser.parse_args(argv)
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPOSITORY}/issues?state=all&per_page=100",
             "--paginate", "--slurp"],
            check=True, capture_output=True, text=True,
        )
        records = [issue for page in json.loads(result.stdout) for issue in page]
        issues, graph = issue_graph(records)
        unknown = set(args.active) - issues.keys()
        if unknown:
            raise ValueError(f"Unknown active issue numbers: {sorted(unknown)}")
        selected = [
            number for number, issue in sorted(issues.items())
            if issue["state"] == "open"
            and (not args.owner or args.owner.casefold() in
                 {person["login"].casefold() for person in issue.get("assignees", [])})
        ]
        print(f"{REPOSITORY} — read-only candidate queue")
        for number in selected:
            issue = issues[number]
            status, detail = queue_status(number, issues, graph, set(args.active))
            owners = ", ".join(person["login"] for person in issue.get("assignees", [])) or "UNASSIGNED"
            extension = " [optional]" if "scope:extension" in label_names(issue) else ""
            print(f"#{number:<3} {status:<18} {owners}{extension}: {issue['title']}")
            if detail:
                print(f"     {detail}")
        if not selected:
            print("No open work issues match this owner/filter.")
        print("\nBefore starting: confirm no active claim/open PR, merged main, acceptance evidence, "
              "available artifacts and authorization. Closed-as-not-planned dependencies do not count. "
              "This command does not claim work or infer unreported agents.")
        return 0
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as error:
        print(f"Cannot determine queue; do not assume work is ready: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
