# Isolated app rehearsal — #22 groundwork

This lane owns `scripts/rehearsal/` and `reports/verification/app-rehearsal/`.
It supplements CoffeeCoder's #17 UI work and WindyTrout's API implementation.
It does not select a final model or close #22. Run only on permitted private local
data; the outer test remains sealed. PMData physiology does not supply clinical
negative labels or prove Apple Watch transfer.

`runtime.py` uses the existing API staging/serving code and the evaluator's
independent inference path. It stages **one** pinned artifact from a frozen
inner-validation packet, checks the admitted snapshot, and creates a fresh private
operator root outside Git. It refuses dirty/uncommitted code and later checkout
changes. Every invocation uses that same root and locked environment. Keep API
8720 and web 5180 reserved for this worker; never stop somebody else's listener.

The default published packet index is
`reports/evaluation/pmdata-hourly-validation/packet-index.json`. Split, origin,
evaluation and protocol hashes must match it, in addition to the packet's own
checksums. Use `--packet-index` only for another reviewed frozen packet index with
the same shape. Rehashing a changed private packet cannot satisfy this gate.

## Prepare and launch

From a fresh isolated checkout, set private local paths. These are shell variables,
not browser inputs. `HACHI_REHEARSAL_ROOT` must not exist yet. Use a new value for
each code revision. The environment and cache must belong to your worker.

```sh
export UV_PROJECT_ENVIRONMENT=/approved/private/runtime/worker22/venv
export UV_CACHE_DIR=/approved/private/runtime/worker22/cache
export HACHI_REHEARSAL_ROOT=/approved/private/runtime/worker22/run-001
export HACHI_REHEARSAL_DATA=/approved/private/data
export HACHI_REHEARSAL_RUN=/approved/private/runs/pmdata-validation
export HACHI_REHEARSAL_MODEL=hourly-last-valid-v1
export HACHI_REHEARSAL_ARTIFACT=hourly-last-valid-v1-141306001b16e168
uv sync --locked --extra api --extra baselines
uv run --locked --extra api --extra baselines python scripts/rehearsal/runtime.py prepare \
  --owner ezzy1630 \
  --runtime-root "$HACHI_REHEARSAL_ROOT" \
  --data-root "$HACHI_REHEARSAL_DATA" \
  --snapshot-id pmdata-features-1-simula-2020-04-24-06606ac2708b \
  --model "$HACHI_REHEARSAL_RUN/outer-0-inner-0/models/$HACHI_REHEARSAL_ARTIFACT" \
  --packet "$HACHI_REHEARSAL_RUN/outer-0-inner-0/evaluations/$HACHI_REHEARSAL_MODEL" \
  --protocol "$HACHI_REHEARSAL_RUN/protocol.json" \
  --api-port 8720 --web-port 5180
uv run --locked --extra api --extra baselines python scripts/rehearsal/runtime.py serve \
  --runtime-root "$HACHI_REHEARSAL_ROOT"
```

Retain the server's owned process/session. The launcher binds loopback and disables
access logs, since API paths and query strings contain participant identifiers.
Do not expose this runtime publicly. The API is an operator-local single-user
service, not a per-subject authorization system. The private operator document
sets workspace, database, artifacts, snapshot, CORS origin and Git identity;
inherited Hachi environment variables cannot redirect those locations.

In another terminal at the same checkout/environment:

```sh
uv run --locked --extra api --extra baselines python scripts/rehearsal/runtime.py check \
  --runtime-root "$HACHI_REHEARSAL_ROOT" > "$HACHI_REHEARSAL_ROOT/evidence.json"
```

Output contains sanitized counts, identities, hashes and discrepancies only.
Check the exit status before using the evidence. No raw exception messages are
printed. Do not publish private operator/configuration files or saved responses.

The check verifies health/code/artifact identity, every frozen validation origin,
exact point sets and values against both packet and fresh evaluator inference,
metric/unit/mode/snapshot, point-only null bounds/coverage, quality coverage, causal
coverage cutoff, and idempotent report retries. Missing API points fail even when
the remaining values match. Unsupported anomaly/illness/recovery tasks retain
explicit unavailable reasons. Separately labeled **synthetic** HTTP checks exercise
an Apple XML import, insufficient coverage, persistent check-in readback, malformed
import and unavailable sleep scenario. These are transport evidence, not real-data
model or clinical evidence. A live response is saved mode 0600 under
`private-results/`; saving alone does not prove replay. The separate consumer and
its rendered verification are described under [Private offline replay](#private-offline-replay).

## Browser integration and honest gates

Build the exact published #17 source in a clean owned review checkout. PR111
`0b58f4e7358a1bcc1f29c036eac98c954a808449` and corrected
`5a422ddb2f1d0dd2a5c4e1003a1c833cf430daca` were exercised with these settings
in both the build and preview shell (later app revisions need fresh evidence):

```sh
export VITE_HACHI_API_BASE_URL=
export VITE_HACHI_API_PROXY_TARGET=http://127.0.0.1:8720
export VITE_HACHI_REPLAY_PROXY_TARGET=http://127.0.0.1:8729
export npm_config_cache=/approved/private/runtime/worker22/npm-cache
# From apps/web in that same source checkout:
npm ci
npm run build
npm run preview -- --host 127.0.0.1 --port 5180 --strictPort
```

The same-origin `/v1` and `/healthz` routes reach the API; `/replay/report` reaches
the separate loopback provider on 8729 with `changeOrigin`, without rewriting.
Run the published `replay.py serve` command below with `--port 8729` when using
the actual app; port 5180 belongs to the web preview. No provider or UI source
override is needed.
Record web commit, build SHA,
API `/healthz` Git SHA and artifact pin. Check served index bytes against `dist`.

Use T3 `preview_status`, `preview_open`, snapshots and native controls. Screenshots
and snapshots must contain only a clearly labeled synthetic fixture or permitted
sanitized demo. **Do not take snapshots/screenshots of real participant charts or
log raw DOM/network data.** Compare real chart/table/API values privately and emit
only equality/counts and public artifact identities. Include units, data mode,
quality and point-only absence of an interval band in the comparison. Do not
rename a fixture into a real result or inject a result into UI state.

Current main's fixture workspace is separate evidence. An admitted dataset
snapshot can produce an actual PMData report. This runbook stages the frozen
PMData comparator without Apple admission, so an Apple upload through that
profile returns `unavailable` / `NO_ARTIFACT_FOR_TASK`. Apple admission is
**per artifact**, not a blanket API limitation: an explicitly admitted profile
uses `apple-hour-end-sealed-native-v1`, retains the model's metric, aggregation
and density gates, and labels successful transfer with `DEVICE_SHIFT` and its
unvalidated rationale. Sparse history can still return `INSUFFICIENT_HISTORY`.
Real personal Apple imports are excluded from shared-GPU models pending an
approved transfer/retention design. See the [API source-admission documentation](../../src/hachi/api/README.md#apple-health-imports)
and [generated CPU-artifact HTTP proof](../../src/hachi/data/apple_health/README.md#generated-http-transport-against-the-original-frozen-cpu-artifact).
That generated proof does not establish real Apple accuracy. The actual PR111 app
existing-PMData-subject → report → chart and private offline replay were exercised
at the pinned head: [source-bound receipts and scope](../../reports/verification/app-rehearsal/README.md#actual-app-runtime-at-pr111-0b58f4e).
One app origin matched 24 points/48 endpoints at each head; the separate API
oracle covers 25 origins/600 points at each head. Generated Apple input exercised
the `0b58f4e` app import/status/
coverage and the truthful unavailable response, not a real Apple case.
#19's storage/demo implementation is accepted; #18's complete integrated states,
#20's selected-artifact parity and #21's separately consented late case remain
gates. #15's sleep scenario and clinical #13/#14
also retain their own acceptance gates. Record each unavailable/failing state
honestly. Do not open test, tune on the friend case, or create consent/export.

## Private offline replay

[PR86](https://github.com/vibemonkies/hachi/pull/86), merged at `91bc669`, delivered
`replay.py`: a versioned private cache, typed Python `ReportProvider` seam,
read-only loopback transport and a dedicated rehearsal viewer. It consumes the
authoritative `ReportJob`/`ReportResult` models, checks the generated contract schema
hash and validates both the original and projected response. It never imports an
inference client or attempts a live fallback. Its [private numeric/time/geometry verification](../../reports/verification/app-rehearsal/README.md#private-replay-consumer-follow-up)
used the saved real response with the live API stopped. That PR delivered the
standalone viewer. The later PR111 app replay proof is separately source-bound
below; neither establishes all #22 gates.

The cache preserves the whole completed original response, with its original
`data_mode` (`real` or `synthetic`), generated time, code, artifact, snapshot,
warnings and quality. Projection sets only `ReplayInfo`. Recording time is when
the cache was saved, not when inference happened. The viewer visibly labels replay,
original mode and both timestamps; point-only forecasts have no interval band or
coverage claim. Unavailable/error results retain their actual reason codes.
The exact report cutoff and canonical `interval_start_utc`/`interval_end_utc` are
visible. Every series uses the same elapsed UTC x domain, with points at interval
midpoints. Hourly requests retain the whole requested horizon, so missing initial,
inter-series and trailing target windows stay blank. A keyboard-focusable table
scrolls locally on small screens. The contract requires contiguous targets within
each series; no unsupported per-point abstention shape is manufactured.

Only private regular files outside Git are accepted, bounded to 16 MiB. Cache files
are created exclusively at mode 0600 under a 0700 parent. Symlinks, public files,
pending jobs, already replayed sources and changed schema are refused. Pin the
whole cache hash from the trusted save receipt separately: embedded checksums are
integrity checks, not proof of source authenticity or permission. Saving a file
alone does not establish that it came from a real admitted run; the API receipt
and frozen packet provide that evidence for the actual rehearsal.

With the owned API stopped, run in the same checkout/environment:

```sh
uv run python scripts/rehearsal/replay.py save \
  --source "$HACHI_REHEARSAL_ROOT/private-results/live-report.json" \
  --cache "$HACHI_REHEARSAL_ROOT/private-results/replay-cache.json" \
  > "$HACHI_REHEARSAL_ROOT/replay-save.json"
# Copy cache_sha256 from this trusted private save receipt into this variable.
export HACHI_REPLAY_SHA=the_exact_cache_sha256
uv run python scripts/rehearsal/replay.py check \
  --cache "$HACHI_REHEARSAL_ROOT/private-results/replay-cache.json" \
  --expected-cache-sha256 "$HACHI_REPLAY_SHA"
uv run python scripts/rehearsal/replay.py serve \
  --cache "$HACHI_REHEARSAL_ROOT/private-results/replay-cache.json" \
  --expected-cache-sha256 "$HACHI_REPLAY_SHA" --port 5180
```

`GET /replay/report` returns the validated projected `ReportJob`; `/` renders it.
Responses use `no-store`, no CORS, a restrictive CSP and no access/error logs.
Missing/corrupt/mismatched caches produce an actionable visible replay error and
HTTP 409, without paths, participant identifiers or validation values. The page
omits subject/report identifiers, but real numeric predictions are still private.
Never snapshot/screenshot a real replay page. Use only aggregate-returning private
DOM/API comparisons. Use a distinctly synthetic cache for browser illustrations.
No browser storage, service worker, mutation route or external asset is used.

For a replay forecast, evaluate the text of `browser_compare.js` (trim its trailing
newline) with T3 `preview_evaluate`, `awaitPromise: true`. It reads the actual
same-origin replay transport and compares rendered SVG geometry/table numbers,
units, quality and provenance; output contains booleans/counts only. Keep it out
of snapshots of private real content. A false `ok` is a failed comparison.
It also checks the exact visible cutoff/interval timestamps and shared UTC geometry.
Generate an explicitly synthetic staggered-window source with
`python scripts/rehearsal/synthetic_replay.py --destination /private/owned/gaps/source.json`,
then use the same save/check/serve path. Its five points and three missing target
windows are a rendered gap regression, not real-data or inference evidence.

This viewer proves the independent consumer path. For Coffee's actual app, open
the existing-subject coverage through its controls, select the private frozen UTC
cutoff, review coverage, request the forecast and open its exact-value table.
Keep private identifiers/times out of tool arguments/output: the observed run
supplied trusted saved-response values locally through ordinary input events,
then used native buttons/navigation; it did not inject report or React state.
Evaluate the trimmed text of `app_compare.js` with T3 `preview_evaluate`,
`awaitPromise: true`. The read-only helper compares actual DOM/table/SVG against
the provider's validated saved response, including exact endpoints, cutoff,
units, rounded quality, artifact/snapshot/code and original mode. On the live
view it also requires the whole live result to equal the saved result after
removing only `ReplayInfo`. It returns counts/booleans or a generic failed gate;
never print raw DOM, responses or exceptions.

Stop only the owned API, verify 8720 has no listener, and load saved replay
through the actual app. Open the exact-value tables and rerun the same helper;
record replay provenance, no live report requests and the absent API listener.
The helper checks interval starts on the app's common cutoff-to-cutoff+24h UTC
domain, unlike the standalone viewer's interval midpoints. It deliberately
requires the original point-only CPU comparator: it is not selected 720-hour
interval-model parity. Use the generated staggered-window cache for gap and
mobile illustrations, and a missing private cache for the visible 409 refusal.
The [broader actual app evidence](../../reports/verification/app-rehearsal/app-runtime-0b58f4e.json)
and [corrected-head live/replay follow-up](../../reports/verification/app-rehearsal/app-runtime-5a422dd.json)
record their paths at each producing head. New source needs a rebuild/relaunch
and fresh comparison; no model selection or outer-test opening is authorized
by this runbook.

## Verification and cleanup

```sh
uv run --locked --extra api --extra baselines python -m unittest discover \
  -s scripts/rehearsal -p 'test_*.py'
uv run --locked --extra api --extra baselines ruff check scripts/rehearsal
uv run --locked --extra api --extra baselines ruff format --check scripts/rehearsal
```

Stop only retained owned service sessions, close your own T3 tabs, and confirm
their listeners are gone. Retain private operator root/evidence for reproduction.
Commit only aggregate evidence and owned tooling. A passing backend rehearsal or
fixture walkthrough is groundwork; full #22 closure needs all acceptance gates.
