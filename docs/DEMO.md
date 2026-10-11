# Hachi demonstration preparation

**Full #22/#23 dry-run acceptance is open.** This runbook prepares a truthful
demonstration; no fresh combined live/replay dry run has been recorded at current
main. Existing receipts prove separate product paths at their producing revisions:
the original CPU PMData app and offline replay, and the integrated synthetic sleep
scenario. They do not combine into one current-main run or establish final model
acceptance. The accepted development selection and standalone simulator remain
separate from the final artifact freeze.

## Presenter sequence and roles

Proposals only; humans have not confirmed availability or assignments.

| Segment | Proposed presenter | Show / say |
|---|---|---|
| Problem and supported physiology | Ezzy | Why personal signal history is useful; a real forecast, actual future observations and baseline comparison when approved. Show coverage and held-out limits. |
| Sources, causal architecture and inference | Justin | Admission, native cutoff/availability, participant split, exact code/artifact/source identity, API provenance. |
| Pretraining/training evidence and failures | Ezzy with Justin | Accepted development selection, actual fine-tuning/ensembles, paired negative results, no-gain representations, abstention/burden and selection optimism. |
| Product and replay | CoffeeCoder | App import, report, forecast, check-ins, sleep comparison, and replay. Retain unavailable clinical states. Label replay with the original mode, time, and artifact. |
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

## Reuse the delivered #17 and #18 rehearsal evidence

The receipts below cover different runs and data modes. Keep their producing
revisions attached when you prepare a presentation or a new rehearsal.

| Rehearsal slice | Producing source and receipt | What it establishes |
|---|---|---|
| Original CPU PMData API handoff | [#16/#17 acceptance map](verification/issue17-acceptance.md) and [API receipt](../reports/verification/app-rehearsal/api-5a422dd.json), produced from PR111 `5a422dd` | 25 origins and 600 points matched the frozen packet and direct inference. The original CPU artifact, PMData snapshot, and evaluated protocol are identified. |
| Root app live report and offline replay | [PR114 rehearsal record](../reports/verification/app-rehearsal/README.md#corrected-app-follow-up-at-pr111-5a422dd) | One existing PMData origin rendered 24 points and 48 interval endpoints. The app matched the saved response live and with the API stopped. The receipt retains its original artifact, snapshot, code, units, quality, cutoff, and real mode. |
| Integrated sleep-scenario form | [Merged #18 native scenario receipt](../apps/web/evidence/issue18-windows-20261011/README.md) in [PR119](https://github.com/vibemonkies/hachi/pull/119), with backend observation commit `7777928` | The native app sent a scenario request to the API and rendered two synthetic curves. All 70 displayed timestamps and values matched the API response. A full reload cleared the transient result; reopening the synthetic subject and resubmitting reproduced it. |

The PMData receipts are real research-data evidence. The sleep scenario is a
dimensionless synthetic simulation with null validation and dataset snapshot. Do
not present these receipts as a single combined current-main run. The #17 receipt
is bound to its producing app commit, and the #18 receipt is bound to its later
Windows runtime. Neither proves that a new checkout has run the complete flow.

The #17 app and #18 scenario interaction are now delivered. The remaining full
product demonstration still needs the accepted #20 packet, selected export and
freeze, plus #21's real case, timeline, and separate consent handoff. Root controls
scientific acceptance and any test opening. Finalization tooling does not grant
permission. Do not describe the current development selection or conditional
simulator as a final model.

A deliberately reduced CPU rehearsal may use the approved PMData inner-validation
packet and original frozen baseline. Label it “original CPU PMData rehearsal; no
final-selected model or full app acceptance.” Do not access reserved outer-test
participants. Use the existing authorized owner workflow for any private source or
runtime operation. This document grants no new data access or processing authority.

## Optional standalone synthetic scenario exercise

The standalone CLI and the integrated scenario form are different paths. The
integrated form was observed through the native app and API in the
[#18 scenario receipt](../apps/web/evidence/issue18-windows-20261011/README.md).
It uses synthetic schedules, shows the assumptions and simulation status, and has
no subject-data snapshot or validation result. Use that receipt for the observed
app path. Use the standalone CLI below only when you need its separate SVG output.
With the repository's existing dependencies available, use an owned external
output directory:

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
the #23 worker has not run this exercise. The CLI does not validate ratings/PVT,
reproduce the integrated form, or satisfy the full live/replay rehearsal.

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
4. Build the published app from the same clean checkout and record its commit,
   served build/index hash, and API identity. Use the actual import and report
   controls. Historical PR114 observations remain bound to `5a422dd`; do not use
   them as proof that a different build rendered the same real response. Do not
   inject report state or replace the real path with a synthetic fixture.
5. Use the integrated sleep-scenario form only as a separately labeled synthetic
   simulation. The [#18 receipt](../apps/web/evidence/issue18-windows-20261011/README.md)
   records the exact request, response comparison, and reload behavior. Do not
   describe it as a personal forecast or clinical validation.
6. Save a completed original real result through `replay.py save` to a new private
   cache. Retain the trusted whole-cache digest outside the cache. Stop only the
   retained owned live service; confirm it is unavailable. Check/serve the pinned
   cache without a live fallback.
7. Privately run the source `browser_compare.js` using the collaborative T3 browser,
   with aggregate-only output. Compare rendered medians, units, quality/provenance,
   cutoff and every interval endpoint, elapsed-time geometry, real/replay labels and
   point-only absence of an interval band. Never snapshot or screenshot real charts,
   log participant DOM/network payloads, or put real values/dates in public receipts.
8. Exercise missing/corrupt cache visibly with no fallback. Use distinctly generated
   synthetic data for public desktop/mobile screenshots, unsupported/empty states,
   malformed import and network/job failures. Treat those as transport/UI checks.
9. Stop only retained owned services and close owned browser tabs. Confirm listeners
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
