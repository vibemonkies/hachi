# Independent fixture walkthrough

Ezzy's independent agent (`SnowyFortress`) exercised CoffeeCoder's merged app on October 11, 2026, 07:41–07:44 UTC. This is fresh browser evidence for issue #4, from a separate reviewer and checkout. It verifies the synthetic UI only.

## Exact artifact

- Checkout: `/Users/ezzyrappeport/.t3/worktrees/Hachi/issue-4-ezzy-verification`.
- Branch: `issue-4-ezzy-verification`; app commit `86d6d9f4eb406b60819861656501509153cda7e0` (merged PR #32).
- Working tree was clean before this evidence directory was created. No app source, contracts, dependencies, or tests changed.
- macOS ARM64; Node `26.3.1`; `npm ci` installed 26 packages and reported zero vulnerabilities; `npm run build` passed TypeScript compilation and Vite `8.3.4` production build.
- Preview command: `node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 5189 --strictPort`, in this checkout's `apps/web`.
- Owned exec session `12124`, PID `63755`; `lsof` confirmed the listener bound to `127.0.0.1:5189`. HTTP response bytes equaled this build's `dist/index.html`, SHA-256 `d54cf6cca20c1e2b559387a60af192d4644bc0c2701f49ab230c05d4901dfb08`.
- T3 preview navigation returned a page but snapshots timed out twice after 15000 ms; status then reported no automation host. CUA's in-app browser was unavailable. The connected Chrome extension drove a newly created tab through public controls, with read-only DOM inspection and genuine JPEG captures. Existing user tabs were preserved.

## Observed results

| Path | Result and evidence |
| --- | --- |
| Initial/pending/cancel | Empty workspace had synthetic disclosures. Loading disabled duplicate submission and exposed Cancel operation. Cancellation returned to the empty workspace. [Empty](01-empty-task.jpg), [canceled](06-canceled-task.jpg). |
| Coverage gate | Complete history showed 342/360 hourly bins, 14/15 resting-HR windows, 13/15 sleep windows. Cutoff controls appeared only after acknowledgment. Request stayed disabled with no cutoff. [Coverage](02-coverage-task.jpg). |
| Latest report | Latest cutoff produced 64, 67, 75, 73, 68, 63 bpm at six UTC timestamps; the chart and table agreed. All three designs completed import → acknowledgment → cutoff → report → forecast on desktop and phone. [Task](18-task-forecast-desktop.jpg), [summary](18-summary-forecast-desktop.jpg), [analysis](18-analysis-forecast-desktop.jpg). |
| Cutoff replacement | Selecting the earlier cutoff immediately removed the old report link. New report values were 62, 64, 72, 70, 66, 61 bpm at the earlier timestamps. [Earlier report](05-earlier-forecast-task.jpg). |
| Overview | Overview showed unavailable illness-onset and recovery with their label/follow-up requirements; heading received focus. [Overview](04-overview-task.jpg). |
| Import failure states | Access denial and decode failure had distinct reasons; retrying access failure repeated the intentional failure. Empty observations supplied no substitute numbers. [Access](07-access-failure-task.jpg), [decode](08-import-failure-task.jpg), [empty](09-empty-observations-task.jpg). |
| Sparse history | Forecast was unavailable at 144/360 bins. Baseline deviation retained `Missing` at `2026-10-07T07:00:00Z` and the chart left a gap. Scores explicitly were not illness probability. [Sparse forecast](10-sparse-forecast-task.jpg), [gap and table](11-sparse-deviation-task.jpg). |
| Unavailable/error reports | Missing model artifact showed an unavailable reason without a chart. Report failure exposed Retry synthetic report; retry repeated the intentional failure. [Missing artifact](12-models-unavailable-task.jpg), [report error](13-report-failure-task.jpg). |
| Symptoms | Empty event time triggered native required-field validation (`valueMissing=true`). The valid headache/Moderate preview separated `2026-10-09T12:00:00Z` event time from actual entry creation time. Leaving and returning removed the preview; recreating and reloading removed it again. [Preview](14-symptom-task.jpg), [phone form](20-symptoms-phone-analysis.jpg). |
| Sleep | Supported schedules used the same 0–100 illustration scale. Steady values were 72, 83, 76, 61, 67; later values were 49, 63, 58, 43, 48. Fixed assumptions and source were disclosed. Unsupported schedule showed no curve. [Steady](15-sleep-steady-task.jpg), [later](16-sleep-later-task.jpg), [unsupported](17-sleep-unavailable-task.jpg). |
| Phone layout | At requested 390 × 844, document clientWidth and scrollWidth both equaled 390 in all designs. Chart widths remained local: 600 inside 351/359-pixel regions. [Task phone](19-task-forecast-phone.jpg), [summary phone](19-summary-forecast-phone.jpg), [analysis phone](19-analysis-forecast-phone.jpg), [coverage phone](22-coverage-phone-analysis.jpg), [sleep phone](21-sleep-phone-analysis.jpg). |
| Keyboard/history | In analysis, ArrowRight moved the focused chart from 40 to 78 pixels after native scrolling settled. Immediate reads in `responsive.json` preceded that animation and remained zero; the settled check is separate. Back restored Symptoms, forward restored Sleep. Enter on Skip to content focused `MAIN#main` and retained `#sleep`. [Settled scroll](keyboard-scroll-settled.json), [navigation](keyboard-navigation.json). |

Each numbered screenshot has a corresponding text DOM snapshot. Captures use full-page JPEGs at the specified viewport width; full-page image height may exceed viewport height. Observations were gathered through public controls without state injection, uploads, or personal data. The Chrome console had extension-origin warnings, with no app-origin error observed.

## Cleanup and limits

The owned Chrome tab was closed and its viewport override reset. Exec session 12124 was interrupted (exit 130); `lsof` found no listener on 5189 afterward. Screenshots and snapshots remain in this directory.

This independent walkthrough supplies the browser handoff evidence requested from Ezzy for #4. Contract agreement with Justin remains outstanding; issue #4 should stay open until that agreement is recorded. No API integration, actual upload, persistence, model execution, scientific accuracy, screen-reader session, reduced-motion emulation, or full permutation of every design/state was verified. Edge states were exercised in task; symptom/sleep phone and keyboard/history checks used analysis. These UI results do not close later real-data/model/demo gates.
