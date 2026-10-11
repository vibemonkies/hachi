# Public UI acceptance observations

Observed on 2026-10-11 from main `ca77e566fad246393c39a48129bb8e9cf989891f`
plus this PR's one-line ImportPanel correction. Node 22.14.0. No tests were
created, modified or executed.

## Runtime

Owned loopback transport on 8795 served committed public Coverage and ReportJob
fixtures, with delayed responses to expose loading. It returned a completed
forecast and an anomaly unavailable response with the API's published requirement.
All subjects, values and timestamps were synthetic. No private runtime, model,
dataset, GPU or participant data was accessed.

The actual application ran on 5195, first with Vite development/HMR for the
before/after comparison, then with the production build and Vite preview.
TypeScript/Vite build passed with 136 modules. Preview PID 52744 listened on
127.0.0.1, and the served index equaled dist/index.html. These observations
verify frontend presentation and interaction, not real inference.

## Observations

| Action | Observed result |
|---|---|
| Open empty-subject through the existing-subject form | Loading coverage text, disabled conflicting controls and Cancel operation appeared. |
| Wait for empty Coverage | No observations are available. No missing values are treated as zero. No forecast series was fabricated. |
| Inspect supported alertness before correction | alertness · data requirements met. |
| Inspect the same empty state after correction | alertness · simulation available · no subject data used. |
| Open sufficient synthetic history | Corrected alertness label remained; physiology forecast retained data requirements met. Unsupported reason codes remained visible. |
| Tab from the main heading | Focus traversed file input, subject ID, timezone, mode selector, clear, existing subject ID, open subject, replay and new import controls. |
| Shift+Tab to existing subject ID, Ctrl+A, type synthetic-001, Enter | Native keyboard submission loaded coverage and returned focus to the main heading. |
| Activate report button with Enter | Forecast and anomaly reports are running text, polling explanation, disabled conflicting controls and Cancel operation appeared. |
| Activate Forecast navigation with Enter | Forecast heading received focus. Chart had an accessible metric/unit name. |
| Tab through forecast content, then Enter on exact-values summary | Focus reached review link, chart region and summary. Enter expanded the UTC/value table. |
| Reload on the forecast route | No report yet and a working keyboard-activated import link appeared. |
| Open Baseline deviation in production preview | Baseline deviation unavailable, NO_ARTIFACT_FOR_TASK and A frozen anomaly artifact with measured healthy-period alert burden appeared. |
| Inspect Illness and recovery on that screen | Illness onset showed NO_VALIDATED_ILLNESS_ARTIFACT. Recovery showed NO_ONGOING_EPISODE. No prediction was fabricated. |

The production coverage screen repeated the corrected supported-alertness label
and both illness/recovery coverage reasons. The response shapes came from public
fixtures and the published API reasons. Existing real PMData live/replay receipts
remain separate and retain their producing source revisions.

## Acceptance limits

This fills the explicit public keyboard, empty, loading and unavailable-display
gaps in issue17 comment6111769765. Existing responsive/mobile evidence is reused;
this run does not claim a new responsive or real-data inference walkthrough.
Current protocol-bearing artifact readability remains with the existing runtime
owner. Successful anomaly, illness or recovery inference is not asserted.
