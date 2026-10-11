# Which agents can run together?

**All three teammates can work at once. Multiple agents for one person are also useful when their issues are independent. Issue numbers belong to the whole team; they are not steps each person repeats.**

If Ezzy already has #1 running, do not personally launch #2, #3 and #4 as the next steps: #2/#3 belong to Justin and #4 belongs to CoffeeCoder. Those four issues can run simultaneously across the team, with one active owner/agent per issue. Reassigning ownership requires agreement with the teammate first.

There is no blanket batch of #1–#4 followed by #5–#7. For example, #7 needs the output of #5, so those two cannot be completed independently in the same batch.

## The initial four-agent layout

| Human | Agent | Issue | Dependency |
|---|---|---|---|
| Ezzy (`ezzy1630`) | A | [#1 — GX10 runtime](https://github.com/vibemonkies/hachi/issues/1) | None |
| Justin (`justin06lee`) | A | [#2 — Dataset access](https://github.com/vibemonkies/hachi/issues/2) | None |
| Justin (`justin06lee`) | B | [#3 — Shared contracts](https://github.com/vibemonkies/hachi/issues/3) | None |
| CoffeeCoder (`CoffeeCoder1015`) | A | [#4 — App shell](https://github.com/vibemonkies/hachi/issues/4) | None |

This is a dependency map, not a claim that all four are currently unclaimed. Check your teammates and live issue/PR state before launching anything.

## Ezzy: exact parallel opportunities

| Group you can have running together | When it is available |
|---|---|
| **#1 alone initially** | No other assigned core issue has its full prerequisites yet |
| **#1 + #7**, if #1 is still running | #3 and #5 have landed and passed their gates |
| **#9 + #14** (and unfinished #1) | #7 and #8 have landed; #9 only needs #7 |
| **#10 + #11 + unfinished #14** | #1, #7 and #9 have landed; #14 independently needs #7 and #8 |
| **#12 + unfinished #14** | #10 and #11 have landed |
| **#13 + unfinished #14** | #8, #9 and #12 have landed |
| **#20** | #12, #13, #14 and CoffeeCoder's #15 have landed |

You do not need to wait for #8 to start #9, #10 or #11. It only gates the illness/recovery work that uses its labels. #14 can overlap any independent model issue after its own prerequisites are met. GPU portions still queue.

## Justin: exact parallel opportunities

| Group you can have running together | When it is available |
|---|---|
| **#2 + #3** | Immediately, if neither is already claimed by another agent |
| **unfinished #2 + #6** | #3 has landed; #6 does not need #2 |
| **#5 + #6 + #8** | #2 and #3 have landed |
| **#16 + unfinished #8** | #3, #5, #6 and Ezzy's #9 have landed |
| **#19 + unfinished #8** | #6 and #16 have landed |

#5 and #8 both depend on the source registry, but should own different adapter/report files. They consume shared contracts; they must not both rewrite those contracts or the root lockfile independently. #16 does not need to wait for illness/recovery training: it can load the real baseline artifact from #9 and add later artifacts through the agreed interface.

## CoffeeCoder: exact parallel opportunities

| Group you can have running together | When it is available |
|---|---|
| **#4 alone initially** | No other assigned core issue has its full prerequisites yet |
| **unfinished #4 + #15** | #3 and #5 have landed |
| **#15 + #17** | #3, #4 and #16 have landed; #15 independently needs #3 and #5 |
| **#18 + #21**, if #18 is still running | #18 needs #15/#16/#17; #21 independently needs #6/#9/#20 |
| **#22** | #16, #17, #18, #19, #20 and #21 have landed |
| **#23** | #22 has passed its gates |

The initial app issue #4 already covers fixture-based UI development before the API exists. #17 is the later real-API integration. #21 is the late consented Apple export case, not an early dataset to tune on.

**Optional extensions:** Justin's #24 needs #2/#7 and can run alongside independent core work without competing for its file ownership. Ezzy's #25 needs #20/#22. Neither blocks the initial delivery.

## Check the live queue

From a checkout containing this guide, with GitHub CLI authenticated for this repository:

```sh
python3 scripts/coordination/ready.py --owner ezzy1630
python3 scripts/coordination/ready.py --owner justin06lee
python3 scripts/coordination/ready.py --owner CoffeeCoder1015
# Whole team; explicitly mark active work if GitHub labels have not caught up:
python3 scripts/coordination/ready.py --active 1 2 4
```

The command reads GitHub and does not assign, start, comment, relabel, push or merge anything. It reads dependency sections from the live issues instead of maintaining another dependency list. It identifies open issues whose dependencies are closed as completed, active/review labels, unresolved prerequisites, and optional extensions.

**Its result is a candidate queue, not permission to start.** Before treating a dependency as delivered, check that its required work is merged into `main`, its acceptance evidence passed, and its artifact/data are available where needed. Closing an issue without that evidence does not satisfy it. The command cannot detect an unreported agent or decide whether scientific evidence is adequate. A stale `status:ready` label must never override a known active agent or missing prerequisite.

An open issue with partially delivered prerequisites may permit a specifically scoped subtask, but it is not fully unblocked. Agree on that scope first. Do not invent replacement schemas, silently relax acceptance criteria, or launch a whole blocked issue and call it complete.

## Claiming work and avoiding collisions

1. The human identifies an unclaimed issue assigned to them (or agrees on a reassignment). Check issue comments, labels and open PRs; if another agent is already working on it, continue that work rather than duplicate it.
2. Give one agent the exact issue, owned files, branch/worktree and permitted actions. When GitHub status updates are authorized, record the claim with owner, branch and worktree and set `status:in-progress`. A label is advisory, not an atomic lock; the human coordinates simultaneous starts.
3. Start from fresh `origin/main` in a separate worktree. Two terminals on different branches in the **same folder** are not isolated: changing the branch changes both agents' files.
4. Keep virtual environments, mutable caches, test databases, run directories and service ports separate per agent/run. The same human can have several agents, so an owner-only shared checkout/database is insufficient. Reuse an environment only when immutable and compatible.
5. Shared schemas, root package files, lockfiles and CI have one coordinating owner (#3 initially). Agree interface changes before implementing both callers. Preserve unrelated work.
6. GPU jobs go through the runtime coordination wrapper once #1 supplies it. CPU coding, tests and data work can continue while another agent owns the GPU. Do not provision over someone else's checkout or update a running experiment's environment.

## When to commit, push, fetch and integrate

**Use events rather than a timer.** A push shares a branch with GitHub. A merge makes reviewed work part of `main`. A fetch learns remote changes without changing your files. Updating your branch incorporates those changes. These are separate actions.

| Event | Action |
|---|---|
| Starting an issue | Fetch; create its worktree/branch from `origin/main` |
| A coherent piece is ready | Run relevant checks, commit only your owned changes, and push the issue branch if authorized |
| Before a handoff or long experiment | Push a useful checkpoint if authorized; record the exact commit/configuration. A draft PR may show unfinished work with blockers clearly stated |
| A dependency is merged | Notify dependent owners through an authorized channel; they fetch and integrate it at a clean checkpoint |
| Before requesting review | Fetch/integrate relevant latest `main`, run integration checks, push, and open/update the PR |
| After review and acceptance checks | An authorized person merges the PR. Agents do not infer merge authorization from permission to push |
| After merge | Verify issue completion/evidence, refresh dependent status, and start new work from updated `origin/main` |

Push several focused commits during an issue if useful. Do not wait until the entire project is done, and do not push every temporary edit. A pushed branch is not automatically incorporated into another branch or a running GX10 checkout. Do not pull or install dependencies into a running experiment.

### Start a separate agent safely

Run these in an existing clone; `fetch` and `worktree add` do not change the current checkout's files. Pick an unused branch and sibling directory:

```sh
git fetch origin
# Example for the agent assigned issue 7; only start when its gates are met.
git worktree add -b issue-7-evaluation ../hachi-issue-7 origin/main
cd ../hachi-issue-7
git status --short --branch
```

Do not run `git switch main` or `git pull` in the folder another agent is editing. For a dedicated, clean `main` checkout with no active agent, `git pull --ff-only` is appropriate before creating new work.

### Publish a checkpoint (when authorized)

```sh
git diff
# Stage specific owned files; inspect before committing.
git add path/to/owned-file
git diff --cached --check
git diff --cached
git commit -m "Describe the completed change"
git push -u origin HEAD
```

Run the relevant issue checks before presenting a checkpoint as verified. If pushing unfinished work, identify it as unfinished. Never stage unrelated files, participant data, credentials or checkpoints merely because they appear in `git status`.

### Receive a merged dependency

From **your own** issue worktree, at a clean committed checkpoint:

```sh
git status --short
git fetch origin
git merge origin/main
# Resolve any owned conflicts, run relevant checks, then push if authorized.
```

If the worktree is dirty, finish/commit your own work first; never stash another agent's changes. A merge preserves a published branch's history. Rebasing is an optional choice for an unpublished branch, not the shared default; do not force-push to repair routine coordination. A conflict touching another owner's work needs inspection and agreement, not choosing one side wholesale.

Fetching alone does not update your feature branch. Updating your laptop does not update the GX10. Transfer/fetch the intended committed revision into that agent's isolated remote checkout before its next run and record that revision in the run manifest.

## Prompt to hand an agent

> Work on issue #N in vibemonkies/hachi, assigned to MY_USERNAME. Read AGENTS.md and docs/COORDINATION.md. Check live dependencies, existing claims and PRs before starting. Use a separate worktree/branch and own only the issue's listed files. Preserve other agents' work and coordinate shared interfaces. Implement and verify the acceptance criteria, and report exact blockers rather than weakening them. My allowed actions for this task are: INSERT_AUTHORIZATION_HERE. Do not merge or take another issue unless I authorize that separately.

For example, the human may explicitly allow “commit your changes, push your issue branch, and open a draft PR.” That is not permission to merge, deploy, message people, or begin every subsequent issue. State the intended permissions in the actual request; this example grants none by itself.
