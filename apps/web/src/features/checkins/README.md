# Interactive check-ins and schedule comparisons (#18)

`Checkins` and `ScenarioComparison` consume the generated Hachi TypeScript contracts
and actual HTTP API. They are independent of the import/report workflow and accept
an operator-configured `apiBaseUrl` and selected `subjectId`:

```tsx
<Checkins subjectId={subjectId} apiBaseUrl={apiBaseUrl} asOf={utcCutoff} />
<ScenarioComparison subjectId={subjectId} apiBaseUrl={apiBaseUrl} />
```

Import the components into the coordinated `SectionView` symptoms/sleep branches.
No browser storage persists labels. Every history refresh reads the API. A subject
or API change remounts the feature, so one subject's draft/report cannot be shown
as another's. A missing `asOf` means the recovery button uses the current instant;
an explicit cutoff is displayed and sent unchanged.

## Recorded values

Seven supported entry kinds: symptom onset, symptom status over a period,
resolution linked to a recorded onset, pathogen/test method/result with collection
uncertainty, KSS 1–9 (higher = sleepier), measured PVT duration/trials/mean reaction
time/lapses, and optional schema-supported confounders. No PVT is administered and
no measurements are fabricated.

Event inputs are **explicit UTC clock times**, not the browser's local timezone.
The form validates the calendar date and converts these clocks to ISO UTC.
`entered_at_utc` is independently created at save time. Unchanged failed requests
retain their entry id and entry timestamp, so retry is idempotent. API field issues
are shown without logging requests, identifiers, labels or response bodies.

Corrections follow WindyTrout's agreed #18 interface: a new entry id and honest
correction entry time, with `supersedes` naming the current version. All versions
are fetched separately for episode-root lookup. Resolution and recovery requests
use the original onset id. Delete confirms the exact entry id and removes its
whole version chain; the API protects referenced onsets and invalidates affected
clinical reports. The correction/delete controls activate only when the committed
generated schema contains `supersedes`; they are unavailable against the earlier
immutable-entry API. Final acceptance requires the actual coordinated API revision,
not that schema check alone.

## Outputs and limitations

An unresolved onset says that resolution follow-up has not been recorded; it is
not labeled recovered. Recovery requests go through report-job polling. Successful
responses must match the requested episode before their survival probabilities and
supported follow-up are displayed. Unavailable/error responses show the API's
specific requirements/reason. No recovery distribution is created in the browser.

Schedule A/B have separate local bedtime and wake date/time, one IANA timezone,
explicit prior sleep, caffeine (`none` / `not_modeled`) and light exposure
(`not_modeled`). The API checks DST and elapsed duration. Responses render their
actual status, submitted/computed assumptions, data mode, scale, curves, exact
value tables and provenance. Simulation never claims personal energy accuracy.
Validated predictions require the response's measured-validation evidence.

## Checks

```sh
node --experimental-strip-types --test apps/web/tests/checkins.test.mjs
npm run build --prefix apps/web
uv run --locked --extra api pytest tests/api/test_subjects.py
```

The Node checks cover date/time separation, impossible dates, explicit symptom
absence, linked resolution, test uncertainty, KSS/PVT bounds, scenario assumptions,
correction event-field round trips and episode-chain safety. Browser acceptance
must additionally exercise save/read-back/reload, correction/deletion, invalid
inputs, keyboard/mobile use and the actual report/scenario endpoints.

This feature checkpoint does not close #18. App-route integration belongs to the
active #17 worker, stored correction/deletion depends on the coordinated #16 API,
and computed comparison curves depend on #15 publication/wiring. Supported
illness/recovery/alertness claims retain their own real-label/evaluation gates.
