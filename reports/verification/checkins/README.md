# #18 synthetic backend/browser checkpoint

Source tested: `4f5da115559ac7091cb19dc5d5652158c683a4f3` (feature `abe991b`
plus current main). API health reported this exact SHA after its process was
restarted. Checkout: `issue-18-ezzy-parallel-checkins` on MacBook-Air-4.local,
represented owner `ezzy1630`, worker `MistyLeopard`. Isolated API `8721`, web
`5181`, own ignored `.cache/api18` workspace/SQLite roots and `.venv`.

The browser mounted the committed feature exports in a temporary private harness;
shared #17 app routes remain another worker's files. All data in this walkthrough
is explicitly **synthetic**. No private wearable archive or clinical participant
was used. The actual API imported 48 generated hourly watch observations as
synthetic Apple XML; this verifies plumbing, not personal-export acceptance.

Through T3 preview, all seven supported entries were submitted through rendered
forms, read from the backend and recovered after a full page reload. HTTP read-back
verified the count and kinds, exact onset event window, separate entry timestamp,
explicit symptom absence, resolution-to-original-onset link, KSS value and PVT
measurements. `receipt.json` records aggregate checks only. The mobile history
screenshot shows synthetic values, never clinical records.

Recovery responses were observed through actual report-job polling:

- Before the synthetic import: `INSUFFICIENT_HISTORY` with the completed-import
  requirement.
- Imported history with unresolved onset: `NO_VALIDATED_RECOVERY_ARTIFACT` with
  the censoring-aware evaluation/artifact requirement.
- After recorded resolution: `NO_ONGOING_EPISODE` with the unresolved-onset
  requirement. The UI shows recorded resolution and displays the API result.

The scenario request preserved separate A/B local bedtime/wake dates, IANA zone,
prior sleep, caffeine and unmodeled light assumptions. The API returned its real
`NO_ARTIFACT_FOR_TASK` / #15-artifact requirement, which the UI displayed with the
submitted assumptions and synthetic mode. No curve was fabricated. Invalid
wake-before-bedtime displayed an actionable error and retained the draft.

At 375 CSS px, the form and history have no horizontal overflow. Keyboard Tab
focus moved through the actual inputs. Desktop1280 and mobile375 rendered states
were inspected. Date inputs were filled through T3 page evaluation after the
preview text-fill operation reported `locator.fill: Error: Malformed value`;
submission and subsequent checks still used the actual form/API path.

Checks: web build passed, 5 Node form/episode-chain tests passed, and 17 API subject
and privacy boundary tests passed. PR #72's check job passed at this revision.

## Remaining acceptance

This is a useful checkpoint, not complete #18 acceptance. Stored corrections and
per-entry deletion await WindyTrout's coordinated contract/API changes. #17 must
wire the feature exports into the actual selected-subject app. #15 must publish
and be served before computed comparison curves can be inspected. Those missing
paths are not replaced by fixture evidence; #18 remains open.

## Stored correction/deletion follow-up

PR #79 is merged and integrated. `correction-deletion-receipt.json` binds API
`f2870c3` and UI `977d312` (the later UI commit only changes deletion focus/error
placement). All work remains in the same isolated synthetic runtime.

The rendered correction form changed the onset severity from 2 to 3, saved a new
version with its own entry time, and preserved the event window. Actual GET
history returned 8 current entries and 9 versions; an inclusive cutoff at the
original entry time returned severity2. Resolution still named the original onset.

The browser attempted confirmed onset deletion and observed the API's 409:
"delete the resolution first." The error initially appeared above the mobile
viewport; the UI fix put it beside the confirmation at y368 in a667px viewport.
Opening deletion focuses its confirmation field; cancelling restores the source
button's focus. After deleting resolution and then onset through the forms,
current/all history contained6 remaining entries. Neither onset version nor the
resolution survived in a prior-cutoff read. The other6 entries remained, and page
reload rendered the same6 rows without horizontal overflow.

`retry-receipt.json` separately records a real stopped-API failure and retry at
source9501011: the draft stayed intact, one error was announced near the form, and
retry after API restart saved one entry. A failed intermediate count check during
hot reload was not accepted as evidence; the frozen-source rerun passed.

The maintained Ajv2020/Ajv-formats parser replaces the temporary structural reader.
8 Node checks cover generated documents, no coercion/default mutation, malformed
nested entries/dates, unknown schema keywords, form/domain boundaries and episode
roots.24 API/correction/privacy checks passed after #79 integration. The remaining
#18 gates are #17 app-route integration and #15 computed scenario publication/API
wiring and rendered curves, plus the supported output/evaluation limitations.
