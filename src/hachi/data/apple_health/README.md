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
