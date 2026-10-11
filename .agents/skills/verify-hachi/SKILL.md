---
name: verify-hachi
description: Verify Hachi's synthetic web workspace through its real browser controls, including import, reports, symptoms, sleep, and responsive navigation. Use after UI changes or to reproduce a walkthrough.
---

# Verify Hachi

This verifies the fixture interface in `apps/web`, not backend integration or scientific accuracy. Read [the feature map](features/README.md) and select the scope before driving. A full walkthrough covers every mapped entry and scenario.

## Launch

From the repository root, record `git rev-parse HEAD` and `git status --short`. Use Node >=22.14.0. Run these PowerShell commands separately:

```powershell
Set-Location apps/web
npm ci
npm run build
node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 5187 --strictPort
```

Keep the final command in an owned exec session and retain its session ID. Readiness is Vite's `http://127.0.0.1:5187/` line. No credentials, environment variables, seed service, or database are needed. An occupied port is a failed launch: choose another unused port consistently, never stop its owner. Separate ports and browser tabs isolate in-memory state. Do not double-drive a user's tab. Do not install while another server holds this checkout's native dependencies; use another checkout or stop only your owned server first.

## Doctor

Read-only, from `apps/web`:

```powershell
$hachiListener = Get-NetTCPConnection -LocalPort 5187 -State Listen
$hachiListener | Select-Object LocalAddress,LocalPort,OwningProcess
Get-CimInstance Win32_Process -Filter "ProcessId = $($hachiListener.OwningProcess)" | Select-Object ProcessId,CommandLine
$hachiPage = (Invoke-WebRequest http://127.0.0.1:5187/).Content
$hachiPage -ceq (Get-Content dist/index.html -Raw)
```

Require loopback, the PID belonging to the session just launched, a Vite preview command, and `True` for the served build comparison. Correlate its build with the recorded commit and dirty files. If ownership cannot be established, do not drive or kill the listener. Re-run doctor whenever the page looks stale or fails to connect.

## Drive

Use the available CUA browser harness. On a fresh CUA runtime, select a browser with `await cua.getBrowser({id:'iab'})` alone, then read the returned documentation. Create a new hidden tab for `http://127.0.0.1:5187/`. Inspect its DOM snapshot before choosing selectors. Follow the harness documentation if APIs differ.

The actual import path is:

```javascript
await tab.playwright.getByLabel('Demonstration scenario', {exact:true}).selectOption({label:'Complete history'});
await tab.playwright.getByRole('button', {name:'Load synthetic history',exact:true}).click();
```

Inspect the pending state immediately, then wait for `I have reviewed the coverage` to become visible through the harness's locator wait. Click it; select `October 10, 07:00 UTC · latest fixture` with `getByLabel('Explicit UTC cutoff',{exact:true}).selectOption({label:...})`; click `Request synthetic report`. Observe `Synthetic report ready.` before navigating. Scope section links to `getByRole('navigation',{name:'Workspace sections'})` and use name regexes such as `/Forecast/`: desktop prefixes disappear at narrower widths. Never use internal state setters or evaluate mutations. Browser evaluation is only for read-only DOM observations, such as focus and scroll dimensions.

## Evidence

Write each run under `apps/web/evidence/<unique-run-name>/`. Record the commit, dirty files, build result, doctor PID/build comparison, actions in order, resulting status text, discrepancies, and limitations. Capture before/action/result DOM snapshots plus screenshots of meaningful states. Save browser screenshot bytes using the CUA runtime's filesystem API; do not fabricate screenshots.

Exercise controls and native navigation. No test-only endpoints, state injection, or added mocks are needed: fixtures are the actual current product. Verify the claimed absence of persistence by leaving/reloading Symptoms and observing the preview disappear; reload also clears the workflow. Source inspection supports the absence of uploads and API calls, but does not prove a future backend. Never enter personal data. Compare charts to their exact-value tables, including missing values. Inspect desktop and 390 by 844 layouts, keyboard focus, local scrolling, synthetic disclosures, and common comparison scales. Record anything not exercised. Existing [walkthrough evidence](../../../apps/web/evidence/README.md) is prior evidence, not a substitute for the requested fresh scope.

## Cleanup

Close only the tab created for this run and reset any viewport override you set. Stop only the retained exec session using its interrupt/termination control; never kill by process name. Confirm port 5187 has no listener belonging to that session. Confirm the run directory and screenshot files still exist. Evidence is retained and committed when appropriate. If a launch fails before creating a session, no process cleanup is needed; inspect the error before retrying.

## Helpers

No helper scripts or added dependencies are shipped. The repo's `npm run build`, Vite preview CLI, PowerShell doctor, and CUA browser controls are sufficient. Do not create or modify tests as part of this workflow. Use `$maintain-verification-skill` when controls or feature scope change.
