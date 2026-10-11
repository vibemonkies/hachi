# Stanford floating-clock resting signal

`stanford_nightly_rest(hr_points, step_points, request, policy)` consumes one
source-reconciled participant stream and returns a typed `NightlyRest`, inclusion
counts and causal input hash. Native sample types validate finite values and
minute-aligned steps. The source-specific subpackage has no dependency from frozen
CPU forecast inference; adding this adapter preserves existing forecast receipts.

The source dates are shifted local wall time, represented with Z suffixes only
for canonical storage. Policy requires `floating_local_shifted` and requests use
UTC coordinates. Never join them with real UTC or another dataset.

No README documents cadence, minute start/end meaning or original collection
availability. All three edge interpretations are explicit experiment assumptions.
`start` treats the recorded minute as the beginning; `end` as the end. Conservative
`both` needs recorded zero at M and M+1 for [M,M+1). A disagreement remains outside
rest coverage. Step readiness is conservatively timestamp+one minute for `both`
and `start`; `end` uses timestamp. HR is assumed a point available at its timestamp.

Missing steps stay unknown. Duplicate identical instants count once; conflicting
native values are excluded. Minute HR medians receive equal weight, then the night
is their median. Only usable HR/zero-step minutes count toward minimum rest. A night
before 07:00 or without enough support is unavailable, never a fabricated value.

`source.read_native_nights` selects standard HR/step pairs only, without merging
multiple devices or overlapping long-term files. `burden.run` verifies admitted
archive/snapshot checksums, freezes the clinical split before task eligibility,
scores surveyed symptom-free validation days, saves causal histories and canonical
manifests, and verifies inference from its data-only configuration artifact.
See `reports/evaluation/stanford-anomaly-validation` for the real-source execution,
independent CSV reconciliation and substantial coverage limitations.

The generated tests establish edge semantics, missingness/conflicts, future-input
invariance, boundary readiness, floating-clock enforcement, sealed-test/unknown-label
exclusion, episode grouping, coverage denominators, private permissions and replay.
