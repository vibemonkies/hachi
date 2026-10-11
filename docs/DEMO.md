# Hachi demonstration preparation

**Full #22/#23 dry-run acceptance is open.** This runbook prepares a truthful
demonstration; no live/replay dry run was executed by the #23 preparation worker.
The existing source-bound independent rehearsal receipts are described in
[the narrative](presentation/NARRATIVE.md). They are separate from the missing
published root-app path and final artifact freeze. Accepted development selection
and the published standalone simulator are described in the updated narrative;
neither supplies the missing whole-app rehearsal.

## Presenter sequence and roles

Proposals only; humans have not confirmed availability or assignments.

| Segment | Proposed presenter | Show / say |
|---|---|---|
| Problem and supported physiology | Ezzy | Why personal signal history is useful; a real forecast, actual future observations and baseline comparison when approved. Show coverage and held-out limits. |
| Sources, causal architecture and inference | Justin | Admission, native cutoff/availability, participant split, exact code/artifact/source identity, API provenance. |
| Pretraining/training evidence and failures | Ezzy with Justin | Accepted development selection, actual fine-tuning/ensembles, paired negative results, no-gain representations, abstention/burden and selection optimism. |
| Product and replay | CoffeeCoder | Published app import/status/error → quality → forecast/anomaly → check-ins → sleep comparison. Retain unavailable clinical states. Replay must remain labeled with original mode/time/artifact. |
| Privacy, personal case and remaining gates | Team | Public aggregates/synthetic illustrations; separate consents and one-person retrospective limit. Name missing full-scope gates explicitly. |

Use [NARRATIVE.md](presentation/NARRATIVE.md) as speaker notes and
[CLAIMS.md](presentation/CLAIMS.md) for questions. A short spoken version is in
[the presentation README](presentation/README.md). Read
[GATES.md](presentation/GATES.md) before choosing what can be shown.

## Documentation rehearsal — runnable now

From this isolated checkout, without application dependencies or private data:

```sh
git status --short --branch
git rev-parse HEAD
python3 docs/presentation/check_claims.py
python3 -B -m unittest discover -s docs/presentation -p 'test_*.py'
git diff --check
```

The checker verifies integrated immutable Git/file pins, exact JSON values or text
anchors, and generated narrative/ledger equality. It does not score data, read private
artifacts, verify consent, select a model, open test or prove a runtime. A failure
blocks use of the numerical notes. Do not update hashes to bypass a source change.

## Gate the actual demonstration

Before running the full path, obtain the accepted #20 packet/selection/freeze and
selected export, Coffee's published #17 app source and agreed wiring, #21's real
case/timeline/separate consent handoff, and #22's integration plan. Root controls
scientific acceptance and any test opening; finalization tooling is not permission.
These full-path handoffs are missing. #12's development-selected native loader and
#15's standalone conditional simulator are accepted scoped inputs, with no final
freeze/test or API/full-app acceptance. Stop full-demo acceptance here until the
remaining handoffs exist.

A deliberately reduced independent CPU research rehearsal may use only the approved
PMData inner-validation packet and original frozen baseline. Its scope must say
“independent rehearsal consumer; no final-selected model or full app acceptance.”
It cannot be called the final system. Do not access reserved outer-test participants.

## Optional standalone synthetic scenario exercise

The accepted public simulator description and exact parameter/request bytes are
pinned in the manifest. With the repository's existing dependencies available, use
an owned external output directory for a future exercise:

```sh
SCENARIO_RUN=$(mktemp -d /tmp/hachi-23-scenario.XXXXXX)
PYTHONPATH="$PWD/src" python3 -m hachi.scenarios.demo \
  --request configs/scenarios/compare-bedtimes.toml \
  --model configs/scenarios/two-process-v1.toml \
  --output "$SCENARIO_RUN"
```

Inspect `result.json` and `curves.svg` against
[the accepted source description](../src/hachi/scenarios/README.md). Keep the
archived implementation/configuration artifact outside Git; do not copy its contents
into public presentation docs. Preserve simulation/synthetic mode, null validation,
disclosed prior-history/phase assumptions and unmodeled caffeine/light effects.
Root's accepted CLI/equation/rendering checks are historical supplied evidence;
the #23 worker has not run this exercise. This optional exercise does not validate
ratings/PVT, integrate an API/app, or satisfy the full live/replay rehearsal.

## Isolated live baseline and offline consumer instructions

The exact prepare/serve/check/save/check/serve commands and pin checks live in
[scripts/rehearsal/README.md](../scripts/rehearsal/README.md), whose bytes are pinned
in the claim manifest. Use that source runbook rather than a divergent copied launch
script. Its historical port reservations are worker-specific: obtain a current
owner handoff or use unoccupied ports supplied to `prepare`; never stop another
listener. The #23 document check needs no service.

For a new authorized rehearsal:

1. Start at the accepted clean commit in the bound isolated checkout. Record full
   SHA, lock/config/schema hashes, Python/tool versions and hostname. Use an owned
   environment/cache, new external private run root and isolated SQLite state.
2. Supply approved immutable private source/packet paths and the externally approved
   packet index pin. The manifest's demonstration receipt identifies the historical
   CPU baseline only; a final-selected export needs its own accepted handoff.
3. Follow `runtime.py prepare`, then retain your own `serve` session. Run `check`
   through actual HTTP and inspect its exit status and sanitized aggregate result.
   Compare health/code/artifact/source/config identity and every expected point
   against the frozen packet and fresh direct inference, including missing/extra points.
4. For the complete app, build the exact published reviewed #17 source with its
   documented API origin and owned package cache. Record served build/index hash.
   Drive actual controls. No injection into UI state, synthetic replacement or
   unpublished source copy qualifies. Without that source, record this step blocked.
5. Save a completed original real result through `replay.py save` to a new private
   cache. Retain the trusted whole-cache digest outside the cache. Stop only the
   retained owned live service; confirm it is unavailable. Check/serve the pinned
   cache without a live fallback.
6. Privately run the source `browser_compare.js` using the collaborative T3 browser,
   with aggregate-only output. Compare rendered medians, units, quality/provenance,
   cutoff and every interval endpoint, elapsed-time geometry, real/replay labels and
   point-only absence of an interval band. Never snapshot or screenshot real charts,
   log participant DOM/network payloads, or put real values/dates in public receipts.
7. Exercise missing/corrupt cache visibly with no fallback. Use distinctly generated
   synthetic data for public desktop/mobile screenshots, unsupported/empty states,
   malformed import and network/job failures. Treat those as transport/UI checks.
8. Stop only retained owned services and close owned browser tabs. Confirm listeners
   gone. Retain private replay/source/operator files in approved storage and publish
   reviewed aggregate receipts only.

The standalone viewer and the final app are distinct consumers. An equality check
on the viewer cannot substitute for the app's import/report/chart or replay gate.
Do not rerun GPU jobs, alter environments or replace a serving profile simply to
make this presentation runnable.

## Full-path acceptance checklist

- Permitted real import: status/progress, sources/units/counts and coverage reconcile;
  malformed import, insufficient history and unsupported metrics retain useful errors.
- Exact accepted artifact: code/build, model hash, snapshot, protocol/config and
  schema match the frozen evaluation and fresh inference; API/UI values agree.
- Forecast and anomaly: actual future comparison, baseline comparison, denominators,
  uncertainty and false-alert burden use the accepted task-specific reports.
- Check-ins: event versus entry time, corrections/deletion and replay as-of states
  preserve causality; missing clinical models remain explicitly unavailable.
- Sleep comparison: both bedtime and wake time, timezone/assumptions and distinct
  simulation labeling; no measured-alertness claim without approved label evaluation.
- Real saved replay: live API unavailable, original mode/time/model/source preserved,
  target times/gaps/rendering checked; missing/corrupt cache has no live/fixture fallback.
- Personal case: real source reconciliation, held future holder, prespecified cutoffs,
  saved prediction hashes before reveal, separate analysis/display consents, failures
  and one-person retrospective limitation. Currently blocked.
- Public materials: only reviewed aggregates and clearly synthetic/empty screenshots;
  licenses/citations/changes and unresolved license conflicts visible.
- Scope: every required roadmap gate is reconciled. Partial preparation or a reduced
  demo is never recorded as full issue/project completion.

## Evidence record to fill after execution

Keep the detailed private run record outside Git. The public sanitized receipt should
contain exact producing commit/config/commands, lock/schema/source/split/packet/model
hashes, environment and measurement scope, aggregate expected/actual counts and
equality results, artifact storage category, synthetic screenshot hashes, unavailable
states, reviewer identity and remaining blockers. No participant identifiers, rows,
predictions, raw exports, operational thresholds, credentials or model weights.

Record activity, readiness and completion separately. A missing reply does not prove
an unattended worker; a saved report alone does not prove rendering; a rendered fixture
does not prove real inference; and a completed reduced rehearsal does not close #23.
