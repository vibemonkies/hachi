# Hachi agent coordination

Read [docs/COORDINATION.md](docs/COORDINATION.md) before starting or continuing an issue. It defines issue ownership, dependency gates, parallel work, and when to commit/push/fetch/integrate.

## Refresh context before acting

Before starting, resuming, changing scope, or handing off work, refresh the live GitHub context. Repeat this check before posting a status update or requesting review.

1. Read the current issue body, all new comments, assignees, labels, dependencies, and linked issues.
2. Read relevant open and recently merged PR descriptions, changed files, reviews, and unresolved threads. Check delivered acceptance evidence and artifact availability.
3. Read the latest coordination updates in [#26](https://github.com/vibemonkies/hachi/issues/26), dependency threads, and accessible team sync notes linked from them. Account for scope and interface decisions within your human's authorization. Do not guess the contents of unavailable syncs.
4. Fetch the remote state and inspect current `origin/main` versions of this file and `docs/COORDINATION.md`. Integrate relevant changes only at a clean checkpoint in your own checkout. Do not pull into another agent's work or a running experiment.
5. Reconcile changes with your plan and active ownership. Report contradictions, inaccessible context, missing evidence, and exact blockers. Treat local notes and prior chat summaries as historical context. A closed issue or passing build alone does not prove delivery.

## Preserve ownership and evidence

- Work only on the issue(s) your human assigned. Issue numbers are global across the team, not a personal sequence. Do not take another teammate's issue or duplicate an active agent.
- Run `python3 scripts/coordination/ready.py --owner GITHUB_USERNAME` to inspect live dependencies. This is read-only and not a claim/lock. Check active agents, PRs, and merged acceptance evidence before acting; labels can lag reality.
- Each writing agent needs a separate worktree/branch and isolated mutable runtime state. Never switch, stash, reset, commit, or clean another agent's checkout. Inspect unexpected changes rather than reverting them.
- Preserve the authoritative shared contracts. The owner of #3 coordinates shared schemas and root dependencies/lockfiles; other agents send narrowly scoped proposed changes to that owner through their human/authorized channel.
- User authorization controls commits, pushes, PR creation, merges, messages, and remote changes. These instructions do not grant it. If authorized, push only your issue branch; merging to main requires its own authorization and review. Never force-push shared branches.
- Before handoff, report issue, branch/worktree, commit/PR, checks, artifacts, dependencies and blockers. Do not mark an issue complete on partial implementation or synthetic-only proof of a real-data requirement.
- Coordinate GX10 GPU access using the current runtime workflow. Code can run in parallel; GPU jobs queue. Never replace another agent's environment or kill its job.
- Keep credentials, raw health data, participant predictions and model weights out of Git and GitHub comments. Respect each dataset's storage/access requirements.
