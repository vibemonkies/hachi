# Design verification

Run: October 11, 2026. App commit: `1aab246`, after `c090123`.

## Environment

`npm run build` passed after the final copy commit. Vite preview served the production build on loopback port 5188, owned session 14765, PID 26648. PowerShell confirmed `127.0.0.1` and exact equality between the served HTML and `dist/index.html`. The original coordinator's port and checkout were not used.

CUA drove a separate hidden browser tab through public controls. Screenshots are real JPEG captures at requested viewport sizes 1440 × 1000 and 390 × 844. Scrollbars reduce the latter document client width to 375 pixels. No state injection, personal data, test files, or test suite was used.

## Observations

| Interface exercised | Expected and observed |
| --- | --- |
| All three designs | Load complete history, acknowledge coverage, choose latest UTC cutoff, request report, then open overview and forecast. Each completed successfully. |
| Coverage | 342/360 hourly bins, 14/15 daily resting-HR values, 13/15 nightly sleep values. Report cutoff controls appear after acknowledgment. |
| Forecast | Latest table: 64, 67, 75, 73, 68, 63 bpm. Six timestamps and illustrative bounds match the displayed chart. Analysis opens the exact-value table by default. |
| Cutoff replacement | Changing latest to earlier immediately removed the old report link. A new request produced 62, 64, 72, 70, 66, 61 bpm at the earlier timestamps. |
| Sparse history | Forecast unavailable with a reason. Baseline deviation table explicitly says Missing at `2026-10-07T07:00:00Z`; chart leaves a gap. |
| Empty/access/import failures | Empty state and distinct failure reasons appeared, with appropriate retry controls. |
| Models unavailable | Forecast showed the missing-artifact reason instead of a chart. |
| Report failure | Retry synthetic report appeared. Retrying repeated the deliberate fixture failure. |
| Cancellation | Cancel operation returned to empty; coverage did not appear afterward. |
| Symptoms | Clearing the required event time and submitting produced no preview. Restoring it produced an unsaved preview with separate event and creation timestamps. Leaving and reloading each removed the preview. |
| Sleep | Both supported schedules rendered on the shared 0–100 scale. Fixed assumptions opened through their disclosure. Unsupported schedule rendered an unavailable reason without a curve. |
| Phone layout | Forecast document scrollWidth equaled clientWidth for all three variants. Chart scrolling stayed local. ArrowRight moved the chart scroll position. |
| Navigation | Native links retained the design query and changed section hashes. Back/forward restored matching sections. Skip to content focused `main` without changing the section hash. |

Complete flows were repeated in all three designs. Edge cases used the shared workflow through the task design; symptom and sleep checks also used analysis. This is not a complete permutation of every state and viewport.

## Content review

Removed slogans, section introductions that narrated controls, repeated fixture badges, duplicate symptom headings, and repeated unavailable-output explanations. Remaining descriptions provide interpretation, data-handling consequences, missingness, time conventions, or unavailable reasons.

The skeptical source review found that reports do not analyze an eligible observation prefix. They select hand-authored bundles by scenario and cutoff. UI copy now states that fact. Import-wide coverage counts are not presented as analyzed inputs. No scientific accuracy or model execution was verified.

The React review found one shared reducer, stable component definitions, native labeled controls, stable list keys, and direct imports. No added dependencies or performance claim. Build checks include TypeScript compilation.

## Limits

No event-specific judging rubric or usability study was available. Reduced-motion emulation, a screen-reader session, actual uploads, backend contracts, clinical validity, and another teammate's walkthrough remain unverified. Issue #4's external review gates remain open.

## Gallery

| Composition | Overview | Forecast | Phone forecast |
| --- | --- | --- | --- |
| Task | [Capture](evidence/task-overview-desktop.jpg) | [Capture](evidence/task-forecast-desktop.jpg) | [Capture](evidence/task-forecast-phone.jpg) |
| Summary | [Capture](evidence/summary-overview-desktop.jpg) | [Capture](evidence/summary-forecast-desktop.jpg) | [Capture](evidence/summary-forecast-phone.jpg) |
| Analysis | [Capture](evidence/analysis-overview-desktop.jpg) | [Capture](evidence/analysis-forecast-desktop.jpg) | [Capture](evidence/analysis-forecast-phone.jpg) |

Additional captures cover each desktop coverage view, sparse deviation, symptoms, and sleep. The reusable [verification skill](../../../.agents/skills/verify-hachi/SKILL.md) documents launch, doctor, controls, evidence, and owned cleanup.

Cleanup completed: owned tab closed, viewport override reset, preview session interrupted, no listener remained on port 5188, and all 16 screenshots remained on disk.
