# Final evaluation packet preparation

This directory contains preparation guidance and a model-card template. It contains
no final scores, winner, completed-task claim, or authorization to open outer test.
Full #20 acceptance still requires #12, #13, #14 and #15 evidence.

`hachi.evaluation.finalization` reads existing immutable private #7 packets and #9
model receipts. It never imports executable serialized models, fits candidates,
scores test participants, changes splits, or selects a winner. Source receipts
are checked against the producing Git commit, so a newer implementation does not
silently replace historical provenance. Artifact-only dependencies must be pinned
separately; paired #9 packets refer to their original baseline run's artifacts.

## Development verification

Run in an isolated environment with its own cache. Use the **published/approved**
index digest, not a fresh checksum of a possibly altered input. Private bundle paths
are operator inputs, and outputs are new private directories with 0700/0600 modes.

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv run python -I -m hachi.evaluation.finalization development \
  --bundle /approved/private/runs/primary-validation \
  --expected-index-sha256 APPROVED_INDEX_SHA256 \
  --output /approved/private/runs/new-development-receipt

UV_CACHE_DIR="$PWD/.cache/uv" uv run python scripts/evaluation/final_packet.py development \
  --bundle /approved/private/runs/paired-validation \
  --expected-index-sha256 APPROVED_PAIRED_INDEX_SHA256 \
  --artifact-bundle /approved/private/runs/primary-validation \
  --artifact-index-sha256 APPROVED_INDEX_SHA256 \
  --output /approved/private/runs/new-paired-receipt
```

Verification covers all indexed bytes and refuses extra/missing files, unsafe paths
and symlinks. Forecast packets must bind clean code, real mode, exact configuration,
task, snapshot, seed, sealed split, validation-only origin schedule, scored support,
metric definition and source identity. Baseline, zero-shot univariate Chronos and
#11 encoder heads resolve their owner's existing receipt and model schema.
Chronos binds checkpoint/runtime/protocol; encoder heads bind original experiment,
configuration, features, fit cutoff and embedding-table hashes. Source scopes follow
the producing owner format. The encoder `ProtocolRef` pins original config-file
bytes; these are checked at the producing commit and parsed against the canonical
saved protocol, whose JSON digest may differ. Paired packets bind both evaluations and
the same split/origin schedule. Prediction-origin coverage and scored support
must reconcile; exported fit time must match the evaluator's training cutoff.
It checks identity and internal consistency;
it does not recompute scientific metrics from source labels or certify source access.

The aggregate `development.json` contains digests and support counts, without
participant IDs or predictions. Physiology development evidence is explicitly
separate from final selection. The Stanford anomaly adapter separately verifies the
producer's existing protocol/artifact/whole-person folds and reconciles its metrics
against saved observed-control counts. It retains the floating-clock convention and
limited coverage; it does not produce illness probabilities. Use `--kind stanford-burden`
with the approved #9 packet index. Illness, recovery and measured alertness stay
blocked until their own adapters and evidence land. The CLI emits aggregate status
only, including on failures.

The initial #14 recovery packet produced at `af7e26b` is superseded pending the
owner's corrected source-bound rerun: its censoring could overstate observed
event-free follow-up, and report-wide totals could expose sealed-test outcome
counts by subtraction. Preserve it only as audit provenance, never as accepted
final evidence. No recovery adapter in this release accepts that packet.

## Assemble model-card development evidence

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv run python -I -m hachi.evaluation.finalization evidence \
  --bundle /approved/private/runs/development \
  --expected-index-sha256 APPROVED_INDEX_SHA256 \
  --output /approved/private/runs/new-aggregate-evidence
```

Artifact-only dependencies use the same separately pinned arguments as development
verification. The resulting `evidence.json` contains model/code/environment/data/
config/artifact identities, counts, overlap disclosures, saved metric aggregates
and paired differences. Equivalent repeated runs count once. Canonical aggregation
refuses overlapping scored participants; different model/code/config/environment/
data/seed identities remain separate. No participant rows or coefficients are emitted.

This is validation-only evidence with `selection_status: pending_owner_selection`,
`inference_reproduced: false`, `runtime_measurements: not_assembled` and no test
authority. It cannot fill final held-out fields or establish missingness/device
analysis. HTTP and warm model-only latency remain separate measurement scopes.
Fine-tuned or extended-context Chronos exports and #12 ridge heads require their
actual owner fit/context/export handoffs before adapters can accept them.

## Freeze exact decisions

The internal `FreezeRequest` names hashed documents for development receipts,
protocol, selection rule/log, experiment budgets, preprocessing, thresholds,
calibration, and selected canonical run/split/config. All five required tasks must
retain explicit support states. An explicit decision such as no calibration must
be a nonempty document; missing or empty decisions fail.

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv run python -I -m hachi.evaluation.finalization freeze \
  --root /approved/private/freeze-inputs \
  --request /approved/private/freeze-inputs/request.json \
  --output /approved/private/runs/new-decision-freeze
```

This consumes the merged `hachi.models.ensemble.selection.SelectionRule`/`SelectionLog`
and `judge` from #12; an older checkout missing them refuses with the named dependency.
It checks the recorded incumbent chain and gates against the owner's rule; it
does not invent a rule or choose a different model. It preserves exact selection,
calibration and manifest hashes, plus the decision documents, in exclusive output.
The selected split must retain the development/test membership digests from the
verified input, active outer fold, exclusions and every shared operational
protocol field. Candidate-specific pretrained-overlap disclosures may differ.
Changing thresholds, calibration, selection, or preprocessing
requires a new freeze, never mutation of an existing one.

Supported transitions are `development_verified` → `decisions_frozen`.
Both have `final_test_authorized: false`. Decision freezing remains
`blocked_pending_acceptance`: task acceptance, selection-to-packet linkage, fresh
selected-artifact inference reproduction, independent review, and the parent's
coordinated test opening are still required. There is no test-opening command.
The parent must verify actual delivered prerequisites before authorizing the later
final-test action; neither a hashed declaration nor a green check substitutes for it.
The #12 owner will supply direct selection-step-to-comparison/evaluation packet hash
links and selected export receipts. Selected #12 ridge/adapted export integration and
fresh selected inference remain pending those actual exports. #10 score packets
with null export references can establish development evidence without establishing
a served final artifact.

Read back any emitted packet with its approved index digest:

```sh
UV_CACHE_DIR="$PWD/.cache/uv" uv run python -I -m hachi.evaluation.finalization verify \
  --bundle /approved/private/runs/new-decision-freeze \
  --expected-index-sha256 APPROVED_OUTPUT_INDEX_SHA256
```

## Scientific and privacy boundaries

Clinical phase 1 is a floating, shifted local clock represented with `Z`; it is not
actual UTC and cannot establish cross-dataset date alignment. Missing surveys and
unlabeled controls are unknown. Phase 2 supplies no negative/recovery follow-up.
Retrospective episode/outcome metadata are not earlier-cutoff predictors. Simulation
assumptions are distinct from measured alertness; daily fatigue is not hourly truth.
Friend-case tuning and test reopening are outside this tooling's authorized path.

Keep model weights, participant predictions, split memberships and raw data in
approved private storage. The freeze manifest is private even though CLI summaries
and development receipts contain only aggregate fields. Review all public claims
against measured evidence before final publication.
