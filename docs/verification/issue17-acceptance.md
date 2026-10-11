# Issue 17 acceptance evidence

This reference records the acceptance state of [issue 17](https://github.com/vibemonkies/hachi/issues/17) on 2026-10-11.
The issue remains open pending delivery of the reviewed PR stack.
The source and existing receipts satisfy the CPU handoff through complementary evidence at their producing revisions.
They do not establish a fresh combined execution at the current app and API heads.

## PR stack

| Change | Parent | Evidence |
|---|---|---|
| [PR116](https://github.com/vibemonkies/hachi/pull/116) corrects supported alertness wording and records public UI observations. | `main` at `ca77e566fad246393c39a48129bb8e9cf989891f` | Head `cdac421f505b8bb7e13243706187173d8b9d3ec7`, independent [review](https://github.com/vibemonkies/hachi/pull/116#issuecomment-6111882933), and [passing CI](https://github.com/vibemonkies/hachi/actions/runs/38160971321). |
| This acceptance reference reconciles the delivered evidence and retires the repeated CPU receipt request. | PR116 at `cdac421f505b8bb7e13243706187173d8b9d3ec7` | The child diff contains this reference only. It does not change the application or create runtime evidence. |

[PR111](https://github.com/vibemonkies/hachi/pull/111) merged as `9794d1f99561c58fb3671d213ceda132434c9754`.
Its final navigation correction has independent review, direct saved-replay success and error observations, and passing CI.

## Criteria and observations

| Current criterion | Delivered evidence | Remaining condition |
|---|---|---|
| Generated types, import progress, coverage, cutoff selection, forecast intervals, and anomaly handling. | PR111 delivers the integrated source. The [public UI observations](../../apps/web/evidence/issue17-public-states/README.md) cover loading, empty coverage, report navigation, and the specific anomaly unavailable explanation. Existing [runtime observations](../../reports/verification/app-rehearsal/app-runtime-0b58f4e.json) cover generated Apple import and coverage. | Deliver PR116 and this reference. An unavailable anomaly result does not require a successful anomaly model. |
| Units, coverage, model identity, and real, synthetic, and replay modes. | The [real app receipt](../../reports/verification/app-rehearsal/app-runtime-5a422dd.json) records 24 forecast points and 48 endpoints with zero value, time, or geometry mismatches. Units, artifact, snapshot, code, cutoff, quality, original mode, and replay provenance are visible. | The original CPU compatibility reconciliation is below. These observations retain their producing app revision. |
| Illness and recovery results only when supported, otherwise specific unavailable reasons. | The [API receipt](../../reports/verification/app-rehearsal/api-5a422dd.json) records actual unavailable reasons. PR116's public UI observations record the anomaly screen and illness and recovery coverage explanations. These synthetic observations prove presentation, not private inference. | No successful illness or recovery model is required. Actual-response and public presentation evidence must remain separately identified. |
| Loading, errors, empty history, keyboard use, small screens, and accessible plots. | PR116 records keyboard submission, navigation, chart focus, and opening the exact-values table with Enter. It records loading, cancellation controls, empty coverage, and the empty report route. The earlier runtime receipt records a 390px viewport without page overflow and focusable chart and table scroll regions. PR111's final correction records visible replay error and retry behavior. | No new blanket browser run is required for unchanged states. The responsive receipt retains its earlier source revision. |
| Actual inference after the backend handoff and comparison of rendered chart values with API output. | The actual app receipt binds live and API-stopped replay to source `5a422ddb2f1d0dd2a5c4e1003a1c833cf430daca`. The matching API receipt compares 25 validation origins and 600 points against the saved packet and direct evaluator. The [snapshot report](../../reports/data/pmdata-features-1-simula-2020-04-24.md) records ingestion and reconciliation of the same real PMData snapshot. This uses the existing-subject path, not an observed real Apple upload. | The [current acceptance assessment](https://github.com/vibemonkies/hachi/issues/17#issuecomment-6111769765) permits this real-source path. No new private run is required to combine these existing observations. |

## CPU handoff reconciliation

The [human-directed handoff](https://github.com/vibemonkies/hachi/pull/107#issuecomment-6112099567) assigns the necessary dependency audit to the existing issue 17 owner.
The [completed audit](https://github.com/vibemonkies/hachi/pull/107#issuecomment-6112119475) found existing evidence for the original full-density CPU path.
The earlier PR114 note about a corrected PR107 artifact not being staged refers to the Apple-density artifact.
It does not invalidate the original PMData app observations.

| Evidence | What it establishes |
|---|---|
| [PR107 staging report at `a21da6c`](https://github.com/vibemonkies/hachi/pull/107#issuecomment-6111087041) | WindyTrout reports that the original last-valid and tree models successfully stage with their run protocols. This is the required original-model staging evidence, separate from the Apple-density variant. |
| [Accepted API handoff](https://github.com/vibemonkies/hachi/issues/16#issuecomment-6111671712) | The owner reports original last-valid `e7666ef0…` parity for 600 points and an approved protocol-bearing artifact handoff. The later 504-point rerun in that comment is the tree, not the last-valid model. |
| [Actual API receipt](../../reports/verification/app-rehearsal/api-5a422dd.json) | The original artifact is `hourly-last-valid-v1-141306001b16e168` at `e7666ef0f4665006822f9ee9c0988a6de0df1633175ff217a27666ce6f66fa3b`. The snapshot is `06606ac2708b1c5329b1cfa04e6edfb9a0583c5a6c9f2eb1465b07aebab2ee47`. The frozen run protocol hash is `2adbe991611b949f2a99877422e5836f86540f00ee8961db83128ca554134bd7`. |
| [Published packet index](../../reports/evaluation/pmdata-hourly-validation/packet-index.json) | Its byte hash is `65b9de2982d2c0032d95ad034aecb989d6a1c58628fe0f1a7ce993032fabef1f`, matching the API receipt. The receipt names `outer-0-inner-0/evaluations/hourly-last-valid-v1`. |
| [`stage_artifact` and `committed_protocols`](../../src/hachi/api/artifacts.py) | Staging derives the model pin from its receipt and validates the staged directory before returning. Adding the evaluated protocol does not change the model pin or require refitting. The loader recognizes both committed raw protocol documents and normalized PMData run documents. Their byte hashes need not be equal. |
| [`prepare`](../../scripts/rehearsal/runtime.py) | The current runtime source supplies the frozen protocol to staging and checks that the resulting pin matches the packet. |

The full-density path retains its original inference behavior. The newer thinning and Chronos context paths are separate.
In [`SubjectData.hourly_features`](../../src/hachi/api/sources.py), `thinning is None` still uses the original PMData aggregates and hourly feature function.
The non-Chronos path in [`predictor`](../../src/hachi/api/reports.py) still returns the CPU model's `predict` method.
The forecast and anomaly view files have no changes between `5a422dd` and PR116's tip.
The report client's UTC identity correction and import-page replay navigation correction have their separate PR111 observations.
These source checks and owner staging reports complement the historical real app receipt.
They establish the required handoff without claiming a fresh current-head private execution or present readability of JadeOx's old runtime directory.
The mandatory repeated CPU receipt request is retired for issue 17.

CoffeeCoder1015 owns issue 17 acceptance. Its existing implementation chat owns PR116.
The same issue 17 worker owns any necessary dependency follow-through under the human-directed handoff.
JadeOx's other private runtime work and WindyTrout's other API work retain their owners.
The original coordinator owns routine follow-up through the existing watch.

## Scope limits

The selected 720-hour GPU model, the withheld friend case, and complete scientific acceptance of issues 20, 21, and 22 are separate work.
They are not automatic prerequisites for the permitted original CPU PMData path in issue 17's current assessment.
No private rows, predictions, weights, credentials, or storage paths are included here.

The remaining delivery condition is review and landing of PR116 and this child in dependency order under the applicable merge authority.
Issue 17 can close after that delivery and a final criterion check.
This document does not merge the stack or close the issue.
