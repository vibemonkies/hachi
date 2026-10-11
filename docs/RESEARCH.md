# Research catalog and admission decisions

Primary sources checked 2026-10-10. Access descriptions are source-page observations, not proof that the team has downloaded or been authorized to use a dataset. No cohort or checkpoint was downloaded during planning. Record actual file checksums and terms during acquisition.

The prior Apple Health conversation is background, not evidence of availability or accuracy. In particular, open code, open weights, and accessible participant data are three different things. The catalog covers the resources named there and an additional forecasting comparator; it does not claim an exhaustive inventory of every health dataset.

## Dataset routing

| Dataset / primary source | What it contributes | Access and decision |
|---|---|---|
| [PMData](https://datasets.simula.no/pmdata/) / [OSF archive](https://osf.io/vx4bk) | Longitudinal Fitbit data and wellness reports; 16 participants over five months | First development cohort for physiology/fatigue. Public download listed; not an infection cohort. Current site says CC BY 4.0, while the [original paper](https://web-backend.simula.no/sites/default/files/publications/files/3339825.3394926.pdf) says CC BY-NC 4.0. Resolve terms for the exact archive and intended use; do not assume commercial permission. |
| [CovIdentify 1.0.0](https://physionet.org/content/covidentify/1.0.0/) | Daily resting HR/steps, symptom surveys, reported COVID test results | High-priority illness cohort; PhysioNet credentialing/DUA required. Audit who has matched usable labels, onset timing and follow-up. The participant count is not the count of usable positive episodes. |
| [Stanford wearable-infection](https://github.com/StanfordBioinformatics/wearable-infection) | NightSignal/Isolation Forest implementations and example inputs | Baseline reproducibility resource (repository license observed Apache-2.0). Example files are not a representative illness training cohort; verify separate data terms and labels. |
| [CMU Common Cold Project](https://www.cmu.edu/common-cold-project/data/index.html) | Viral-challenge studies, symptom and infection variables | Registration/DUA and analysis-registration requirements. Review study codebooks before defining recovery: follow-up may be too short to observe resolution. Not a continuous Apple Watch cohort. |
| [OpenMHC](https://github.com/AshleyLab/OpenMHC/blob/main/DATASET.md) | Wearable pretraining/benchmark data | Repository still describes release conditional on paper acceptance and separate DUA. Keep access unresolved until actual authorized download succeeds. Do not make initial ingestion depend on it. |
| [NHANES PAXMIN_H](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2013/DataFiles/PAXMIN_H.htm) | Accelerometry linked through participant ids to examination/lab data | Public research branch for activity/lab associations. Survey design and sampling weights matter. Cross-sectional labels cannot teach acute illness onset by concatenation. |
| [WESAD](https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection) | Raw multisensor lab stress/affect data | Separate stress representation task. UCI points to upstream license terms. Stress labels are not illness labels; waveform channels differ from standard Health exports. |
| [PPG-DaLiA](https://archive.ics.uci.edu/dataset/495/ppg+dalia) | Raw PPG/motion with ECG-derived heart-rate reference | Public, UCI lists CC BY 4.0. Useful for waveform/sensor-quality work, not direct training on watch summary values. |
| [Sleep-EDF Expanded](https://physionet.org/content/sleep-edfx/1.0.0/) | Clinical sleep recordings and annotations | Public sleep-stage research branch; incompatible with ordinary watch sleep summaries as direct model input. |
| [DREAMT 2.2.0](https://physionet.org/content/dreamt/2.2.0/) | Wearable signals aligned with sleep labels | Registered users and specified DUA. Sleep-stage branch; check sensor availability before admitting a model. |
| [GLOBEM 1.1](https://physionet.org/content/globem/1.1/) | Longitudinal behavior and wellbeing features | Credentialed access, training and DUA. Potential wellbeing study; not an acute-infection label source by default. |
| [All of Us Workbench](https://www.researchallofus.org/data-tools/workbench/) | Large linked research cohort | Approved workbench access; not an unrestricted local GX10 download. Verify available wearable tables within the authorized environment. |
| [UK Biobank](https://www.ukbiobank.ac.uk/use-our-data/apply-for-access/) | Population activity and clinical outcomes | Access application page currently says applications are paused. Long-term research dependency, not an available demo cohort. |
| [MiPACT](https://depressioncenter.org/research-services/mobile-technologies-core/mobile-health-datasets) | Apple Watch, blood pressure, EHR and surveys | Institutional DataDirect access; suitability/access need confirmation. Future paired-clinical-label branch. |
| Consented personal Apple export | Real target-device history and late transfer/case study | Private data, acquired later. Symptom onset and resolution require separate labels; routine exports are not full raw PPG recordings. |

## Model candidates

| Candidate / primary source | Role in Hachi | Admission gate |
|---|---|---|
| [Chronos-2](https://huggingface.co/amazon/chronos-2), [official code](https://github.com/amazon-science/chronos-forecasting) | First pretrained forecasting experiment, then targeted adaptation | Pin revision and validate GX10 execution, causal covariates, missing-data behavior and intervals. Apache-2.0 model card. Future observed physiology cannot be supplied as a known covariate. |
| [OpenMHC](https://github.com/AshleyLab/OpenMHC), [WBM checkpoint](https://huggingface.co/MyHeartCounts/openmhc-wbm-dp) | Wearable representation candidate feeding trained heads | Code MIT; model terms separate (OpenRAIL). WBM needs CUDA Mamba2 kernels. Pin exact channel order, normalization and missingness semantics, then test on ARM64/GB10. |
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

For each admitted source, record: identifier/version, primary URL/DOI, retrieval date, terms and permitted use/storage, access owner, approved team members where relevant, file checksums, schema/codebook, device/unit mapping, participant and label counts, exclusions, missingness, storage location, task, and split manifest. Distinguish `candidate`, `access_pending`, `downloaded`, `validated`, and `rejected_for_task`.

Keep this manifest free of credentials and personal identifiers. Each trained task must declare the exact datasets it used. Do not redistribute data simply because a repository or download is reachable.
