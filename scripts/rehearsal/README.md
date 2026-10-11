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
`private-results/`; saving it does not implement or prove offline replay.

## Browser integration and honest gates

Build the exact reviewed #17 source in this same isolated worktree after its owner
publishes it. Set its documented API origin to `http://127.0.0.1:8720`. Run `npm ci`
in `apps/web` with an owned npm cache, then `npm run build`; serve `dist` with Vite
preview on loopback port 5180 and `--strictPort`. Record web commit, build SHA,
API `/healthz` Git SHA and artifact pin. Check served index bytes against `dist`.

Use T3 `preview_status`, `preview_open`, snapshots and native controls. Screenshots
and snapshots must contain only a clearly labeled synthetic fixture or permitted
sanitized demo. **Do not take snapshots/screenshots of real participant charts or
log raw DOM/network data.** Compare real chart/table/API values privately and emit
only equality/counts and public artifact identities. Include units, data mode,
quality and point-only absence of an interval band in the comparison. Do not
rename a fixture into a real result or inject a result into UI state.

Current main's fixture workspace is separate evidence. An admitted dataset
snapshot can produce an actual PMData report; an Apple upload with the current
hourly-feature artifact is unavailable. Neither alone proves real
upload → report → chart. The real browser path depends on #17's implementation;
check-ins on #18, safe demo/storage on #19, final artifact selection on #20,
separately consented late case on #21. #15's sleep scenario and clinical #13/#14
also retain their own acceptance gates. Record each unavailable/failing state
honestly. Do not open test, tune on the friend case, or create consent/export.

Offline replay must come from a saved **real** result, with visible replay mode,
recorded timestamp and artifact/model identity, and pass the same numeric
comparison with networking unavailable. There is no offline UI replay on current
main; this remains an explicit gate rather than a synthetic fallback.

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
