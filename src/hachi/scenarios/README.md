# Conditional sleep scenarios

This offline model compares one to four alternative sleep schedules. It reads only an
explicit synthetic request and a versioned parameter file, never PMData or participant
observations. It produces an illustrative relative alertness index, not a probability,
KSS score, PVT forecast, measured benefit, or causal benefit. No validation is claimed.
A plausible sleep-regulation mechanism does not validate a mapping to KSS or PVT.

From the repository root, with Hachi's existing dependencies available:

```powershell
$env:PYTHONPATH = "$PWD/src"
python -m hachi.scenarios.demo --request configs/scenarios/compare-bedtimes.toml --model configs/scenarios/two-process-v1.toml --output "$env:TEMP/hachi-scenario-demo"
```

Use an output directory outside Git. `result.json` is an existing `AlertnessResult`
contract with `status=ok`, `task=alertness`, `mode=simulation`, `data_mode=synthetic`,
`validation=null` and `dataset_snapshot=null`. `request.json` preserves the validated
request. `curves.svg` plots the same simulated points in three aligned panels, without
recomputing equations. Its x-axis uses UTC and draws only waking intervals. There is
one curve per schedule, every 30 elapsed minutes from wake through bedtime+24 elapsed
hours, with an extra final endpoint when necessary.

`model-artifact.json` archives the exact configuration and original implementation
sources plus this description. The provenance SHA-256 hashes those exact UTF-8 bytes;
the artifact id is the model version. `git_sha` identifies the checkout HEAD, while
the artifact captures local uncommitted source. Generation time changes between runs;
simulation points are deterministic for identical inputs. The command requires Git
to resolve HEAD. Request JSON is accepted as well as TOML. Keep TOML local timestamps
quoted as strings, as in the example. Contract validation rejects unknown fields,
duplicate ids, nonexistent local times, and invalid inputs. Ambiguous times resolve
to fold=0. The domain additionally enforces actual UTC sleep duration in (0,16] hours.

## Equations and synthetic history

Let B be the chronologically earliest resolved bedtime, independent of request list
order. Initialize S=0.6 at B-24 elapsed hours. Place all stated `prior_sleep_hours` in
one contiguous synthetic sleep block starting at B-24h, then remain awake until B.
This placement is a disclosed convention, not an inference of actual sleep history.
Each alternative remains awake from B to its own bedtime, sleeps until its own wake,
then remains awake until its bedtime+24 elapsed hours. Alternatives never feed into
each other. All propagation and sampling use elapsed UTC time, including across DST.

For duration d in hours:

```
awake: S(t+d) = 1 - (1-S(t))*exp(-d/18.2)
sleep: S(t+d) = S(t)*exp(-d/4.2)
C(t) = cos(2*pi*(t-anchor)/24h)
A(t) = (1-S(t) + a*(C(t)+1))/(1+2*a), a=0.2
```

The anchor is 15:00 local time on B's local date, converted once to UTC. C advances
continuously thereafter; neither candidate schedule changes nor light shift its
phase. S is in [0,1], C in [-1,1], and A in [0,1], with higher A meaning more
simulated alertness. Initial pressure, synthetic history placement, phase and index
weight are assumptions, not sourced fits. The configuration exposes these assumptions
and the time constants; changes must be disclosed when interpreting comparisons.
`caffeine` and `light_exposure` remain required contract assumptions and are echoed
exactly. Neither has a modeled effect, including when caffeine is `none`.

The two-process concept is described in
[Borbély et al., The two-process model of sleep regulation: a reappraisal](https://doi.org/10.1111/jsr.12371).
The 18.2h waking and 4.2h sleeping constants follow
[Daan, Beersma & Borbély (1984), Timing of human sleep: recovery process gated by a circadian pacemaker](https://doi.org/10.1152/ajpregu.1984.246.2.R161).
No parameter fit for this population is claimed. Equation concepts are literature-derived;
this implementation is original. No software code license is asserted or borrowed.

## Design and limits

`model.py` owns frozen domain values and a pure simulator; it has no contract,
filesystem, clock, or dataset dependencies. `contract.py` owns local-time conversion
and existing result metadata. `demo.py` owns file I/O, artifact provenance and SVG
presentation. This keeps shared contracts and API/UI behavior untouched. A direct
analytic propagation avoids integration step error and makes alternatives independent.
The static SVG has no browser dependency. The small model omits naps beyond the one
synthetic prior block, sleep quality, chronotype, adaptation, individual differences,
sleep inertia, caffeine effects and light entrainment. Different assumptions can change
the apparent schedule comparison. The index cannot select a medically optimal bedtime.

## Future collection and evaluation

Collect repeated `AlertnessRatingEntry` observations using `entry_id`,
`entered_at_utc`, `rated_at_utc`, `scale="kss_1_9"`, and `value` 1–9. KSS is higher
when sleepier, opposite to this index. Record the event time separately from entry
time; delayed entry must not be treated as contemporaneously available evidence.
Collect `PvtResultEntry` with `entry_id`, `entered_at_utc`, `started_at_utc`,
`duration_seconds`, `trials`, `mean_reaction_time_ms`, and `lapses` (responses slower
than 500ms). Keep rating and PVT outcomes separate rather than combining them into
one label or treating the illustrative index as either outcome.

Predefine a consistent daily collection schedule relative to waking and local time,
a fixed PVT duration, device, task implementation, setting and instructions, and a
consistent rating prompt. Record actual sleep timing/quality, naps, caffeine dose and
timing, light exposure, chronotype, shift work, travel/timezone, medication, alcohol,
illness, exercise and device/task changes as relevant confounders. Track planned and
completed observations, missingness reasons and delayed entries. Missing observations
are unknown; do not fill them as alertness, sleepiness or zero lapses.

PMData has no alertness labels. Its daily fatigue direction is higher=less fatigued;
that daily response is not hourly alertness truth and cannot validate these curves.
Future work needs newly collected labels and a predefined evaluation protocol. Hold
out later observations for within-person evaluation and participants when evaluating
generalization to new people. Fit personalization and every KSS/PVT mapping on training
data only. Compare held-out outcomes against training-only time-of-day means, the last
available rating (for the rating outcome), and an unpersonalized circadian baseline.
Use equivalent outcome-appropriate baselines for PVT, with a last available PVT value
where applicable. Respect entry-time availability at every prediction cutoff. Report
rating errors and PVT reaction time/lapse results separately, with coverage, missingness,
sample counts and uncertainty. Such a study, rather than the mechanism or this synthetic
demonstration, would establish whether a mapping predicts either outcome.
