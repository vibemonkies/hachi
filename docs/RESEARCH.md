# Research catalog and admission decisions

The admission registry in [`configs/datasets/`](../configs/datasets/) is authoritative: one TOML file per source, validated by `hachi.data.registry`, recording version, access type, license or agreement with quoted evidence, whether teammates can share access, whether a copy may sit on the shared GX10 account, citation, access steps, access owner, approved users, storage, checksum strategy, task fit and blocked capabilities. This page summarises it. Primary sources were rechecked on 2026-10-11.

A catalog entry is not proof of access. Only `downloaded` and `validated` sources list archives someone actually holds, pinned by SHA-256. `access_pending` means a named teammate is pursuing access; `candidate` means nobody has yet; `rejected_for_task` says why. Agents never register, accept agreements or sign DUAs on anyone's behalf.

```sh
python -m hachi.data.registry                 # status table
python -m hachi.data.registry verify [ROOT]   # check local archives; ROOT defaults to $HACHI_DATA_ROOT
```

Raw archives live outside Git under each person's data root as `$HACHI_DATA_ROOT/<dataset_id>/<archive>`, on storage only that person uses. Sources whose `shared_gx10_account` is `allowed` also have one read-only team copy on the GX10 at `~/hachi/data/<dataset_id>/<version>/`, next to a `SHA256SUMS` file produced by `python -m hachi.data.registry sums`. Where an agreement requires security (CMU, every PhysioNet, Synapse and Dataverse source), the target is an encrypted volume with key-only SSH. As of 2026-10-11 neither Justin's T7 nor the GX10 disk is encrypted and the GX10 still allows password SSH on its private lab network. The owners accepted this interim state for CMU and plan to fix both.

## Rules that follow from the terms

- **Per-person access.** CMU, every PhysioNet restricted or credentialed project, Synapse (Homekit2020, Evidation), TILES, OpenMHC-XS and All of Us must be accepted or credentialed by each teammate who touches the data. One person's access never covers the team.
- **The shared GX10 account.** All three teammates share one Unix account, so a copy there is shared with everyone. CovIdentify and the other PhysioNet credentialed data must never go there: PhysioNet does not permit sharing within teams. Other per-person data may go there only once every teammate has accepted the terms; CMU qualified on 2026-10-11. The registry's `shared_gx10_account` field records this per source.
- **No participant rows in hosted LLM conversations.** PhysioNet counts sending restricted data to an LLM API as sharing with a third party unless the service guarantees zero retention, no training and no human review. CMU forbids passing data to anyone who has not accepted its agreement. Agents work on these datasets through code and aggregate counts only, and never print, paste or upload participant-level rows.
- **Analysis registration.** CMU requires planned analyses to be registered with its laboratory before analysis. Synapse cohorts publish your intended-use statement.
- **Attribution.** Each entry's `citation` and `acknowledgement` fields hold the required text, including grant numbers.

## First usable cohorts and blocked capabilities

| Capability | Usable now | Blocked until |
|---|---|---|
| Physiology forecasting and anomaly baselines (#5, #7, #9) | **PMData** (downloaded; CC BY-NC 4.0) first; **LifeSnaps** (downloaded) adds HRV, wrist temperature and SpO2; **NetHealth** (downloaded) adds years of daily history per person | Nothing |
| Recovery labels (#8, #14) | **CMU Common Cold Project** (downloaded): symptom-only, right-censored at the end of a 5-6 day quarantine, no wearables | Evidation ILI or Homekit2020 access for wearable-paired recovery |
| Wearable illness onset (#8, #13) and anomaly lead time (#9) | **Stanford COVID-19 wearables** (downloaded): minute watch HR and steps around 32 COVID-19 onsets. Evaluation-sized: one infection type, wide intervals, too small to train a calibrated model alone | A training-sized cohort: CovIdentify (PhysioNet credential under review, about a week) or Homekit2020/Evidation (Synapse validation) |
| Alertness personalisation (#15) | Nothing: no verified open dataset pairs daily wearable sleep timing with KSS or PVT | Hachi's own self-report collection (#18); DROZY only sanity-checks scales |
| Late case study (#21) | Consented export not yet collected, by design | #20's frozen model |

PMData's license sources conflict: the Simula page and OSF's project field say CC BY 4.0, while the OSF `license.txt` and the paper say CC BY-NC 4.0. The registry binds the stricter CC BY-NC 4.0. Hachi's non-commercial research use is permitted either way.

## Catalog sources

| Dataset | Status | Access | Contributes | Decision |
|---|---|---|---|---|
| [PMData](../configs/datasets/pmdata.toml) | downloaded | public | Fitbit Versa 2, 16 people, ~5 months; minute steps, HR, sleep, daily resting HR, wellness 1-5 | First development cohort for #5. No infection labels; fatigue is not illness |
| [CMU Common Cold Project](../configs/datasets/cmu-common-cold-project.toml) | downloaded | registration | 5 viral-challenge studies (n=1,415): daily symptoms, mucus weight, lab-confirmed infection | Recovery and onset label definitions only; no wearables; register analyses first |
| [CovIdentify 1.0.0](../configs/datasets/covidentify.toml) | access_pending | credentialed | Daily resting HR and steps from 2,887 watch users, daily symptom surveys, self-reported tests | Highest-priority wearable illness cohort; individual credentialing; never on the shared GX10 account |
| [Stanford wearable-infection](../configs/datasets/stanford-wearable-infection.toml) | candidate | public | NightSignal and isolation-forest code with example inputs (Apache-2.0) | Baseline reproduction for #9 |
| [OpenMHC-XS](../configs/datasets/openmhc.toml) | candidate | registration | My Heart Counts subset released on Dataverse 2026-10-08 (~2 GB); full set unreleased | Representation experiments (#11); per-user request; don't make ingestion depend on it |
| [NHANES PAXMIN_H](../configs/datasets/nhanes-paxmin-h.toml) | candidate | public | Minute wrist accelerometry, 7,776 people for ~7 days | Optional (#24) population priors; no HR, survey weights required |
| [WESAD](../configs/datasets/wesad.toml) | rejected_for_task | public | Single-session lab stress, raw chest and wrist signals | Not longitudinal; no watch summaries |
| [PPG-DaLiA](../configs/datasets/ppg-dalia.toml) | rejected_for_task | public | Raw PPG with ECG HR reference | Raw-PPG branch only (#24) |
| [Sleep-EDF Expanded](../configs/datasets/sleep-edfx.toml) | rejected_for_task | public | Clinical PSG with hypnograms | Clinical waveform branch only (#24) |
| [DREAMT 2.2.0](../configs/datasets/dreamt.toml) | candidate | registration | One night of Empatica E4 plus PSG staging, 100 adults | Optional wrist-sleep validation; sign the DUA individually |
| [GLOBEM 1.1](../configs/datasets/globem.toml) | candidate | credentialed | Daily Fitbit steps and sleep, 497 people over 705 person-years | Recommended once the PhysioNet credential exists; no HR, no illness labels |
| [All of Us](../configs/datasets/all-of-us.toml) | candidate | institutional application | Fitbit data for 68,000+ people plus EHR, cloud-only | Only if the university already has a DURA |
| [UK Biobank](../configs/datasets/uk-biobank.toml) | candidate | institutional application | 7-day accelerometry, ~103,000 people | Applications paused until late 2026 |
| [MiPACT](../configs/datasets/mipact.toml) | rejected_for_task | institutional application | Apple Watch, blood pressure, EHR | No access route without a University of Michigan collaborator |
| [Consented personal Apple export](../configs/datasets/personal-apple-export.toml) | candidate | private consent | The friend's target-device history | Collected late for #21 only |

## Additional candidates found 2026-10-11

| Dataset | Status | Access | Contributes | Decision |
|---|---|---|---|---|
| [Homekit2020](../configs/datasets/homekit2020.toml) | candidate | credentialed (Synapse) | 5,034 Fitbit users, 206 PCR-confirmed influenza, minute-level HR/steps/sleep, recovery follow-up | Apply: the best verified illness-label cohort; each user validates individually |
| [Evidation ILI 2019-2020](../configs/datasets/evidation-ili-2019-2020.toml) | candidate | credentialed (Synapse) | ~71,000 people; self-reported ILI onset and recovery dates; day-level Fitbit | Apply: best fit for censoring-aware recovery |
| [Stanford COVID-19 wearables](../configs/datasets/stanford-covid19-wearables.toml) | downloaded | public | Mishra 2020: minute-level watch HR/steps around 32 COVID-19 onsets | Onset and anomaly evaluation; no stated data license |
| [Stanford COVID-19 wearables phase 2](../configs/datasets/stanford-covid19-wearables-phase2.toml) | candidate | public | Alavi 2022: 3,318 people, 84 infected (5.5 GB) | Later: larger anomaly evaluation; no stated data license |
| [LifeSnaps](../configs/datasets/lifesnaps.toml) | downloaded | public | 71 Fitbit Sense users, up to 4 months: HRV, wrist temperature, SpO2, respiratory rate, sleep | Forecasting with Apple-like channels (CC BY 4.0) |
| [NetHealth](../configs/datasets/nethealth.toml) | downloaded | registration | Daily Fitbit activity and sleep for students over 4 years | Long-history forecasting; no stated license. Only the Fitbit files are registered and used; the rest of the release sits apart on the GX10 in `nethealth-extra/` |
| [Crowd-sourced Fitbit 2016](../configs/datasets/crowdsourced-fitbit-2016.toml) | downloaded | public | 30 Fitbit users, minute-level, 2 months (CC BY 4.0) | Real-format ingestion fixture only |
| [TILES-2018](../configs/datasets/tiles-2018.toml) | candidate | registration | 212 hospital staff, 10 weeks of Fitbit HR, steps, sleep | Optional; sign the DUA individually |
| [DROZY](../configs/datasets/drozy.toml) | candidate | public | 14 people in lab sleep deprivation: KSS, PVT, PSG | Optional scale sanity check; read its license PDF first |

Checked and not registered: TemPredict (Oura) and DETECT (Scripps) require PI approval unlikely within a hackathon; MMASH and Walch sleep-accel are one-day or one-night sets; OpenNeuro ds004902 has two sessions per person; Corona-Datenspende released only surveys; no substantial open Oura or Whoop data exists.

## Model candidates

| Candidate / primary source | Role in Hachi | Admission gate |
|---|---|---|
| [Chronos-2](https://huggingface.co/amazon/chronos-2), [official code](https://github.com/amazon-science/chronos-forecasting) | First pretrained forecasting experiment, then targeted adaptation | Pin revision and validate GX10 execution, causal covariates, missing-data behavior and intervals. Apache-2.0 model card. Future observed physiology cannot be supplied as a known covariate. |
| [OpenMHC](https://github.com/AshleyLab/OpenMHC), [WBM checkpoint](https://huggingface.co/MyHeartCounts/openmhc-wbm-dp) | Wearable representation candidate feeding trained heads | Licenses conflict: the README says code MIT and models OpenRAIL, the repository has no LICENSE file, and the WBM model card says CC BY 4.0. Resolve before redistributing a derived model. WBM needs CUDA Mamba2 kernels. Pin exact channel order, normalization and missingness semantics, then test on ARM64/GB10. |
| [MOMENT](https://github.com/moment-timeseries-foundation-model/moment) | Frozen representation + trained head comparator, or compatible alternative if WBM cannot run | Audit checkpoint terms/revision; benchmark against handcrafted features using identical splits. |
| [TimesFM](https://github.com/google-research/timesfm) | Additional forecasting comparator if it can answer a specific ablation | Pin checkpoint and runtime; add only after the first pretrained benchmark is reproducible. |
| [NightSignal](https://github.com/StanfordBioinformatics/wearable-infection) | Existing causal anomaly comparator | Reproduce upstream behavior, audit baseline construction for temporal leakage, preserve attribution. Any causal adaptation gets a different model id. |
| [SleepFM](https://github.com/zou-group/sleepfm-clinical) | Clinical sleep waveform branch | Requires appropriate sleep-recording modalities and a separate task. Do not feed watch stage summaries as clinical waveforms. |
| [PaPaGei](https://github.com/Nokia-Bell-Labs/papagei-foundation-model) | Raw PPG representation branch | Requires optical waveform data. A sequence of heart-rate values is not PPG. |
| [OSF](https://github.com/yang-ai-lab/OSF-Open-Sleep-FM) | Sleep foundation-model research branch | Verify checkpoint, modalities, task and license independently. Not part of the core watch-summary pipeline. |
| [Apple WBM research](https://machinelearning.apple.com/research/beyond-sensor) | Design reference | Do not assume an Apple checkpoint exists; OpenMHC is a separate implementation. |
| [2B-Alert research](https://pubmed.ncbi.nlm.nih.gov/30033688/) | Evidence informing an alertness/PVT design | A paper is not reusable code or an acquired model license. Select and cite equations/implementation separately; validate any personal claims. |

Use model-specific adapters over a common feature store. Start with frozen representations and a learned head before deciding whether full fine-tuning is useful. Preserve experiments that fail to beat the baseline. Multi-teacher distillation is a later optimization only after teachers demonstrate complementary held-out performance; it is not a way to make incompatible modalities or missing labels disappear.

## Per-source acquisition manifest

The registry holds identifier and version, primary URL and DOI, check date, terms with evidence, access owner, approved users, archive checksums, storage and task mapping. Ingestion issues (#5, #8) add schema/codebook audits, device and unit mappings, participant and label counts, exclusions and missingness, and move a source from `downloaded` to `validated`. Split manifests reference the dataset snapshot they used.

Keep the registry free of credentials and personal identifiers. Each trained task must declare the exact datasets it used. Do not redistribute data simply because a repository or download is reachable.
