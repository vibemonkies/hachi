# Public activity and waveform feasibility evidence

Checked 2026-10-11. Owned evidence note for #24; official documentation/papers only. No dataset or weights downloaded, no account/terms accepted, no experiment run. Local scope references: [research catalog](../../../../docs/RESEARCH.md) and the four registry files linked below. Public availability is separate from Hachi admission.

## What does each source actually support?

### Takeaway

These sources support activity priors, laboratory stress, optical heart-rate estimation, or PSG sleep staging. None supplies a documented training-sized wearable illness-onset/recovery cohort.

### Cited Findings

| Source | People, recordings and duration | Modalities and labels | One concrete task |
|---|---|---|---|
| NHANES PAXMIN_H | **7,776 participants**, ages 3+; planned seven full days plus partial boundary days | GT3X+: original acceleration 80 Hz, light 1 Hz; this release is **minute MIMS/lux summaries**, with algorithmic wake/sleep/non-wear/unknown labels, not PSG stages. [CDC codebook](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2013/DataFiles/PAXMIN_H.htm) | Survey-weighted distribution of daily activity MIMS among adults, stratified by age; no conversion of MIMS to watch steps. |
| WESAD | **15 released people**, one roughly two-hour lab protocol each; 17 recruited, two discarded after sensor failures. [Authors' paper, §§3.1–3.3](https://ubi29.informatik.uni-siegen.de/usi/pdf/ubi_icmi2018.pdf) | Chest ECG/EDA/EMG/respiration/temperature/ACC at 700 Hz; wrist BVP 64 Hz, EDA/temperature 4 Hz, ACC 32 Hz. Neutral/stress/amusement conditions and questionnaires. [UCI](https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection) | Participant-held-out wrist-only stress versus non-stress classification; a lab affect task. |
| PPG-DaLiA | **15 people = 15 sessions**, approximately 36 hours total; protocol ~150 min/person. [Authors' paper, §§2.2.3–2.2.5](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679242/) | Chest ECG/respiration/ACC 700 Hz; wrist BVP 64 Hz, ACC 32 Hz, EDA/temperature 4 Hz. [UCI](https://archive.ics.uci.edu/dataset/495/ppg+dalia) | Participant-held-out PPG heart-rate estimation against ECG reference, with error stratified by activity. |
| Sleep-EDF Expanded 1.0.0 | **197 recordings**: 153 sleep-cassette (SC), 44 sleep-telemetry (ST). SC ~20-hour day/night periods; ST ~9-hour nights from **22 people**, paired placebo/temazepam. | EEG Fpz-Cz/Pz-Oz and horizontal EOG 100 Hz. SC chin EMG is a **1 Hz envelope**; ST EMG 100 Hz. Some SC recordings add airflow/temperature 1 Hz. Technician-scored R&K W/R/1/2/3/4/M/? hypnograms. [PhysioNet](https://physionet.org/content/sleep-edfx/1.0.0/) | Whole-person-held-out EEG/EOG sleep staging, explicit N3 merge of R&K 3+4, exclude movement/unscored epochs under a frozen rule. |

- NHANES quality limitations are explicit: one 80 Hz sample is absent every minute because of a processing error; MIMS `-0.01` means uncomputable, while QC flags are independently generated. Battery depletion and nonreturn/damaged devices reduce completeness; 96% wore until day 9 and about 2% had fewer than seven days **across the cited PAM surveys**, not a newly measured Hachi rate. CDC requires examined-sample weights. [CDC analytic notes](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2013/DataFiles/PAXMIN_H.htm)
- WESAD's UCI field says no missing values; that does not describe excluded recruits or per-channel artifacts. The paper reports two exclusions due to sensor malfunction, and describes lab conditions and subjective ratings rather than longitudinal illness. [UCI](https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection); [authors' paper](https://ubi29.informatik.uni-siegen.de/usi/pdf/ubi_icmi2018.pdf)
- **PPG-DaLiA completeness correction:** UCI says no missing values, but the source paper reports a hardware-truncated session with only the first 90 minutes usable. ECG R-peaks were manually corrected; HR reference is mean instantaneous HR over eight-second windows, shifted two seconds. Eight activities plus transitions are annotated; demographic/skin-type coverage is limited. [UCI](https://archive.ics.uci.edu/dataset/495/ppg+dalia); [authors' paper, §§2.2.3–2.2.5 and conclusion](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679242/)
- Sleep-EDF has three lost SC nights and absent ST channels. Earlier eight-/61-record releases are nested, not independent cohorts. [PhysioNet](https://physionet.org/content/sleep-edfx/1.0.0/)

### Inferences

- SC implies **78 people**: (153 retained + three lost)/two nights. With 22 ST people: 100 nominal people, cross-study deduplication unverified. [PhysioNet](https://physionet.org/content/sleep-edfx/1.0.0/)
- Split at person level before making overlapping windows; keep paired Sleep-EDF nights together. Adjacent samples, minute rows and windows increase observations, not the independent participant count. [PPG-DaLiA protocol](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679242/); [Sleep-EDF protocol](https://physionet.org/content/sleep-edfx/1.0.0/)
- No reviewed schema pairs prospectively timestamped infection/recovery follow-up with longitudinal watch summaries. These four sources therefore cannot clear Hachi's illness-training dependency; this is task-fit judgment from the documented modalities/labels, not a computed clinical result. [CDC](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2013/DataFiles/PAXMIN_H.htm); [WESAD](https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection); [PPG-DaLiA](https://archive.ics.uci.edu/dataset/495/ppg+dalia); [Sleep-EDF](https://physionet.org/content/sleep-edfx/1.0.0/)

### Gaps

- Per-channel usable fractions after a frozen Hachi quality rule are unmeasured; no local data audit was authorized. UCI's no-missing field must not substitute for that audit. [WESAD UCI](https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection); [PPG-DaLiA UCI](https://archive.ics.uci.edu/dataset/495/ppg+dalia)
- Cross-source participant overlap, particularly between WESAD and PPG-DaLiA from overlapping author/device ecosystems, is **unknown**, not established absent. The reviewed papers supply no participant crosswalk; do not pool them as proven-disjoint people. [WESAD paper](https://ubi29.informatik.uni-siegen.de/usi/pdf/ubi_icmi2018.pdf); [PPG-DaLiA paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679242/)

## Which model branches match the source modality?

### Takeaway

PaPaGei is a raw optical waveform candidate for PPG-DaLiA or WESAD; SleepFM/OSF are PSG candidates for a separate sleep task. None is a justified adapter for existing watch stage summaries or minute heart-rate values.

### Cited Findings

- **PaPaGei:** official code is BSD-3-Clause; reference installation uses Python 3.10/PyTorch and `pyPPG==1.0.41`. Its example cleans single-channel optical PPG, makes ten-second segments and resamples to 125 Hz for a 512-dimensional encoder representation; CPU inference is supported by the example's device selection. [Official code/README](https://github.com/Nokia-Bell-Labs/papagei-foundation-model)
- Its pretraining corpora are **VitalDB, MIMIC-III waveform matched subset and MESA**; WESAD valence/arousal and PPG-DaLiA HR/activity were downstream tasks, not stated pretraining cohorts. The appendix describes selecting checkpoints based on downstream performance. Thus absence from pretraining does not make these datasets new to upstream model selection. [PaPaGei paper, §4.1 and Appendix A](https://arxiv.org/pdf/2410.20542v2)
- **SleepFM Clinical:** official repository offers base, staging and disease checkpoints and states CC BY-NC 4.0. The published corpus comprises Stanford Sleep Clinic, BioSerenity, MESA and MrOS; SHHS was excluded from pretraining. [Official repository](https://github.com/zou-group/sleepfm-clinical); [publisher's paper/indexed methods](https://www.nature.com/articles/s41591-025-04133-4.pdf)
- Its official notebook converts EDF to HDF5 at **128 Hz**, uses five-second patches, groups channels into brain/respiratory/ECG/EMG modalities, and explicitly marks its demo data/labels **synthetic**. It directs users to inspect dataset-specific channel mappings with domain expertise. [Official notebook](https://raw.githubusercontent.com/zou-group/sleepfm-clinical/main/notebooks/demo.ipynb)
- **OSF:** code and OSF-Base model card declare MIT. Python ≥3.10, PyTorch ≥2.9, Lightning ≥2.5.5; input is **12 PSG channels × 1,920 samples = 30 seconds at 64 Hz**, including specified C3-A2/C4-A1 EEG and E1-A2/E2-A1 EOG montages plus ECG, chin/leg EMG and respiratory channels. [Official code](https://github.com/yang-ai-lab/OSF-Open-Sleep-FM); [official model card](https://huggingface.co/yang-ai-lab/OSF-Base)
- OSF's paper names SHHS/NCHSDB/WSC/CCSHS/CFS for pretraining and MrOS/MESA/CHAT/SOF for external evaluation; **Sleep-EDF is absent from that list**. The code/model card's supported-source list additionally includes STAGES: that discrepancy must be resolved for the exact checkpoint. [Paper, Appendix B.1](https://arxiv.org/html/2603.00190v2); [model card](https://huggingface.co/yang-ai-lab/OSF-Base)

### Inferences

- A frozen PaPaGei encoder plus trained HR head could be compared against a conventional PPG HR estimator on identical PPG-DaLiA participant folds. Original eight-second reference windows and the encoder's ten-second example need an explicit label/window alignment rule; interpolation cannot recreate missing optical detail. This is a proposed experiment, not executed feasibility. [PaPaGei example](https://github.com/Nokia-Bell-Labs/papagei-foundation-model); [PPG-DaLiA labels](https://pmc.ncbi.nlm.nih.gov/articles/PMC6679242/)
- Sleep-EDF needs a **separate montage adapter**, not channel-name substitution. Its EEG/EOG references, EMG envelope and absent channels differ from OSF's prescribed inputs. SleepFM needs mapping/resampling inspection too. [Sleep-EDF](https://physionet.org/content/sleep-edfx/1.0.0/); [OSF input](https://github.com/yang-ai-lab/OSF-Open-Sleep-FM); [SleepFM mapping instructions](https://raw.githubusercontent.com/zou-group/sleepfm-clinical/main/notebooks/demo.ipynb)
- Published gains on PSG/PPG tasks cannot establish improved Hachi illness, recovery or watch-summary forecasting. Any branch needs a same-target ablation and separate acceptance evidence. [Local model-admission rules](../../../../docs/RESEARCH.md)

### Gaps

- PaPaGei's Zenodo record lists released weights and underlying-data terms; the fetched text did not establish a distinct weight license. Code BSD does not alone settle every checkpoint's redistribution terms. Pin and resolve exact artifact terms before admission. [Weight record](https://zenodo.org/records/13983110)
- SleepFM's publisher page/PDF returned `Internal Error` on direct fetch; cohort details above were available from its indexed primary-source methods and repository, not a successful complete-paper read. Sleep-EDF absence from the listed cohorts is not participant-level proof of no overlap. [Publisher](https://www.nature.com/articles/s41591-025-04133-4.pdf)
- No checkpoint was downloaded or run; ARM64 environment compatibility, runtime cost, exact revision and channel-failure behavior remain unverified. Official examples are not Hachi execution evidence. [PaPaGei](https://github.com/Nokia-Bell-Labs/papagei-foundation-model); [SleepFM](https://github.com/zou-group/sleepfm-clinical); [OSF](https://github.com/yang-ai-lab/OSF-Open-Sleep-FM)

## What are the access and admission barriers?

### Takeaway

PPG-DaLiA and Sleep-EDF have clear public licensing; WESAD is scientific/noncommercial; NHANES is statistical-use public data under NCHS restrictions. Registry status currently authorizes no experimental branch here.

### Cited Findings

| Source | Current official access/terms | Hachi state and barrier |
|---|---|---|
| NHANES | Public XPT/codebook; NCHS limits use to statistical reporting/analysis, forbids attempted identification, identifiable external linkage and disclosure-method/re-identification research; use signifies agreement. [NCHS agreement](https://www.cdc.gov/nchs/policy/data-user-agreement.html) | [Registry](../../../../configs/datasets/nhanes-paxmin-h.toml): `candidate`, public, no held checksum/approved users. Parent's 2026-10-11 OliveTower checkpoint says permitted source download is in progress on GX10; status awaits verified checksum. No #24 experimental branch admitted; weights/unit mapping still required. |
| WESAD | UCI refers licensing to origin; university's current indexed official disclaimer permits **scientific, non-commercial** use with publication credit and supplies a 2.5 GB download. Direct fetched origin body omitted disclaimer/download content, so exact current archive retrieval was not tested. [University source](https://www.eti.uni-siegen.de/ubicomp/home/datasets/icmi18/); [UCI](https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection) | [Registry](../../../../configs/datasets/wesad.toml): `rejected_for_task`; no longitudinal core-task labels. Separate lab stress/PPG branch would need owner agreement and preserved noncommercial constraint. |
| PPG-DaLiA | Public UCI 2.7 GB archive/documentation; **CC BY 4.0**, attribution required for sharing/adaptation. [UCI](https://archive.ics.uci.edu/dataset/495/ppg+dalia) | [Registry](../../../../configs/datasets/ppg-dalia.toml): `rejected_for_task`; raw-PPG branch unadmitted. Data and checkpoint terms, participant split and modality-specific task must be pinned first. |
| Sleep-EDF | PhysioNet explicitly open-access, **Open Data Commons Attribution 1.0**; public files and checksum manifest. [PhysioNet access](https://physionet.org/content/sleep-edfx/1.0.0/) | [Registry](../../../../configs/datasets/sleep-edfx.toml): `rejected_for_task`; separate clinical waveform branch unadmitted. SleepFM adds noncommercial terms; OSF adds montage/missing-channel and checkpoint-provenance gates. |

### Inferences

- Keep all four out of the core illness/recovery training claim. If the parent prioritizes one additional sensor-specific branch, **PPG-DaLiA HR estimation** offers the clearest paired reference task, subject to admission and PaPaGei artifact-term resolution. NHANES is useful only if survey-weighted activity priors answer a concrete question; Sleep-EDF adds a separate PSG task with substantial channel work; WESAD adds lab affect data, not illness. [Dataset facts above](https://archive.ics.uci.edu/dataset/495/ppg+dalia); [Hachi catalog](../../../../docs/RESEARCH.md)

### Gaps

- **Probe status: not admitted, not executed.** No script or experiment issue is created by this note. Registry owners/parent must agree before acquisition or any executable feasibility probe; no recommendation changes admission status. [Hachi registry authority](../../../../docs/RESEARCH.md)
