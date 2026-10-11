# Verification skill execution

Executed against commit `33ab871` on October 10, 2026 (America/Los_Angeles), with a fresh production build. No app source was changed. `npm run build` passed. An initial launch from the repository root failed because Vite resolves dist relative to cwd; the generated skill explicitly enters apps/web and the corrected launch succeeded.

## Lifecycle and observations

1. Launched an owned Vite preview session on loopback 5187, separate from the existing 5175 instance. Doctor identified PID 21196, its absolute checkout Vite command, and an exact match between served HTML and dist/index.html (`True`).
2. Opened a separate hidden CUA tab. Clicked Load synthetic history; observed 342/360, 14/15, and 13/15 coverage counts. Acknowledged coverage; Request synthetic report was disabled before choosing a cutoff.
3. Selected October 10, 07:00 UTC and requested a report. Observed Synthetic report ready. Opened Forecast and expanded exact values: 64, 67, 75, 73, 68, 63 bpm, with UTC timestamps and illustrative bounds. Captured [forecast](forecast.png).
4. Inspected at 390 by 844. DOM document clientWidth and scrollWidth both equaled 390. The chart and table retained internal horizontal scrolling. Labels, units, uncalibrated interval text, and synthetic disclosure remained readable. Captured [phone forecast](phone-forecast.png). The visible Skip to content overlay in this capture is the harness hover state, not persistent page content.
5. Opened Symptoms and submitted the synthetic 2026-10-09T12:00 event. The preview separated event UTC time from actual creation time and stated unsaved memory. Captured [symptoms](symptoms.png). Reload retained Symptoms but removed the preview and reset the workflow.
6. Opened Sleep comparison; inspected explicit timezone, wake date, fixed assumptions, and 0 to 100 illustration scale. Captured [sleep](sleep.png). Selected later-night and observed 00:30; selected unsupported and observed Schedule unavailable with no chart. Captured [unsupported](sleep-unavailable.png).
7. Reset the viewport, closed only the created tab, and interrupted the owned preview session. Port 5187 no longer had a listener. All five screenshot files remained on disk after cleanup.

## Scope and design assessment

The generated launch/doctor/drive/evidence/cleanup recipe was executed successfully. Skill structural validation passed. The semantic review corrected a discovered inaccurate symptom instruction: its event time starts prefilled, so required-field verification must first clear it. Local links and all five feature-map shapes were checked. No helper code or tests were added or run.

The design review used the design skill's typography, geometry, and interaction guidance. The existing quiet palette, local Inter font, aligned controls, explicit chart units, and shared sleep scale support interpretation. Phone page overflow was absent. No further visual changes were justified by this run.

This fresh pass covers import success, latest report values, symptom reload, sleep states, and narrow layout. The preceding [coordinator walkthrough](../README.md) supplies the broader observations for cancellation, failure fixtures, sparse gaps, earlier cutoff, keyboard focus/scroll, and desktop 1440 by 1000. Those were not rerun in this fresh pass. Reduced-motion emulation was not exercised. All results remain synthetic; backend integration and predictive validation are unverified. The separate teammate walkthrough and backend-owner agreement remain open gates for issue #4.
