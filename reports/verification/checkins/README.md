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
