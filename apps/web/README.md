# Hachi fixture workspace

A local React, Vite, and TypeScript interface for the import, coverage, and report workflow. Every observation and output is synthetic. No model runs, personal records, uploads, persistence, or API integration are implemented.

## Run locally

Use Node.js 22.14.0 and npm 11.6.0. Dependencies and the lockfile belong exclusively to this directory.

```powershell
cd apps/web
npm ci
npm run dev
```

Open the local URL printed by Vite, normally `http://127.0.0.1:5173`. The development server binds to loopback. To build and serve the production artifact, run the following commands separately.

```powershell
npm run build
npm run preview
```

The production artifact is `dist`. Inter is bundled from the pinned `@fontsource/inter` package under its SIL Open Font License. The package includes its license. Fonts and application assets are local. There are no remote fonts or application network requests at runtime.

## Explore the workflow

1. Choose Complete history and load the synthetic history. The demonstration delay is one second. Duplicate loads are disabled while pending. Cancel operation cancels the single App-owned timer.
2. Review counts, missingness, units, and import period. Acknowledge coverage before choosing a report cutoff.
3. Select one of the two named explicit UTC cutoff examples. Request a synthetic report, then open Overview, Forecast, or Anomaly monitor.
4. Change the cutoff in Import & coverage. The previous report is removed immediately. Request again to display the distinct static bundle for the new cutoff.
5. Use native section links and browser back/forward. The hash selects the section. Reload retains the section URL but clears all workflow state and previews.

Scenario controls expose Complete history, Empty observations, Sparse history, Access failure, Import failure, Models unavailable, and Report failure. Empty history has no numeric substitute. Sparse history has explicit missing counts, an unavailable forecast, and a missing anomaly point. Access and import failures offer retry. Report failure offers retry at the same cutoff. Failure fixtures intentionally fail again until a different history is loaded. Reset clears the workflow and cancels pending completion.

Symptoms accepts only a synthetic preset symptom, severity, and bounded example event timestamp. The native datetime field is explicitly interpreted as UTC. The preview shows event time separately from actual entry creation time. It remains unsaved in component memory and clears on leaving the section or reloading. Do not enter real personal data.

Sleep comparison selects named static examples with bedtime, wake time, wake date, time zone, and fixed prior sleep, caffeine, and light assumptions. Both example curves share a 0 to 100 illustration scale. The unsupported schedule returns unavailable. No equations or personalized predictions run.

## Evidence limits

Forecast values, intervals, baseline scores, and sleep curves are hand-authored illustrations. The forecast displays six selected hourly bins within a 24-hour horizon, not a complete 24-bin backend result. Intervals are illustrative and uncalibrated. Import-wide coverage counts are not cutoff-specific counts. Each report selects a static cutoff-specific bundle; values are never relabeled as a different cutoff. Missing values remain missing.

The anomaly score illustrates absolute standardized deviation from an earlier historical baseline. It is not an illness probability. No alert threshold or measured alert burden is claimed. Illness onset and recovery remain unavailable with evidence requirements. Sleep indices have no measured scale or validated accuracy.

## Code ownership and integration

`src/workflow.ts` owns UI presentation shapes and allowed transitions. These are fixture types, not authoritative wire schemas. `src/fixtures.ts` owns all synthetic bundles. `src/App.tsx` owns the reducer, hash navigation, focus, announcements, and one cancellable demonstration timer. `src/sections.tsx` owns concrete forms and six section views. `src/components.tsx` owns the SVG plot and equivalent data table. The direct call chain is App to section to workflow or fixture. No router, context provider, external state library, job service, or operation-ID system is needed for one pending operation.

The generated-type handoff from issues #3 and #16 is **PENDING**. Follow `../../docs/CONTRACTS.md` and `../../docs/PRODUCT.md`. A future single adapter must import generated DTOs, validate and normalize real responses into presentation shapes, and replace fixture selection and the timer with the actual import/report lifecycle. Backend ownership agreement has not been recorded. Real consent, authorization, uploads, persistence, polling, deletion, artifact compatibility, and API failures belong to later work. Revisit state requirements against actual contracts before integrating.

## Verification and remaining gate

`npm ci` and `npm run build` passed with Node 22.14.0, npm 11.6.0, TypeScript 7.0.2, and Vite 8.3.4. Vite transformed 23 modules and emitted the local asset bundle. The coordinator exercised the rendered workflow, error fixtures, cutoff changes, keyboard controls, symptom previews, and sleep examples. Production preview checks covered desktop and phone layouts. See the [browser observations and screenshots](evidence/README.md). No tests were created, modified, removed, or run.

Issue #4 closure still requires another teammate to complete the browser walkthrough. Build success and coordinator review do not replace that gate. Backend agreement, real inference, and predictive validation remain pending.
