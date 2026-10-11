# #21 preparation, not case acceptance

This implements a private receipt workflow and a generated-data rehearsal only.
The held-out Apple export and illness timeline are **not available**. Processing
and presentation consent, accepted #20 selection/calibration, and the actual
selected artifact have not been supplied. #21 stays open. Every real-mode
operation is refused, including a case with processing metadata and a
`final_test_authorized=false` freeze. No accepted future handoff schema exists;
this package does not invent one or turn a boolean into permission to score.

## Caller and local metadata

Use the existing `ReportResult`, `ArtifactRef`, and Apple `HourlyFeature` shapes.
The new types describe local receipt metadata only; no prediction interface,
model fitting, API, GPU, or importer implementation is added.

The caller is `python -m hachi.evaluation.case_study` (also available through
`scripts/case_study/receipt.py`). It performs these operations:

1. `preregister`: validate a private `Prespecification`, verify pinned documents
   and the source snapshot, create an exclusive private bundle, and return its
   receipt checksum to the external holder.
2. `seal`: accept existing canonical results for **every** declared task at
   every 72/48/24-hour cutoff and healthy comparison end. Missing, error and
   unavailable outcomes must be retained. Save their bytes and a receipt before
   the holder opens the tail; return the receipt checksum externally.
3. `reveal`: require both externally retained checksums, unchanged documents,
   unchanged original source/model, and increasing saved receipt times. Record
   the sealed timeline's hash in a reveal receipt. This records the handoff;
   it does not expose raw labels or compute clinical results.
4. `verify`: read back all three stages against externally retained checksums;
   emit only source-bound aggregate counts and honest unavailable status.

`Prespecification` contains separate processing/presentation consent status,
private document references and recorded consent times; Justin's data-holder
role; a private UTC onset uncertainty interval and sealed timeline reference;
exact UTC cutoffs computed from the **lower** onset bound minus 72, 48 and 24
hours; ordered prechosen healthy periods finishing before the earliest case
cutoff; and required tasks. Comparison predictions use each period's end.
All cutoffs are retained; onset uncertainty remains an interval rather than a
selected best-looking date. Timeline metadata is an outcome, never an earlier
predictor.

The original system pins name the canonical artifact identity plus separate
source, model, configuration, feature-source, compatibility and freeze document
checksums. Artifact bundle checksums and model-document checksums are distinct
identities. The source snapshot hashes every `src/hachi/**/*.py`, the local CLI
scripts, `pyproject.toml` and `uv.lock`, plus the exact producing Git commit.
Any subsequent source or commit change requires an independently reconciled
handoff; it cannot silently reuse a receipt from an earlier system.

## Reproduce the generated lifecycle

From this isolated worktree, use a separate environment/cache and a new output
directory outside Git. The output's parent must already exist. For example:

```sh
UV_PROJECT_ENVIRONMENT="$PWD/.venv-case-study" \
UV_CACHE_DIR="$PWD/.cache/uv-case-study" uv sync --locked
mkdir -m 700 /tmp/hachi-case-preparation-NavyDune
.venv-case-study/bin/python scripts/case_study/receipt.py synthetic-proof \
  --repo "$PWD" --output /tmp/hachi-case-preparation-NavyDune/generated-001
.venv-case-study/bin/pytest tests/evaluation/case_study
.venv-case-study/bin/ruff check scripts/case_study
```

Use a fresh output name; the caller refuses overwrite. Outputs are exclusive
0700 directories and single-link regular 0600 files, flushed before receipt
hashes return. Inputs must also be private and cannot use symlinks or hardlinks.
Interrupted stages stay incomplete; there is no rewrite/reseal recovery command.
Retain the returned prespecification and sealing hashes with the independent
holder **before** the next step. `synthetic-proof.json` saves them locally for
rehearsal readback only; this is not independent real-case custody.

The generated caller creates fictional consent/timeline/model documents and
eight unavailable results (two tasks at three illness cutoffs plus one healthy
comparison). No clinical probabilities are invented. It proves refusal of
reveal before sealing, real-mode use of the false freeze, posthoc cutoff omission,
resealing, repeat reveal and sealing after reveal. Tests additionally challenge
model/config/feature/timeline/consent/source/commit changes, altered external pins,
clock regression, timestamps, result identity and storage permissions.

The raw-parser seam generates six XML records with known values: five accepted
records and one duplicate; two records visible at the cutoff; one source; native
units reconciled. Future-created records, future events and unfinished sleep are
excluded. The canonical Apple hour-end feature stays identical after a later
tail becomes visible. This proves the generated transport/availability seam,
not parser acceptance on a real export, physiological model accuracy, fitting
normalization/baseline causality, or cross-device source compatibility.

## Real integration remains gated

Justin's side must obtain explicit human processing permission covering the
held-out retrospective use, named storage/access/retention, and separate
aggregate presentation permission. Justin records the dataset policy in
`configs/datasets/personal-apple-export.toml`, receives the actual export, and
holds future measurements/labels and the actual onset/recovery timeline.
CoffeeCoder, the accountable #21 assignee, must agree to the protocol and reveal
procedure on #21. #20's owner/parent must deliver scientific acceptance, the
exact selected artifact/config/source/source-profile and reproduced inference;
the current blocked false freeze cannot satisfy that gate. Real integration
requires a later scoped implementation after this handoff, not an input flag.

Before any actual case, reconcile parser record buckets, sources, units, coverage
and representative aggregates privately. Apply event-end **and** creation-time
availability before model normalization, personal baselines and every predictor
transform; completed sleep summaries must be available by cutoff. Use exact
original feature policy and model compatibility rather than relabeling native
Apple data as PMData. Keep future measurements sealed and prove tail-invariance
through the actual selected model path. Nothing here authorizes access, GPU
transport or retention. No real or friend case is used for tuning.

## Evidence and limits

UTC capture times are observed from the process's system clock, with no caller
override. Saved hash-pinned timestamps and chronology checks reject mutation or
regression they can observe. They are **not secure timestamp attestation** and
cannot prevent an owner controlling the machine from fabricating a wholly new
bundle, changing the OS clock, or falsely claiming an external handoff. Only the
independent holder's retained hashes/custody can support that part of acceptance.

No raw records, identifiers, case dates, predictions or weights belong in Git,
mail, GitHub or presentation assets. The CLI sanitizes validation/refusal output.
Private receipts are not a public report: presentation consent is independent
of processing and does not authorize automatic publication. The generated proof
has no real person or presentation permission claim.

The eventual aggregate report must retain successful and failed alerts, all
cutoffs/comparisons, missingness, lead-time intervals and unavailable outputs.
A one-person retrospective case cannot establish population accuracy or make an
uncalibrated physiological forecast an illness detector. Without accepted
clinical outputs, that capability remains unavailable.
