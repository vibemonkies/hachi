# Hachi web client

The React and Vite client uploads Apple Health exports, opens an existing API subject, reviews coverage at a UTC cutoff, and displays API forecast, anomaly, check-in, and schedule-comparison responses. It does not create report values in the browser.

## Configure the API

The development and preview servers proxy `/v1` and `/healthz` to `http://127.0.0.1:8717`, and `/replay` to `http://127.0.0.1:5180`. Set `VITE_HACHI_API_PROXY_TARGET` or `VITE_HACHI_REPLAY_PROXY_TARGET` in the Vite environment to use different upstreams. Replay requests stay same-origin in the browser and use a separate proxy target. If the web server itself uses port 5180, set `VITE_HACHI_REPLAY_PROXY_TARGET` to the replay provider's separately coordinated port to avoid proxying back to Vite. Set `VITE_HACHI_API_BASE_URL` only when the browser should call a separately reachable API origin directly and that API allows the page's origin.

The API base setting is shared by import, coverage, reports, check-ins, and schedule comparisons. Saved replay always uses the same-origin `/replay/report` route. Subject IDs are entered explicitly; the app has no subject-discovery endpoint and never manufactures an import to open an existing subject.

## Run locally

Use Node.js 22.14.0 or later.

```powershell
cd apps/web
npm ci
npm run dev
```

Open the loopback URL printed by Vite. To create and serve the production client, run:

```powershell
npm run build
npm run preview
```

`npm run build` runs TypeScript compilation followed by the Vite production build. It does not run tests.

## User flows and limits

- **Import:** choose the export, pseudonymous subject ID, time zone, and source mode explicitly. The API validates and imports the file, then the UI polls status and loads coverage.
- **Existing subject:** enter an already available subject ID. The UI reads its coverage directly; no import ID is invented.
- **Reports:** review source coverage, units, gaps and task support, choose an exact UTC cutoff, and request forecast and anomaly reports. Point-only results have no interval band; unavailable reasons and API warnings remain visible.
- **Check-ins:** Symptoms reads and writes saved observations for the selected subject through the API. It keeps event time separate from entry time and supports the API's correction and deletion behavior.
- **Schedule comparison:** Sleep submits two schedules and explicit assumptions to the API. PR #101 merged the conditional simulator source; its handoff asks Justin/WindyTrout to integrate it through the API seam. No successful scenario response was observed locally, and the source merge alone does not establish API serving.
- **Offline replay:** load the saved report from `/replay/report`. It displays the saved data mode, source report ID, and replay timestamp. A missing replay fails visibly and never triggers a live report request.

Apple Health input is not automatically admitted by a forecast artifact. The current PMData artifacts return `NO_ARTIFACT_FOR_TASK` for Apple input unless an operator has explicitly admitted an artifact. Admitted transfer is labeled unvalidated; sparse histories may abstain with `INSUFFICIENT_HISTORY`. Long reports remain in the running state while the client polls.

Real Apple export access, per-artifact source admission, model validation, and the completed real import-to-chart/API-value walkthrough remain separate acceptance gates. PR #101's simulator source merge does not establish API serving or complete #15, #16, #18, or #20 acceptance. Saved-response replay is a separate source with its own replay timestamp and provenance; it must never fall through to a live request.
