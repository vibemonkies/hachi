# Browser observations

The coordinator exercised the local synthetic interface on October 10, 2026, in America/Los_Angeles. This record describes direct browser observations. It does not establish predictive accuracy or satisfy the separate teammate walkthrough gate in issue #4.

## Artifact and environment

The implementation starts at commit `554daf5fd351144aa8f85c76df1165e85d548b8d`. Commit `bb35308` contains the phone layout correction and the explicit explanation of static baseline metadata. Commit `e28a1be` scopes Symptoms and Sleep status to those sections. The final production build includes all three changes and the team coordination work from `main` at `3c690d7`.

The environment was Windows, Node 22.14.0, npm 11.6.0, TypeScript 7.0.2, and Vite 8.3.4. `npm ci` and `npm run build` completed successfully. Vite transformed 23 modules. The first clean install encountered a Windows file lock while the development server held Rolldown's native module. After stopping that server, the clean install succeeded.

The initial interaction captures came from the Vite development server on loopback port 5175. The final desktop forecast, sparse anomaly, symptom preview, sleep examples, mobile coverage, mobile forecast, and mobile sleep captures came from the production preview on the same port. The preview command was `node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 5175 --strictPort`.

## Observed behavior

| Interface | Observation | Capture |
| --- | --- | --- |
| Import | Load showed a pending state, disabled duplicate submission, and exposed Cancel operation. Cancellation returned to the empty workspace. | [Loading](loading-history.jpg) |
| Coverage | Complete history showed 342/360 hourly bins, 14/15 resting-HR windows, and 13/15 sleep windows. Report controls required coverage acknowledgment and a named UTC cutoff. | [Desktop coverage](desktop-coverage.jpg), [phone coverage](mobile-coverage.jpg) |
| Report cutoff | Changing October 10 to October 9 removed the old report. A new request showed the distinct earlier fixture. The latest forecast values were 64, 67, 75, 73, 68, and 63 bpm. The earlier values were 62, 64, 72, 70, 66, and 61 bpm. | [Latest forecast](desktop-forecast.jpg), [phone forecast](mobile-forecast.jpg) |
| Empty history | Empty observations showed an explicit empty result without substitute numbers. | [Empty history](empty-history.jpg) |
| Access and import failures | Each scenario showed its own error and retry control. | [Access failure](access-error.jpg), [import failure](import-error.jpg) |
| Sparse history | Forecast was unavailable with 144/360 hourly bins. The anomaly table retained a Missing value at 2026-10-07T07:00:00Z and the chart retained a gap. | [Sparse forecast](sparse-forecast.jpg), [sparse anomaly](sparse-anomaly.jpg) |
| Unavailable models | Forecast, anomaly, illness onset, and recovery exposed unavailable states with requirements. | [Unavailable models](unavailable-models.jpg) |
| Report failure | The intentional fixture failed again on retry at the same cutoff. | [Report failure](report-failure.jpg) |
| Symptoms | A blank event timestamp triggered native required-field validation. A valid synthetic preview separated the UTC event time from actual entry creation time. Reload cleared the preview and workflow while retaining the section hash. After a report failure, Symptoms and Sleep showed their own synthetic status without the unrelated report error. | [Symptom preview](symptom-preview.jpg), [sleep status](sleep-steady.jpg) |
| Sleep comparison | Both supported schedules used the same 0 to 100 illustration scale. The unsupported schedule returned unavailable. | [Steady evening](sleep-steady.jpg), [later night](sleep-late.jpg), [unsupported](sleep-unavailable.jpg), [phone sleep](mobile-sleep.jpg) |
| Keyboard | Skip to content focused main without changing the Forecast hash. Native section links moved focus to the heading. A focused phone chart responded to ArrowRight within its own scroll region. | Direct interaction and DOM focus observations. |
| Responsive layout | Desktop was inspected at 1440 by 1000. Phone was inspected at 390 by 844. Phone document width and scroll width both measured 375 CSS pixels, with the scrollbar occupying the remaining viewport width. Chart content remained wider within its scroll region. | [Phone forecast](mobile-forecast.jpg), [phone sleep](mobile-sleep.jpg) |

The phone check initially found a page wider than the viewport. The final captures show the correction. Temporary browser viewport overrides were reset after inspection.

## Limits and open gates

All observations, intervals, scores, and curves are hand-authored synthetic examples. No upload, personal data, persistence, API, model execution, calibration, or scientific validation was exercised. Every panel identifies its synthetic or unavailable state. No tests were created, changed, removed, or run.

Another teammate must still reproduce the browser walkthrough. The generated contract handoff and agreement with the backend owner remain pending. Issue #4 stays open until its closure gates are met.
