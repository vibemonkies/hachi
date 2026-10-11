# #19 private storage and demo evidence

## Complete remote cleanup acceptance follow-up

The required remote privacy tests replace the earlier observed-retention assertions.
The initial PR87 candidate `6b0a7a7` fixed personal-source refusal and surfaced removal
errors but still failed fifteen independent cases: logs/metadata/nested outputs remained,
partial writes were outside the cleanup guard and unexpected exceptions bypassed it.
The updated source `9e2e891` resolves those findings and adds owned-job termination
confirmation before treating unknown SSH/timeout outcomes as cleaned.

Independent tests now require whole-owned-run erasure and sibling preservation on
success, busy/nonzero/timeout/SSH errors, partial writes, read/integrity failures and
unexpected exceptions. Failures in either/both removals must attempt both inventories,
withhold the forecast and surface safe errors. Actual local files and a controlled
late-writer thread verify that unknown termination is explicitly failed, never claimed
complete. SSH command checks confirm quoting/absence checks and marker self-exclusion;
no remote command is executed by these tests.

Actual TCP HTTP checks stage and checksum/code-verify a generated Chronos artifact,
serve generated PMData-layout history, and confirm safe cleanup/termination errors with
no prediction payload. An entirely generated Apple export deliberately classified
`real`, with a synthetic-looking ID and explicitly admitted source profile, is refused
before any remote call. This proves the guard uses resolved source mode rather than IDs,
profile admission or the forecast's synthetic label. Nothing reads or transfers a
human's export. Fixtures stop their own socket service and erase only their generated
roots, including unsealing self-created artifact directories for teardown.

The current complete contract run has 44 independent checks. It uses fake transports
and actual local files/HTTP; the runtime owner's separate generated SSH removal smoke
binds remote execution. No GPU parity/scientific accuracy, participant authentication,
physical-media erasure, real personal transfer or display consent is implied. See the
[runbook](../../../infra/demo/README.md) for failure recovery and personal GPU refusal.

## Correction/concurrency follow-up after PR79/PR76

[corrections-receipt.json](corrections-receipt.json) records the clean checkout
`8ff3d95af114dfc8d4b7d8a061c6ac66bfa09759`, including WindyTrout's merged fix
[PR81](https://github.com/vibemonkies/hachi/pull/81) (`e88b0f8`). Against `84a5cbe`,
six independent TCP cases failed: tombstone-only subject deletion; correction
resurrection after chain erasure; a resolution dangling after onset erasure;
identical observations and cached reports accepted during whole deletion; and a
report published with a stale self-report key. All six pass with PR81. This lane
retains independent tests; it does not duplicate the API owner's implementation.

The focused run passed 27 tests: ten actual TCP checks, seven independent generated
GPU transport/identity boundaries, and ten owner correction regressions. The
production CLI separately passed 37 focused checks with its served Git SHA and
empty model refs pinned, safe logs, isolated private roots and only generated
subjects. It verifies current/all/as-of histories, earlier versus corrected report
keys, chain and tombstone erasure, report invalidation/isolation and ID reuse only
after whole-subject deletion. The CLI and TCP fixtures stop their own service and
remove only disposable state. The original 44-check upload suite and unchanged
private source inspection were retained as historical evidence, not rerun.

The cheap GPU checks invoke no SSH/GPU. They refuse wrong request identity,
duplicated results, request hash, model revision and weights without echoing
submitted values; the transport captures stderr and disables password prompts.
At that historical checkpoint, an in-memory run confirmed a concrete retention limitation: request cleanup
leaves remote prediction/evidence files outside the subject deletion inventory.
Personal GPU use remains gated on explicit source transfer/account consent and
verified remote retention/cleanup, including failures. This is a current privacy
gate, not a request to repeat the model owner's expensive GPU parity work.

The private-roster current-tree/demo scan covered 630 tracked files with zero
findings at the receipt's source commit. Future rendered screenshots/recordings
need separate review. The merged Apple helper supplies neither an approved
per-artifact serving profile nor real-source transfer/UI evidence. Those scoped
follow-ups stay with #16/#18/#21/#22. Source-only work does not imply consent.

## Original upload/storage acceptance checkpoint

[receipt.json](receipt.json) binds sanitized execution evidence to source commit
`809839b` in NobleCat's isolated #19 worktree on MacBook-Air-4.local. The source tree
was clean before the receipt was written. The runtime used its own disposable
workspaces/database/cache/run roots and loopback port 8719; served model refs were
explicitly empty. Only generated subjects were uploaded or deleted.

The three original failures were reproduced before implementation: personal
self-report bytes remained in SQLite/WAL files after deletion; a 422 response echoed
a submitted schedule ID; and an unexpected-error log included a subject URL. The
fixes clear deleted cells and truncate the WAL, sanitize validation messages/unknown
field names, and suppress private URL/query/traceback logging. Fixed-schema built-in
validation rules retain useful messages without copying submitted values.

The real CLI service passed 44 checks, including accepted ZIP/XML imports,
idempotency, job polling, coverage, self-reports, report completion, cross-subject
onset-reference rejection, confirmation, deletion and preservation of another
subject. It rejected traversal/symlink/corrupt ZIPs, external XML entities,
excessive depth/tokens, empty/oversize uploads, foreign Host headers and simple form
writes. A generated fault exercised the production Uvicorn logging filter. No raw
staging files, import directories or personal metadata remained after cleanup, and
generated deleted sentinel bytes were absent from the current database/WAL files.
Service logs were checked privately and only their digest and safe/unsafe result
were saved.

Independent tests found and verified the #16 owner's additional fixes: filesystem
removal failure keeps metadata for retry (PR62), and both identical and changed
uploads during a deletion return 409 (PR65). Streaming bodies are bounded even
without Content-Length. Scan regressions verify that findings exit unsuccessfully
and matched tokens/identifiers are never printed. The launcher itself was run: it
cleared inherited database/owner/model configuration, created a new private root
and isolated database, and reported the pinned commit and empty model refs.

The permitted Stanford phase1 archive's full SHA-256 and private snapshot's
identity/checksums/outcomes passed read-only inspection. Ten files were verified,
with 151 unknown-status, 59 symptom-episode and 36 test-result outcomes. The archive
mode was 0400, snapshot directory 0550, and snapshot files were neither writable
nor world-readable. These modes do not provide isolation from another process
running as the same Unix user. Nothing changed or deleted the source or snapshot.
The clinical clock is shifted floating local time encoded with `Z`, not actual UTC.

Current tracked files and the explicit `infra/demo/` assets are scanned against
credential/private-file patterns and the permitted phase1 participant roster.
The final scan receipt is saved alongside this evidence. It covers the intended
text/code assets, not Git history or OCR of future images/video. Presentation
screenshots remain an explicit rendered-review gate in #22.

Run the commands in [the demo runbook](../../../infra/demo/README.md). CI now also
runs `tests/privacy` with the API extra, the actual HTTP verifier and current-tree
asset scan. Other suite, lint, generated-schema and TypeScript gates remain intact.
No provider access, deployment or GPU process was involved. This evidence proves
private-demo handling on the current service path; #16's evolving scenario/GPU/
clinical integration and #21's human consent remain separate completion gates.
It does not prove SSD/APFS/backup erasure or participant authentication.
