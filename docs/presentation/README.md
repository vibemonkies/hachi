# Evidence-backed presentation preparation

This directory prepares #23. Full issue acceptance remains open on #22 and the
final-selection, actual app and consented case prerequisites. No #23 live/replay dry
run or clinical acceptance is claimed. Only public aggregate evidence is consumed.

- [Narrative](NARRATIVE.md): generated speaker notes with traceable measured claims.
- [Claim ledger](CLAIMS.md): exact public source commit/file hash, selectors, values
  and limits, including original producing receipts inside the pinned sources.
- [Required gate map](GATES.md): all required roadmap milestones and current blockers.
- [Demo runbook](../DEMO.md): proposed roles, future live/offline rehearsal and stop conditions.

## Short spoken version

“Hachi asks what a person's wearable history can actually support. We separate a
physiological forecast from an unusual-signal alert, illness onset, recovery and a
sleep scenario. Missing data and unavailable models stay visible.

“We ran actual pretrained forecasts and actually trained task heads on permitted
research data. The development comparisons measured the zero-shot forecasting
candidate. Development selection now retains long-context zero-shot Chronos after
actual fine-tuning and ensembles failed to demonstrate a gain over it. Adding frozen
wearable representations to the same trained head also did not demonstrate benefit.
We keep the negative results, selection optimism and failed or abstained predictions.
The notes give paired support, uncertainty and burden; native intervals are uncalibrated.

“A separate CPU baseline API and saved-real-result replay consumer were verified
against the frozen development packet. A standalone original sleep simulator is now
available, with synthetic assumptions and no measured alertness validation. Final
artifact freeze/test acceptance, complete app integration, clinical acceptance and
the separately consented personal case are still missing. The next step is independent
final evaluation, then the same artifact through the actual app and a full live/offline
rehearsal. Current clinical exposed partitions are research-only.”

Use generated numerical notes if numbers are needed. Do not copy rounded values into
an untracked slide or talk card. No new accuracy, adaptation win or case claim may be
added without reviewed evidence and a new manifest check.

## Claim manifest interface

Chosen interface: `python3 docs/presentation/check_claims.py`, default read-only
verification; `--write` regenerates only `NARRATIVE.md` and `CLAIMS.md` after pins pass.
It uses Python's standard library and Git, with no app/model dependencies or private
runtime state. A nonzero exit blocks the quantitative narrative.

`claims.json` has explicit `preparation_only` / no-test-authority state. Each source
binds repository path, full integrated commit and file SHA256. Each claim binds exact
scalar JSON-pointer values or an exact text anchor, display formatting and proof limit.
The template references each claim exactly once or more; generated output must match.
Source change, missing commit, bad selector, altered expected value or stale output
fails. Rounding happens only at rendering and never changes the source value.

This was chosen over a free-form prose spreadsheet or private-packet loader: it keeps
provenance executable, avoids a second source of rounded measurements and stays inside
the public presentation scope. Source pins do not certify scientific correctness or
source access. Review still owns interpretation, licensing and clinical acceptance.
The checker does not recompute metrics, inspect private weights/rows, fetch remote
data, choose a model, grant consent, or open the outer test.

## Update and verification

Refresh live issue/dependency/review/mail context. Have the evidence owner identify
accepted public sources and exact producing receipts. Review changes in scope,
denominators and proof limits before replacing any source pin. A new SHA of an altered
packet does not make it accepted. Superseded recovery evidence is refused; pending CMU
scope, unpublished app sources and private artifacts are excluded. The published
simulator README is admitted by exact path; its executable sources are not presentation
inputs. Accepted development selection does not grant final-test or clinical authority.

Edit `claims.json` and `NARRATIVE.template.md`, then run:

```sh
python3 docs/presentation/check_claims.py --write
python3 docs/presentation/check_claims.py
python3 -B -m unittest discover -s docs/presentation -p 'test_*.py'
git diff --check
```

Every measured numerical statement in the generated narrative must be a manifest
claim. Issue numbers, source URLs, hashes and launch instructions are identifiers or
procedural values, not accuracy measurements. Prose outside the generated narrative
contains no independent measured performance headline.

Original source review snapshot: `7db3baafcf0f8a0c3f615c69443a102b58dc4eee`; accepted
development-selection update at `011e98abb1830f7139aece926bdd606388426911` and conditional
simulator update at `85a8c80658e7066dc2a1e9d06ebc4489bf597f21`. Worker AzureOsprey
represents `ezzy1630` for explicitly delegated preparation in the isolated
`issue-23-ezzy-presentation` worktree, branch `issue-23-development-evidence`.
Accountable issue assignee remains
CoffeeCoder1015. Root/SnowyFortress retains scientific and test-opening control.
