# #19 private storage and demo evidence

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
