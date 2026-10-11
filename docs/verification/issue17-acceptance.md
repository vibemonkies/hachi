# Issue 17 acceptance evidence

This reference records the acceptance state of [issue 17](https://github.com/vibemonkies/hachi/issues/17) on 2026-10-11.
The issue remains open. Merged source and observed UI behavior are delivered separately from current runtime compatibility.

## PR stack

| Change | Parent | Evidence |
|---|---|---|
| [PR116](https://github.com/vibemonkies/hachi/pull/116) corrects supported alertness wording and records public UI observations. | `main` at `ca77e566fad246393c39a48129bb8e9cf989891f` | Head `cdac421f505b8bb7e13243706187173d8b9d3ec7`, independent [review](https://github.com/vibemonkies/hachi/pull/116#issuecomment-6111882933), and [passing CI](https://github.com/vibemonkies/hachi/actions/runs/38160971321). |
| This acceptance reference collects delivered evidence and the remaining runtime handoff. | PR116 at `cdac421f505b8bb7e13243706187173d8b9d3ec7` | The child diff contains this reference only. It does not change the application or create runtime evidence. |

[PR111](https://github.com/vibemonkies/hachi/pull/111) merged as `9794d1f99561c58fb3671d213ceda132434c9754`.
Its final navigation correction has independent review, direct saved-replay success and error observations, and passing CI.

## Criteria and observations

| Current criterion | Delivered evidence | Remaining condition |
|---|---|---|
| Generated types, import progress, coverage, cutoff selection, forecast intervals, and anomaly handling. | PR111 delivers the integrated source. The [public UI observations](../../apps/web/evidence/issue17-public-states/README.md) cover loading, empty coverage, report navigation, and the specific anomaly unavailable explanation. Existing [runtime observations](../../reports/verification/app-rehearsal/app-runtime-0b58f4e.json) cover generated Apple import and coverage. | Current CPU artifact compatibility remains pending. An unavailable anomaly result does not require a successful anomaly model. |
| Units, coverage, model identity, and real, synthetic, and replay modes. | The [real app receipt](../../reports/verification/app-rehearsal/app-runtime-5a422dd.json) records 24 forecast points and 48 endpoints with zero value, time, or geometry mismatches. Units, artifact, snapshot, code, cutoff, quality, original mode, and replay provenance are visible. | Reconcile the current protocol-bearing CPU artifact with that producing revision. Renew affected observations if the served artifact changes. |
| Illness and recovery results only when supported, otherwise specific unavailable reasons. | The [API receipt](../../reports/verification/app-rehearsal/api-5a422dd.json) records actual unavailable reasons. PR116's public UI observations record the anomaly screen and illness and recovery coverage explanations. These synthetic observations prove presentation, not private inference. | No successful illness or recovery model is required. Actual-response and public presentation evidence must remain separately identified. |
| Loading, errors, empty history, keyboard use, small screens, and accessible plots. | PR116 records keyboard submission, navigation, chart focus, and opening the exact-values table with Enter. It records loading, cancellation controls, empty coverage, and the empty report route. The earlier runtime receipt records a 390px viewport without page overflow and focusable chart and table scroll regions. PR111's final correction records visible replay error and retry behavior. | No new blanket browser run is required for unchanged states. The responsive receipt retains its earlier source revision. |
| Actual inference after the backend handoff and comparison of rendered chart values with API output. | The actual app receipt binds live and API-stopped replay to source `5a422ddb2f1d0dd2a5c4e1003a1c833cf430daca`. The matching API receipt compares 25 validation origins and 600 points against the saved packet and direct evaluator. This uses the existing-subject PMData path, not an observed real Apple upload. | The [current acceptance assessment](https://github.com/vibemonkies/hachi/issues/17#issuecomment-6111769765) permits this real-source path. Current loader compatibility and usable artifact availability remain pending. |

## Pending runtime handoff

The [canonical PR107 request](https://github.com/vibemonkies/hachi/pull/107#issuecomment-6111812272) asks JadeOx and WindyTrout for the usable original CPU artifact receipt.
The current loader requires the evaluated `protocol.json` in the staged CPU artifact directory.
The earlier API receipt records a protocol hash, but does not establish that the new loader can read a compatible staged directory.

The requested receipt identifies the source revision, artifact pin, evaluated protocol, matching packet, snapshot, and authorized environment compatibility.
It also identifies any affected app observations that need renewal.
No reply or current runtime receipt is included in this reference.
Silence does not establish an access failure or unattended ownership.

CoffeeCoder1015 owns issue 17 acceptance. Its existing implementation chat owns PR116.
JadeOx retains the private runtime lane, and WindyTrout retains the API and artifact handoff.
The original coordinator owns routine follow-up through the existing watch.

## Scope limits

The selected 720-hour GPU model, the withheld friend case, and complete scientific acceptance of issues 20, 21, and 22 are separate work.
They are not automatic prerequisites for the permitted original CPU PMData path in issue 17's current assessment.
No private rows, predictions, weights, credentials, or storage paths are included here.

Issue 17 is not closure-ready while the runtime compatibility row is unresolved.
The stack contains a reviewable incomplete acceptance record, not a completion claim.
