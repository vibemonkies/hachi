# Private demo operation and retention (#19)

The API is a trusted, single-operator service. Run it on loopback with a private,
per-worker workspace/database/cache/run root. Opaque subject IDs, CORS, dataset
folders and a shared Unix login are **not** participant authentication or access
controls. An operator can access every subject served by that instance. Independent
instances do not share metadata; never expose one as a multi-user service.

## Launch with explicit roots and pins

Use the locked environment in this checkout (`uv sync --locked --extra api
--extra baselines`). Start from a new state root outside Git:

```sh
.venv/bin/python infra/demo/serve.py \
  --owner ezzy1630 --port 8719 \
  --state-root "$HOME/hachi/private-demo/noblecat-run-001" \
  --artifact-root "$HOME/hachi/private-demo/approved-artifacts" \
  --data-root "$HOME/hachi/data" \
  --snapshot <approved-snapshot-id> \
  --artifact <approved-artifact-id>@<full-sha256>
```

The launcher clears inherited Hachi configuration, sets separate mutable roots,
requires a new private state directory, records this checkout's Git SHA, and binds
`127.0.0.1`. It refuses a state root inside the checkout or one that already exists.
Dataset snapshots and model artifacts are operator-selected, verified and read-only
inputs. The launcher never provisions GPU access or stages/changes those inputs.
For synthetic import-only operation, omit `--data-root`, `--snapshot`, and `--artifact`;
`--artifact-root` still identifies the intended empty/private artifact location.
No model is served in that mode. Health must show the expected commit and pins;
`degraded` or an unexpected pin stops a demo. Port 8719 is the #19 test port; parent
8718, Justin 8716, Coffee 8717, and rehearsal 8720 have other owners.

A private SSH forward can connect an authorized operator's laptop to an already
approved loopback service, for example `ssh -N -L 8719:127.0.0.1:8716 <authorized-host>`.
Use a free local port and an existing SSH identity. This instruction does not deploy
anything. Binding beyond loopback, public tunnels, a shared participant-facing
service, new accounts, permission changes or credentials need separate authorization
and an authentication/access design; the CLI's exposure flag is not authorization.

## Which data may be present

The authoritative policy is `terms.shared_gx10_account` in each
`configs/datasets/<dataset-id>.toml`, validated by `hachi.data.registry`:

- `allowed`: the dataset's recorded terms permit shared-account storage. This does
  not authorize redistribution or public display of participant records.
- `only_if_all_users_authorized`: each person with account access must meet the
  dataset's terms, and any encryption/registration requirements must also hold.
- `prohibited`: never copy the source, derived rows, subject predictions or private
  weights to the shared `asus` login. Per-worker directories do not fix this.

CovIdentify, GLOBEM and DREAMT are prohibited there. CMU analysis remains blocked
until the human Data Analysis Form is recorded; encrypted-storage requirements
remain a separate gate. Do not infer encryption or access from a folder name or
permission bit. The #19 inspection makes no remote-storage/encryption claim and
changes no security settings. Justin reported unresolved T7/GX10 encryption and
interim password SSH; these are recorded limitations, not #19-authorized changes.

The permitted phase1 Stanford source/snapshot can be inspected locally without
publishing rows. Its shifted local clock is represented with `Z`; it is not actual
UTC and cannot align dates with another dataset. Its 248 observed symptom-free
survey days are not negative labels for the 74 unlabeled controls. Those controls
have zero negative labels. Phase2 supplies no negatives/recovery follow-up. Illness
outcome metadata is not a predictor available before its recording cutoff. Clinical
scoring/folds/model selection remain in the modeling lanes.

## Personal-case consent and display (#21)

Before the late held-out personal case is collected, the human participant must
explicitly approve, in a private record: purpose and held-out status; export/time
range; intended processors and named viewers; exact machines and account access;
storage and retention; display or recording scope; and withdrawal/deletion contact.
Choose local processing by default. Shared-account access requires every account
user to be authorized under the participant's consent and the source terms. No
consent is implied by an upload, an issue assignment, or the existence of an export.
Do not request or place the record in Git/mail/GitHub. No friend-case tuning or
population-accuracy claim is allowed from that case.

Display consent is separate from analysis consent. Default presentations use
explicitly generated/synthetic examples and aggregate approved research evidence.
Do not show identifiers, personal charts, symptom timelines, predictions, raw export
paths, screen recordings or other identifying content without the participant's
specific display consent. Even consented personal content must stay out of hosted
LLM/tool output. A text/secret scan cannot prove a screenshot contains no private
content: inspect every intended rendered image/video separately; #22 owns rehearsal.

## What deletion means

The service retains imported raw provenance and derived observations in each
private `state/imports/<import-id>/snapshot.sqlite3` until confirmed deletion. The
uploaded ZIP/XML staging file is removed when parsing ends, including a rejected
import. Temporary receiving files are removed when the request fails or finishes.
Failed import metadata is retained so the operator can see and delete the failure.
Reports and self-reports live in the operator's metadata database until deletion.
There is no automatic expiry, backup or personal-model training in the API.

`DELETE /v1/subjects/<id>?confirm=<same-id>` removes that subject's import directories
(including raw and derived records and files placed inside those directories),
import status/summary records, report requests/results, and self-reports. It must
refuse an incorrect confirmation and pending/running jobs. It must preserve other
subjects. Failed filesystem removal must leave metadata for an explicit retry;
concurrent publication must serialize against deletion (#16 service-owner fix).

SQLite uses `secure_delete=ON` to clear deleted cells, followed by a truncating WAL
checkpoint. A blocked checkpoint is an error, not successful retention evidence.
Use one API connection/process per metadata database. This verifies logical removal
and absence of generated sentinel bytes in current files; it does not prove physical
erasure from SSD wear-leveling, APFS snapshots, backups, browser caches or disk images.
Any such copies and independently exported personal artifacts require the human
operator's separate copy inventory and approved deletion procedure. Do not create
personal replay/prediction copies outside the subject-managed directory unless that
inventory and retention plan exist.

Served research datasets and pinned population artifacts are immutable shared
inputs. Subject deletion removes API-created personal overlays, not those sources
or trained population weights. A dataset subject remains available from the served
snapshot. Withdrawal from a source dataset is an access/consent decision handled by
the data owner; #19 must not delete production/private sources or another worker's
state. There is no endpoint to delete population artifacts. The verification tools
only delete disposable roots and generated subjects they created themselves.

## Reproduce the evidence

```sh
.venv/bin/pytest tests/privacy tests/api tests/data/apple_health
.venv/bin/python scripts/privacy/verify_http.py --port 8719
.venv/bin/python scripts/privacy/scan.py --assets infra/demo \
  --clinical-snapshot <permitted-private-phase1-snapshot>
.venv/bin/python scripts/privacy/inspect_clinical.py \
  --archive <permitted-private-phase1-archive> --archive-sha256 <expected-sha256> \
  --snapshot <permitted-private-phase1-snapshot> --snapshot-sha256 <expected-sha256>
```

`verify_http.py` starts only its own CLI service and pins its Git SHA and empty model
refs. It drives generated ZIP/XML upload, job polling, coverage, self-reports,
report completion, rejected archives/XML/resources, cross-subject onset references,
confirmation and deletion. A controlled generated-subject fault also checks real
Uvicorn exception logging. It tests absence of raw/derived directories, metadata,
WAL sentinel bytes and private log strings, preserves another subject, then cleans
its own disposable root. It never contacts a pre-existing listener or real source.

The tests also cover receiving limits without Content-Length and deletion failure/
retry. Uvicorn access logging is disabled; unexpected logs retain method/exception
class only. Validation errors omit submitted values and unrecognized field names.
Upload limits are 256 MiB received, 1 GiB expanded XML, 1,024 ZIP entries, 4 MiB ZIP
central directory, 1,000 expansion ratio, two million records, 64 KiB incomplete XML
tokens, 128 KiB record attributes, depth 32 and 256 distinct XML names. ZIP traversal,
symlinks, encrypted/unsupported/ambiguous archives, XML external entities and oversized
input are refused. JSON requests are bounded to 1 MiB.

The scanner examines every current tracked file plus explicitly supplied assets,
uses bounded file sizes, rejects private data/key/archive formats and symlinks,
detects credential patterns and exact private-roster IDs, and prints only counts.
It fails on unscanned oversized files. It is a current-tree/presentation-text scan,
not a Git-history audit, image OCR, or proof that every possible secret is absent.
Keep raw IDs, predictions, model weights and credentials outside Git and all posted
evidence. The clinical inspector only reads pinned bytes/modes and validates the
snapshot; it changes nothing and prints no participant rows or IDs.
