# Hachi agent coordination

Read [docs/COORDINATION.md](docs/COORDINATION.md) before starting or continuing an issue. It defines issue ownership, dependency gates, parallel work, and when to commit/push/fetch/integrate.

- Work only on the issue(s) your human assigned. Issue numbers are global across the team, not a personal sequence. Do not take another teammate's issue or duplicate an active agent.
- Run `python3 scripts/coordination/ready.py --owner GITHUB_USERNAME` to inspect live dependencies. This is read-only and not a claim/lock. Check active agents, PRs, and merged acceptance evidence before acting; labels can lag reality.
- Each writing agent needs a separate worktree/branch and isolated mutable runtime state. Never switch, stash, reset, commit, or clean another agent's checkout. Inspect unexpected changes rather than reverting them.
- Preserve the authoritative shared contracts. The owner of #3 coordinates shared schemas and root dependencies/lockfiles; other agents send narrowly scoped proposed changes to that owner through their human/authorized channel.
- User authorization controls commits, pushes, PR creation, merges, messages, and remote changes. These instructions do not grant it. If authorized, push only your issue branch; merging to main requires its own authorization and review. Never force-push shared branches.
- Before handoff, report issue, branch/worktree, commit/PR, checks, artifacts, dependencies and blockers. Do not mark an issue complete on partial implementation or synthetic-only proof of a real-data requirement.
- Coordinate GX10 GPU access using the current runtime workflow. Code can run in parallel; GPU jobs queue. Never replace another agent's environment or kill its job.
- Keep credentials, raw health data, participant predictions and model weights out of Git and GitHub comments. Respect each dataset's storage/access requirements.
