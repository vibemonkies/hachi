# Apple Health import boundary — issue #6

This imports XML or ZIP into a new private SQLite snapshot, returns reconciled audit counts, and exposes canonical observations. All verification here uses generated records. Consented real-export acquisition and reconciliation remain the late #21 gate.

## Caller

```python
from datetime import UTC, datetime
from pathlib import Path
from hachi.data.apple_health import ImportConfig, import_export, iter_observations

config = ImportConfig(
    dataset_id="synthetic-apple",
    subject_id="synthetic-001",
    declared_tz_name="America/Los_Angeles",
    data_mode="synthetic",
)
database = Path("runs/private-apple/import.sqlite3")
audit = import_export(Path("export.xml"), config, database)
assert audit.counts.bucket_total() == audit.counts.records_seen
for observation in iter_observations(database, as_of=datetime(2026, 10, 11, tzinfo=UTC)):
    consume(observation)
```

The output directory must be private (0700); the importer creates it when missing. The new database is created with O_EXCL and mode 0600, never overwrites an existing snapshot, and is removed if the import fails. Callers own consent, authorized input/storage locations, snapshot admission, and subsequent API job orchestration. No upload endpoint, service, credentials, model, or global environment is installed.

The local CLI prints aggregate audit fields rather than source names, device descriptions, raw rows, or pseudonymous participant identifiers:

```sh
uv run python -m hachi.data.apple_health export.xml \
  --database runs/private-apple/import.sqlite3 \
  --dataset-id synthetic-apple --subject-id synthetic-001 \
  --timezone America/Los_Angeles --data-mode synthetic
```

## Records and selection

- Expat processes bounded binary chunks, without accumulating an XML tree. SQLite stages raw record attributes, nested metadata, and normalized candidates on disk. Source names and full device descriptions remain private; canonical source IDs are deterministic hashes scoped to dataset/subject. Only the device model field is exposed. Start/end/creation strings, their distinct offsets, source/device/version attributes, and metadata are retained unchanged in private staging.
- Canonical records retain UTC start/end, record offset provenance, and Apple `creationDate` as observed availability. The declared IANA timezone is recorded separately in the audit/config and never presented as a source-observed timezone. Naive/invalid timestamps and end-before-start records are rejected.
- Supported measurements: heart rate, vendor resting HR, SDNN, respiratory rate, SpO2, body temperature, steps, active energy, walking/running distance, and named sleep states. Known unit conversions are explicit; unknown units are quarantined. Invalid/impossible values are rejected. HealthKit percent values are fractions, so 0.98 becomes canonical 98 percent. SDNN is never relabeled RMSSD. Absolute sleeping wrist temperature stays unsupported because it is neither body temperature nor the registered wrist-temperature deviation metric.
- Unknown compatible-source types are counted as unsupported after their basic record fields/timestamps are checked. The audit names unavailable metrics, accepted counts and observed UTC spans per metric, and aggregate source-kind counts. It does not infer zero steps, healthy status, clinical readiness, or continuous-time coverage from sample counts.
- Exact canonical duplicates are counted once. Source precedence defaults to watch, phone, third-party app, unknown; a private explicit `source_priority` tuple of source names may override it. Equal-priority same-start conflicts prefer newer creation, then stable record identity. Selection is deterministic and independent of XML record order.
- Competing overlapping intervals are excluded as whole records. No step total is prorated or summed across competing sources. Intervals are half-open; point measurements compete at the same instant or inside an interval. Staged asleep states take precedence over overlapping summary asleep records, while in-bed and awake identities remain distinct. A partially overlapping summary is excluded in full; its uncovered remainder is **unknown**, not manufactured. This conservative policy may reduce usable coverage. All alternatives and original intervals remain in private staging for audit.
- `iter_observations(database, as_of=cutoff)` filters both event end and creation availability **before** reapplying precedence. A future-created watch sample or sleep stage cannot suppress an earlier eligible phone/summary record. Do not load only the full-import selected rows and then filter them for historical predictions. The iterator yields in selection priority order; consumers must use timestamps rather than assume chronological order.
- Every XML `Record` lands in accepted, duplicate (including overlap exclusions), unsupported, rejected, or quarantined. The canonical `ImportCounts` buckets reconcile to records seen; `RecordIssueSummary` carries aggregate stable codes. Root/shared contracts and dependency locks are unchanged.

## Input limits

Default upload limit is 256 MiB; XML expansion and total advertised archive contents are limited to 1 GiB, with at most 1024 entries, a 4 MiB central directory, 1000× expansion, 2 million records, 64 KiB unfinished tokens, 128 KiB record attributes/metadata, depth 32, and a bounded XML name/declaration vocabulary. Review limits with the storage owner before expanding them.

ZIP access streams the sole `export.xml`; it never extracts. Absolute/traversing/drive/backslash paths, symlinks, encryption, ambiguity, unsupported compression, malformed directories, and excessive size/ratio are refused. The central directory is bounded before `ZipFile` allocates it. ZIP64 central directories and multi-disk archives are refused with an actionable instruction to provide XML or a supported ZIP. XML may contain Apple's internal schema DTD, but entity declarations, external DTDs and entity resources are forbidden. Reparse deferral stays enabled. XML buffers, record metadata, nesting and vocabulary have explicit bounds.

SQLite must include its RTree module (verified on this host and exercised by CI). A disk-backed spatial index narrows overlap candidates; exact integer-microsecond comparisons make the final decision, so outward-rounded index bounds cannot create false deduplication. Mutable SQLite/cache state belongs to this importer invocation; readback uses a read-only connection with private temporary selection state.

## Verification

```sh
uv sync --locked
uv run pytest tests/data/apple_health
npm exec --yes --package=bun@1.4.0 -- make setup
npm exec --yes --package=bun@1.4.0 -- make check
uv run python -m hachi.data.apple_health.benchmark --output runs/new-memory-measurement.json
uv build --out-dir runs/apple-import-dist
```

On the isolated `issue-6-apple-import` checkout based on main `9fc9d0d`, 36 focused cases and all 199 Python tests passed, plus five coordination tests, lint/format, generated schema/fixture/type freshness, and TypeScript compilation. Wheel construction passed and contains every importer module. The temporary Bun 1.4.0 command handles the repository's version-2 lock without changing a global installation or lockfile.

The fresh subprocess memory measurement uses Python 3.12.13, Expat 2.6.3, SQLite 3.50.4 on macOS ARM64. At 5,000 records, import/readback took 0.241 s with 44.7 MiB peak RSS (37.3 MiB pre-import peak). At 50,000 records, it took 2.743 s with 47.6 MiB peak RSS (37.2 MiB pre-import peak). Both input/audit/readback counts reconcile exactly. Input grew from 1.11 MB to 11.10 MB; SQLite grew from 5.86 MB to 58.37 MB. This is one synthetic measurement pair, demonstrating bounded resident growth on this workload, not a real-export performance guarantee. [The sanitized evidence](evidence/memory-macos.json) binds the exact source hashes. Generated XML/databases were created in owned temporary directories and cleaned up.

Security and domain cases cover malformed/entity/external XML, depth/token limits, safe internal DTD, archive traversal/symlink/ambiguity/corruption/ratio/directory/entry limits, known/unknown units, exact/overlap deduplication, future availability, missing steps, distinct temperature/HRV semantics, cross-midnight and DST sleep, private provenance, CLI readback, timezone tie ordering, timestamp overflow, and overwrite refusal. The timezone-order and timestamp-overflow regressions failed before their fixes and passed afterward. Real Apple export reconciliation and live API integration are unverified and remain #21/#16 respectively.

Primary semantics: [HealthKit percent units](https://developer.apple.com/documentation/healthkit/hkunit/percent()), [sleeping wrist temperature](https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier/applesleepingwristtemperature), [sleep state identifiers](https://developer.apple.com/documentation/healthkit/hkcategoryvaluesleepanalysis), and [Expat parsing/security controls](https://docs.python.org/3/library/pyexpat.html).

## Native hourly inputs — #16/#22 compatibility subtask

`hourly.py` bridges the immutable importer snapshot to the evaluator's structural
`FeatureBin` interface. The importer/parser/normalization/selection policy is unchanged.
The original API rejects Apple imports unconditionally for hourly-feature artifacts;
this helper supplies the data seam. WindyTrout owns API wiring and source compatibility.

```python
from hachi.data.apple_health.hourly import AVAILABILITY_RULE, apple_hourly_features
from hachi.evaluation.features import HourlyFeaturePolicy

# The serving owner must explicitly admit this source protocol. Do not replace
# a frozen PMData receipt or treat its evaluation as Apple validation.
apple_policy = HourlyFeaturePolicy(
    metric="heart_rate",
    aggregation="mean",
    min_coverage=0.5,
    min_observed_count=30,
    availability_rule=AVAILABILITY_RULE,
)
view = apple_hourly_features(database, apple_policy, cutoff, history_start)
history = view.features  # canonical HourlyFeature, with source-specific readiness
```

The public entry point returns `AppleHourlyView`, retaining `.policy`, `.features`
and `.counts` and adding `.audits`. Native bins and replay are private; callers must
use the guarded Apple entry point, which refuses foreign readiness rules before
building features. Serving must not feed private Apple bins through the shared
selector with a PMData policy. The original policy is not rewritten.

Each `HourAudit` is a separate receipt bound to hour start, fixed closure and the
actual audit cutoff. It reports unique normalized native candidates whose starts
belong to that hour and whose creation **and event end** are at or before the audit
cutoff. Exact canonical duplicates count once; importer raw-record disposition
counts are separate. The following reasons are exclusive and reconcile to
`known_candidates`:

1. `excluded_created_after_seal`: creation after fixed hour closure. This includes
   late crossing records, which are attributed here only.
2. `excluded_cross_hour`: remaining on-time candidates ending outside their start
   hour; excluded whole, with no proration.
3. `excluded_by_precedence`: remaining on-time contained candidates not selected
   by the importer's source/overlap rules at closure.
4. `included_records`: selected contained native records used in the aggregate.

Audits also report sampled HR minutes, recorded step interval seconds and private
source-ID/count pairs. A late candidate stays excluded even when its audit count
becomes visible later. Records created or ending after an earlier audit cutoff are
invisible to that receipt. Audit counts/time never enter feature value, identity,
coverage or readiness. All-late history produces missing bins with visible late
counts after the candidates become known; it does not manufacture usable history.
`.counts` retains the existing inclusion/missing/density/count gate outcomes.

| Property | Apple source protocol |
| --- | --- |
| Readiness | `apple-hour-end-sealed-native-v1`: bin available at completed UTC hour end |
| Native eligibility | Event end **and** observed Apple creation time at or before that hour end |
| Precedence | Replay audited importer selection at each hour end, before aggregation |
| HR value | Arithmetic mean, median, min or max of selected native HR records wholly inside the hour |
| HR coverage | Distinct UTC minutes containing selected HR starts divided by 60; sampled-minute **density**, not continuously observed duration |
| Step value | Sum selected whole recorded amounts; no cross-hour proration |
| Step coverage | Union of explicitly recorded intervals divided by 3600 seconds, including intervals with measured zero totals; instantaneous totals have zero duration support |
| Missingness | No record means null/unknown, never zero; vendor resting HR is excluded from native HR |
| Model gates | Original metric/aggregation/minimum density/minimum count remain in force |

These bins intentionally seal at hour end. A record created later stays queryable
through `iter_observations` but never revises that hour's model input. A late watch
record cannot suppress an earlier eligible phone record or move its readiness into
the future. This differs from PMData's latest-input closure; passing a PMData
availability rule to this helper raises an error. Both value and source lineage
are deterministic under source-declared future/late additions, independent of XML
order. This is source creation-time causality, not an independently observed online
ingestion time; backdated source metadata is not proof of historical receipt.

Only fully contained native records contribute. Interval HR contributes one level
sample at its start, without claiming continuous duration. Cross-hour amounts are
excluded whole, leaving their portions unknown. Source precedence runs first: a
crossing winner can suppress a contained loser and then be excluded itself; both
contributions stay unknown. The loser is counted as a precedence exclusion in its
start hour; the crossing winner is counted once in its own start hour. Bins cover
completed UTC hours from the earliest known native candidate, or the requested
lower bound, to the cutoff;
an unaligned lower bound excludes its partial first hour. Empty metric history
returns an empty view. Timezone offsets are normalized by the importer; no source
calendars or individuals are joined. Source IDs and per-source audit counts stay
private with the imported snapshot.

The source protocol is authored and repository-tested using generated hostile
records. It is **not** scientific readiness or real Apple forecast validation.
Serving must retain the original frozen artifact/protocol receipt and separately
declare any accepted Apple input rule. Low-density history abstains at the existing
0.5/30 HR gates; no friend export or held case was used to choose them. Generated
Apple HTTP-to-artifact evidence, once wired, is synthetic transport proof; #21's
actual consented export and source-transfer validation remain separate gates.

The focused tests exercise density versus duration, unchanged gates, late higher
priority updates, exact duplicates, native precedence, creation/end boundaries,
UTC offsets, whole cross-hour exclusion, zero-step intervals, instant step totals,
missing/vendor-only history and foreign policy refusal. Additional sentinels verify
known-only late counts, exclusive reason reconciliation, exact-duplicate counting,
all-late missingness, crossing-winner suppression, read-only snapshots and native
oracle agreement. Feature identity/readiness stay fixed while later audit receipts
show newly known exclusions. On this Mac, a generated
1,440-record/48-hour probe took 0.012 seconds for one native read versus 0.285
seconds for sealed-hour replay (48 eligible bins), Python 3.12.13. Replay reuses a
read-only SQLite snapshot and the canonical `iter_observations(as_of=closure)`
boundary, with private disk-backed temporary state. Generated hostile-record tests
pin agreement with an independent native-read oracle. It scans prior candidates
per hour; supply the model lookback `start` in serving.

GreenHawk's independent review at `cb1c5a7` measured a 48-hour lookback at 12.0
seconds for 20,000 generated HR records and 69.5 seconds for 105,120 records; one
native read of the latter took 1.46 seconds. These are reviewer measurements of
prior replay, not an interactive-latency guarantee for the audited update. The
history × lookback cost remains an explicit API integration gate. A performance
change must preserve importer precedence, the fixed closure and native-read oracle;
no parser/store or API changes are included in this audit update.

A separate generated 48-hour dense/sparse probe loaded the actual frozen PMData
`hourly-last-valid-v1-141306001b16e168` artifact with receipt
`e7666ef0f4665006822f9ee9c0988a6de0df1633175ff217a27666ce6f66fa3b`
from the validation packet, checking its code/content hashes. Native import →
Apple feature policy → direct model inference produced 24/24 expected synthetic
points; the unchanged gates yielded 24/24 abstentions for sparse input. This proves
the helper's structural input compatibility with that immutable artifact. It does
not prove HTTP integration, Apple source transfer, calibration or population accuracy.

After the audit update, the same checksum/code-verified artifact again produced
24/24 expected generated points. Thirty withheld future watch updates were invisible
at the earlier cutoff; their later audit receipt counted 30 late exclusions while
every prior feature, identity and readiness remained identical. The original CPU
receipt verified without a descriptor or shared feature-contract override.
