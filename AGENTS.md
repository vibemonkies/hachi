# Hachi agent coordination

Read [docs/COORDINATION.md](docs/COORDINATION.md) before starting or continuing an issue. It defines issue ownership, dependency gates, parallel work, and when to commit/push/fetch/integrate.

## Refresh context before acting

Before starting, resuming, changing scope, or handing off work, refresh the live GitHub context. Repeat this check before posting a status update or requesting review.

1. Read the current issue body, all new comments, assignees, labels, dependencies, and linked issues.
2. Read relevant open and recently merged PR descriptions, changed files, reviews, and unresolved threads. Check delivered acceptance evidence and artifact availability.
3. Read the latest coordination updates in [#26](https://github.com/vibemonkies/hachi/issues/26), dependency threads, and accessible team sync notes linked from them. Reconcile scope and interface decisions with the agreed work. Do not guess the contents of unavailable syncs.
4. Fetch the remote state and inspect current `origin/main` versions of this file and `docs/COORDINATION.md`. Integrate relevant changes only at a clean checkpoint in your own checkout. Do not pull into another agent's work or a running experiment.
5. Reconcile changes with your plan and active ownership. Report contradictions, inaccessible context, missing evidence, and exact blockers. Treat local notes and prior chat summaries as historical context. A closed issue or passing build alone does not prove delivery.

## Preserve ownership and evidence

- Work on assigned issues or recorded agent handoffs under the coordination process. Issue numbers are global across the team, not a personal sequence. Coordinate ownership changes in issue or PR threads. Do not duplicate an active agent.
- Keep completion, dependency readiness, and current activity separate. An unfinished issue is not an unattended issue. Treat missing activity evidence as unknown and request an agent checkpoint before considering a handoff.
- Run `python3 scripts/coordination/ready.py --owner GITHUB_USERNAME` to inspect live dependencies. This is read-only and not a claim/lock. Check active agents, PRs, and merged acceptance evidence before acting; labels can lag reality.
- Each writing agent needs a separate worktree/branch and isolated mutable runtime state. Never switch, stash, reset, commit, or clean another agent's checkout. Inspect unexpected changes rather than reverting them.
- Preserve the authoritative shared contracts. The owner of #3 coordinates shared schemas and root dependencies/lockfiles; other agents send narrowly scoped proposed changes to that owner through the agreed coordination channel.
- Use the agreed workflow's delegated permissions for routine GitHub comments, claims, status updates, eligible handoffs, owned commits/pushes, and PR creation. Do not request approval again for actions already delegated. Stay within that scope. Merging, deploying, destructive actions, and access or consent decisions require their own authority. Never force-push shared branches.
- Before handoff, report issue, branch/worktree, commit/PR, checks, artifacts, dependencies and blockers. Do not mark an issue complete on partial implementation or synthetic-only proof of a real-data requirement.
- Coordinate GX10 GPU access using the current runtime workflow. Code can run in parallel; GPU jobs queue. Never replace another agent's environment or kill its job.
- Keep credentials, raw health data, participant predictions and model weights out of Git and GitHub comments. Respect each dataset's storage/access requirements.
