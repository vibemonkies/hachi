# Final model card — incomplete template

Status: blocked on the final evidence packet. No final winner or test result exists
in this template. Populate it only from accepted immutable aggregate artifacts.

## Intended use and unsupported uses

Record the target, horizon, user population, devices, decision cadence and coverage
requirements for each supported task. List unavailable capabilities with their exact
missing labels, source, artifact or verification gate. Avoid diagnostic or causal
claims beyond the observed task. Separate simulations from measured predictions.

## Frozen identities and selection

Record selected artifact IDs/checksums; producing code and environment; preprocessing,
threshold and calibration digests; selection rule/log/budgets; source/checkpoint
revisions and licenses; dataset/split/metric-definition identities; accepted protocol
amendments; and the freeze manifest hash established before test opening.

Retain baseline winners and negative experiments. Report pretrained cohort overlap
as known, absent or unknown with its evidence. Identify selection optimism and the
independent final partition. Never insert private participant IDs, rows or weights.

## Population, availability and leakage controls

Record participants, episodes, censoring, observed versus unknown labels, exclusions,
missing channels and device/source shifts. Bind whole-person/episode splits and
cutoff availability rules. State floating-clock and historical-availability assumptions.
Explain training-only transforms, validation-only thresholds/calibration, out-of-fold
stacking, lookback/embargo sensitivity and final-cohort sealing/opening provenance.

## Final held-out task reports

For every supported task, link accepted aggregate metrics, paired baseline differences,
participant intervals, exact denominators, abstentions and coverage. Include exclusions
and missingness/device analyses. Mark unestimable metrics and unavailable tasks directly.
Validation-only metrics cannot fill a final-test field.

## Runtime, reproduction and failure cases

Record hardware, latency percentiles, peak memory and measurement scope. Link fresh
checkout/environment inference reproduction with matching selected artifact and output
identities. Describe measured failure cases and source-transfer limits. Link independent
acceptance and the evidence-to-public-claim review; a build alone does not establish these.

## Completion gates still open

- #12 selected artifact, adaptation/ensemble/ablation evidence and frozen export.
- #13 accepted incident-onset support and calibrated held-out evaluation.
- #14 accepted recovery follow-up/support and censoring-aware held-out evaluation.
- #15 scenario evidence and distinct measured-label alertness support.
- Parent-coordinated final test opening, untouched-partition evaluation, selected inference
  reproduction and claim review. No friend-case tuning, deployment or study is implied.
