# Issue 18 native Windows scenario receipt

Observed on October 11, 2026 through the current app's native controls and the actual
FastAPI backend. All inputs and outputs are synthetic. No participant data, WSL,
GPU execution, test code, or shared Git configuration changes were used in this run.

## Source and runtime

The backend fix is commit `7777928176a3843bc134cd68c20c41c1d6db688e`, based on
`b4817a96dac484787ce577044033710107532bbf`. The initial interaction and reload
observations used that base with the same backend fixes uncommitted, before a blank
line and environment-variable capitalization were corrected for Ruff. The API was
then restarted at the committed fix and the comparison was submitted again.
`rendered-final.json`, `response.json`, `value-comparison.json`, and `comparison.png`
record the committed backend result. No feature source changed.

The owned checkout was `issue18-scenario-flow/hachi`, on `codex/issue18-scenario-flow`.
Python was native CPython 3.12.13 in the checkout's `.venv`, installed with
`uv sync --extra api --frozen`. Node was 22.14.0, with dependencies from `npm ci`.

The actual launch commands, from repository root and `apps/web` respectively, were:

```powershell
.\.venv\Scripts\python.exe -m hachi.api serve --host 127.0.0.1 --port 18717
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 15187 --strictPort
```

Process-local API configuration set `HACHI_OWNER=CoffeeCoder1015`, port `18717`,
and `HACHI_API_CORS_ORIGINS=http://127.0.0.1:15187`. Database, workspace, and artifact
paths were isolated under a sibling `native-api` directory outside the checkout.
No datasets or trained artifacts were configured. The app process used
`VITE_HACHI_API_BASE_URL=http://127.0.0.1:18717`.

The committed API started successfully as Windows PID 11648. The Vite listener
was Windows Node PID 40396. Direct storage observations accepted a new protected
directory and its subsequent reopen, and refused an existing directory with
inherited permissions. Ruff passed for both changed Python files.

## Interaction and observations

1. Opened `http://127.0.0.1:15187/` in a new browser tab. Selected the synthetic
   identifier `synthetic-scenario-18` using **Open saved history**, then opened
   **Sleep comparison**. This identifier has no imported wearable history. The
   scenario API needs only schedules and assumptions; it reads no subject history.
2. Entered timezone `America/Los_Angeles`, prior sleep `8`, caffeine `none`, and
   the two local schedules in `request.json`. Schedule A slept 23:00 to 07:00;
   schedule B slept 01:00 to 07:00. Submitted **Compare schedules**.
3. Observed two SVG curves and exact-value tables with 33 and 37 points. The app
   displayed both submitted and computed assumptions, synthetic data mode,
   simulation status, a dimensionless 0–1 scale, and the model's limitations.
4. Called the actual API with the same request to preserve `response.json`.
   This is a separate deterministic readback request, not intercepted browser
   traffic. All 70 table timestamps and numeric values matched that response.
   `value-comparison.json` records this comparison at the committed backend.
5. Reloaded the full page. The result and selected subject cleared, and the app
   displayed **Choose a subject first**, as captured in `reload.txt` and
   `reload.png`. Scenario results are not stored by this API. No persistence claim
   is made for this transient comparison.
6. Reopened the same synthetic subject. Submitted a wake time before bedtime and
   observed **Wake time must follow bedtime; include the next day's date.**
   `invalid-input.txt` records the form and error.
7. Corrected that wake time and resubmitted. All 70 values matched the first
   comparison after reload, as recorded in `after-reload.json`.
8. Restarted the API at the committed fix and submitted the unchanged form again.
   The rendered provenance named the committed backend, and all 70 rendered
   values matched the API readback. `curve-detail.png` shows one rendered curve
   with its exact-value table; `comparison.png` preserves the full comparison.

The API response has `mode: simulation`, `validation: null`, synthetic data mode,
and `provenance.dataset_snapshot: null`. Its artifact is
`two-process-v1@b47cf37fb470ee1ebe72a9dc89b508a08e80afe06a564e9b523b79ea474fca84`.
This evidence establishes product interaction and conditional simulation output,
not personal predictive accuracy or causal benefit.

## Literal issue 18 acceptance

| Criterion | Evidence |
| --- | --- |
| Episode fields, uncertainty, event and entry times | Retain [PR 72](https://github.com/vibemonkies/hachi/pull/72) and its original native receipt at the producing revision. |
| Alertness, PVT and optional confounders | Retain PR 72's seven-kind persistence and exact KSS/PVT readback observations. |
| Episode-linked recovery and missing follow-up/unavailable states | Retain the [native form receipt](https://github.com/vibemonkies/hachi/issues/18#issuecomment-6111347366). Current source associates the recovery request/result with the onset root. No validated recovery artifact is available, so no positive distribution is claimed. |
| Schedule comparison with visible assumptions and status | This native app/API receipt, including both computed curves and exact values. |
| Backend save/reload, edit, invalid input and deletion | Retain PR 72 and the later native form/cutoff receipt. This run adds scenario invalid-input correction and full-page reload observations. |

The retained check-in receipts were not repeated. Their producing revisions remain
explicit. The dependencies are delivered, and this receipt fills the previously
missing current scenario interaction. Issue closure and merging remain with the
authorized coordinator. Tests and automated CI were not run under the separate
test-authorization rule. Commit messages suppress CI on publication.

The owned browser tab and both service sessions were closed after capture.
Neither port 15187 nor 18717 had a listener at cleanup. The isolated checkout
retains this evidence; mutable API state remains outside Git.
