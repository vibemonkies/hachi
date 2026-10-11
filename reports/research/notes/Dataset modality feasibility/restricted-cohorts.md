# Restricted cohort feasibility: DREAMT, GLOBEM, All of Us, UK Biobank, MiPACT

Checked 2026-10-11 using public official documentation and original publications only. Read `docs/RESEARCH.md` and the five existing registry TOMLs first. No participant data, account creation, agreement submission, download, runtime probe, or registry edit was performed. Current access status below is the local registry/OliveTower coordination status, rather than independent proof of credentials, archive hashes, or executable access. No experimental branch is admitted by this review.

## DREAMT: can raw wrist signals estimate PSG sleep/wake?

### Takeaway

Concrete optional task: participant-held-out PSG sleep/wake estimation from wrist BVP/ACC. This is overnight validation, not illness/recovery training. [Original paper](https://proceedings.mlr.press/v248/wang24a.html)

### Cited Findings

- 100 unique sleep-lab adults, one overnight visit; 23 severe-OSA cases. Original E4 rates: BVP 64 Hz, ACC 32 Hz, EDA/temperature 4 Hz, derived HR 1 Hz; PSG labels 30 seconds. [Release](https://physionet.org/content/dreamt/2.2.0/)
- `data_64Hz` is resampled wrist data; `data_100Hz` includes aligned PSG EEG/EOG/EMG/ECG/respiration/SpO2. Version 2.2 fixes ACC/PSG misalignment; preparation is recoded as wake. [Release](https://physionet.org/content/dreamt/2.2.0/)
- Two participants have 15-minute missing-label gaps; four others one epoch each. Signal-gap frequency is unspecified; alignment can impute. Privacy timestamps start at zero. WatchSleepNet explicitly pretrains on DREAMT. [Release](https://physionet.org/content/dreamt/2.2.0/)
- Registration and project DUA suffice; no training gate is listed. DUA 1.5.0 prohibits shared access, requires prudent security, scientific research use, and public publication code. [Access](https://physionet.org/content/dreamt/2.2.0/), [DUA](https://physionet.org/content/dreamt/view-dua/2.2.0/)

### Inferences

- BVP permits a raw-PPG branch; compatible PSG channels permit sleep-waveform research. Exclude preparation epochs, audit imputation, and audit WatchSleepNet overlap. Watch summaries cannot replace these waveforms. [Release](https://physionet.org/content/dreamt/2.2.0/)

### Gaps

- Registry status is `access_pending`; teammates' signed DUAs and Justin's private T7 destination do not prove completed checksum validation or a working model path. The shared `asus` login remains forbidden under the project's storage policy and no probe was run.
- The documentation does not give whole-release E4 missingness by channel or a verified infection/recovery label. Other foundation-model overlap and exact artifact licenses must be checked against a selected checkpoint before admission.

## GLOBEM: can daily steps forecast next-day steps across people and years?

### Takeaway

Concrete task: next-day observed steps from prior daily steps/sleep, with whole-person splits across yearly appearances. Optional forecasting use awaits individual credentialing. [Dataset](https://physionet.org/content/globem/1.1/)

### Cited Findings

- Four spring waves, 2018–2021: 155/218/137/195 records, **705 participant-waves, 497 unique people**. Authors' “person-years” are ten-week studies, averaging 77.5 ± 8.9 days, not continuous years of physiology. Returning people overlap across years. [Dataset](https://physionet.org/content/globem/1.1/)
- Release contains Fitbit steps/sleep and phone features; no HR/waveforms. Daily and rolling 7/14-day features are provided; dates shift by whole weeks. Weekly wellbeing/depression surveys and pre/post CHIPS are not dated infections. DS1 depression labels are PANAS-derived proxies, not observed PHQ-4. [Dataset](https://physionet.org/content/globem/1.1/)
- Original release paper Table 7 reports 29.2–29.3% missing physical-activity features; sleep-duration features 34.5%, bedtime 36.3%, wake time 36.4%. These are published feature-specific rates, not a measured rate for a newly ingested snapshot. [NeurIPS paper, Table 7](https://proceedings.neurips.cc/paper_files/paper/2022/file/9c7e8a0821dfcb58a9a83cbd37cc8131-Paper-Datasets_and_Benchmarks.pdf)
- A related GLOBEM algorithm paper excludes participants with fewer than two EMAs or >75% missing sensor data, then describes 7.3 ± 2.3% missing features in its selected matrices before median imputation. That narrower denominator does not contradict the release table's higher rates. [Author paper, Table 1 and preprocessing](https://behavioral-data.github.io/resources/pubpdfs/xu2023globemimwut.pdf)
- Individual credentialing, CITI training approval, and project DUA are required; typical approvals take 1–2 weeks. Sharing access is forbidden. [Project](https://physionet.org/content/globem/1.1/), [FAQ](https://www.physionet.org/about/faqs/), [DUA](https://physionet.org/content/globem/view-dua/1.1/)

### Inferences

- The dominant known sample-overlap risk is recurring participants across years; holding out a year alone does not hold out every person. Cross-source participant overlap is unknown. [NeurIPS paper](https://proceedings.neurips.cc/paper_files/paper/2022/file/9c7e8a0821dfcb58a9a83cbd37cc8131-Paper-Datasets_and_Benchmarks.pdf)
- Recompute normalization using training/past data: released participant medians/quantiles do not promise as-of fit windows. [Specification](https://physionet.org/content/globem/1.1/)
- A TimesFM comparison would have to predict exactly the same steps target, with identical missing-target masks and held-out people. A depression score or a paper result cannot substantiate improvement in Hachi's physiology forecasting.

### Gaps

- Registry status remains `candidate`; credentialing is pending per coordination. No credentialed data were inspected; no measured coverage or episode label count is asserted. Shared `asus` storage/use is forbidden.
- A public sample mentioned by upstream code/tutorials does not grant access to the complete cohort. Foundation-model pretraining overlap is unknown until each selected manifest is audited.

## All of Us: does scale translate into paired recovery follow-up?

### Takeaway

Concrete optional task: forecast next-day steps during an EHR-anchored lower-limb-fracture recovery window, using only earlier available wearables. Published paired follow-up demonstrates a route, but fracture-record dates and return of activity are not infection onset or symptom-free recovery labels. [Program wearables paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC13278962/)

### Cited Findings

- CDR v9 officially contains Fitbit records for **more than 68,000 participants**. This is no longer supported only by search snippets; the full program release page was retrieved. It is a count with any Fitbit records, not qualifying cases or person-years. [v9 release](https://support.researchallofus.org/hc/en-us/articles/50653909888788-Our-Largest-Genomic-Dataset-Curated-Data-Repository-version-9)
- Public transformation docs list HR summaries/minute values, daily sleep summaries and sleep levels, daily activity and minute intraday steps. API-derived records are not additionally cleaned by program ETL; device/API imputation may already have occurred. Apple HealthKit arrived in a separate v9 off-cycle dataset in September 2026; its availability is not proof of a modality-compatible or labeled paired cohort. [Transformation specification](https://support.researchallofus.org/hc/en-us/articles/20281023493908-Introduction-to-Wearables-Data-Collection-and-Transformation)
- A v8 characterization counted 59,018 unique Fitbit donors over a **14-year calendar span**, not 14 years per person. It reported 54,509 participants meeting general activity eligibility and 34,378 sleep eligibility, reflecting variable coverage. For fracture follow-up, 2,476 initial EHR-plus-Fitbit candidates became **61** requiring repeated fracture records and ≥300 observed step days across ±180 days. These are v8 analytic counts, not current v9 eligibility. [Paper, eligibility definitions](https://pmc.ncbi.nlm.nih.gov/articles/PMC13278962/)
- Registered Tier dates are privacy transformed; Controlled Tier includes unshifted event dates. Do not combine a tier's shifted wearable dates with independently unshifted external event dates. [Tier definitions](https://www.researchallofus.org/data-tools/data-access/)
- The institutional directory currently lists **University of California, Santa Cruz with Registered and Controlled Tier access**. This establishes a DURA route, not an individual's authorization. Registration still requires institutional affiliation, two-step verification, Login.gov/ID.me identity verification, responsible-conduct training, DUCC acceptance, and a public workspace description. [Directory](https://www.researchallofus.org/institutional-agreements/), [Registration](https://www.researchallofus.org/register/)
- Participant-level records cannot be copied or downloaded out of Workbench, including screenshots. The cloud workspace is the execution boundary; approved aggregate exports have additional disclosure rules. [Access framework](https://support.researchallofus.org/hc/en-us/articles/22346942074132-Data-Access-Framework), [Program FAQ](https://support.researchallofus.org/hc/en-us/articles/52861503885460-Frequently-Asked-Questions)

### Inferences

- This is a genuinely large *potential* training source with an institutionally feasible route, but not presently a permitted Hachi training source. Keep `candidate` until individual approvals and exact schema/label/coverage gates are met.
- Disease codes paired with Fitbit can support an EHR-anchored task; they do not identify exact infection symptom onset, observed well days, or sustained symptom-free recovery. The 61-person fracture example illustrates why the cohort intersection and follow-up must be counted separately. [Paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC13278962/)
- Future model audit must treat BYOD/WEAR as parts of one program with common identities and consider related publications/checkpoints using earlier CDR releases. Cross-cohort overlap with other US studies remains unknown, not proven absent.

### Gaps

- Registry is still `candidate`, with no approved users. No account was created; no institutional contact was sent. Private access, specific workspace authorization, billing, and compute capability are unverified.
- No verified public count of v9 wearable-paired laboratory-confirmed acute infection episodes with dated symptom/recovery surveys was found. EHR availability does not fill that gap. Overall v9 missingness and target-specific follow-up denominators remain unknown.

## UK Biobank: can raw activity form population priors?

### Takeaway

Concrete optional task: estimate hourly activity distributions from wrist accelerometry in held-out participants, using raw wear-time masks. This is population activity research; it does not supply wearable HR or direct PSG labels. New application access is currently paused. [Protocol](https://biobank.ndph.ox.ac.uk/ukb/ukb/docs/PhysicalActivityMonitor.pdf), [Access](https://www.ukbiobank.ac.uk/use-our-data/apply-for-access/)

### Cited Findings

- Current field 90001 lists **112,330 raw bulk items from 103,568 unique participants**: main-study 103,568 items, seasonal repeats 2,632/3,093/3,037. Each item is a seven-day CWA recording. Thus counts of recordings and people differ, and “one week per person” omits repeat observations. [Live field 90001](https://biobank.ndph.ox.ac.uk/ukb/field.cgi?id=90001)
- AX3 records tri-axial acceleration at nominal 100 Hz and ±8 g. Sampling can fluctuate 94–104 Hz; processing interpolates to 100 Hz, leaving >1-second interruptions missing. The protocol describes 103,720 initially collected participants; this historical collection count differs from current released-field availability. [Official protocol](https://biobank.ndph.ox.ac.uk/ukb/ukb/docs/PhysicalActivityMonitor.pdf)
- Seasonal-repeat first cycle had 17% incomplete kits versus <1% in later cycles, attributed to battery performance. Non-wear is ≥60 minutes stationary; summary processing imputes corresponding times on other days. These full-record summaries can use future days relative to a forecasting cutoff. [Protocol](https://biobank.ndph.ox.ac.uk/ukb/ukb/docs/PhysicalActivityMonitor.pdf)
- A 2026 study excluded 3,985 QC failures and 4,067 additional non-wear/coverage failures from 103,611 usable returns, leaving 95,559. Its sleep stages are algorithm-derived from accelerometry, not direct PSG ground truth. These study exclusions are not universal cohort missingness. [Original 2026 analysis](https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1005213)
- The full current application page confirms applications paused while RAP changes restore compliant existing projects; reopening in late 2026 is an intention, not a promised date. Eligible projects must be health-related and in the public interest; applications require research/data-tier/derived-variable descriptions. [Apply page, updated July 2026](https://www.ukbiobank.ac.uk/use-our-data/apply-for-access/)

### Inferences

- Same-person seasonal repeats must remain in the same participant partition. Published full-week wear-time interpolation is unsuitable as an as-of predictor without causal recomputation. [Field](https://biobank.ndph.ox.ac.uk/ukb/field.cgi?id=90001), [Protocol](https://biobank.ndph.ox.ac.uk/ukb/ukb/docs/PhysicalActivityMonitor.pdf)
- Retain as a pending research source. Neither an application interface nor an older paper's approval provides Hachi access; no local/GX10 experiment is admitted. A one-week recording cannot establish daily symptom-free negative labels or recovery follow-up merely because longitudinal EHR outcomes exist.

### Gaps

- Current Hachi status is `candidate`, no approved users; pause now verified from full primary page. Any future application needs the human/institutional route, accepted MTA, permitted storage/platform, and source-owner coordination. Fees and completion time are not estimated here.
- Foundation-model pretraining overlap and cross-source person overlap are unverified. Acceleration-only sleep predictions cannot stand in for PSG labels or Apple sleep-stage summaries without a separately evaluated mapping.

## MiPACT: is Apple Watch physiology obtainable for next-day HR forecasting?

### Takeaway

Concrete task if ever approved: next-day resting-HR forecasting from prior Apple Watch summaries with wear-time masks. Michigan's stated DataDirect route is materially gated; no public whole-cohort release or current team access was established. [Michigan catalog](https://depressioncenter.org/research-services/mobile-technologies-core/mobile-health-datasets)

### Cited Findings

- The original 2021 study enrolled **6,765 eligible people**; **6,454 Michigan Medicine participants** who completed phase 1 formed its primary analysis. It reports the first 90 days, spanning 45 intensive days plus 45 longitudinal days; a three-year monitoring phase was planned, not proven released by that paper. Apple Watch Series 3/4, Omron Evolv BP, and MyDataHelps collected HR, steps, distance, BP; EHR established clinical phenotypes. Median watch wear on worn days was 15.5 hours (IQR 14–17). This is not fixed-rate raw PPG. [Original study abstract](https://pubmed.ncbi.nlm.nih.gov/34711377/)
- Michigan's current catalog additionally describes HRV, respiratory rate, diagnoses/procedures/labs, and quality-of-life/behavior/function surveys, with access through DataDirect. It does not enumerate current paired-label counts, retention, fixed sensor rates, or illness/recovery surveys. [Michigan catalog](https://depressioncenter.org/research-services/mobile-technologies-core/mobile-health-datasets)
- Deidentified DataDirect requires a U-M account, HIPAA/PEERRS training, DUO, at least IRBMED not-regulated determination, faculty position or faculty sponsorship, and signed attestation; offsite use goes through the university VPN. Students' current guide names Precision Health Turbo storage and faculty sponsorship. [Current Medical School tools](https://medresearch.umich.edu/office-research/about-office-research/our-units/data-office-clinical-translational-research/self-serve-data-tools), [Student requirements](https://medresearch.umich.edu/office-research/about-office-research/our-units/data-office-clinical-translational-research/student-access-patient-data)
- An original MiPACT-AFib subgroup paper says supporting raw data will be made available by authors. That is an author-request possibility for that article, not a reusable license or open access to all longitudinal MiPACT records. [Original subgroup paper, data availability](https://www.frontiersin.org/journals/cardiovascular-medicine/articles/10.3389/fcvm.2023.1243574/full)

### Inferences

- The practical collaborator barrier in the registry is justified by institutional DataDirect requirements. “No route whatsoever” would overstate the evidence: an author-mediated collaboration may exist, but no permission, timeline, complete export schema, or whole-cohort grant was found. Remain rejected for the present task pending a real approved route.
- MiPACT's clinical phenotypes do not establish acute infection onset or symptom-free recovery. Three-year study design is not proof of three years of paired follow-up for every person. Sensor HR/steps are a better modality match to Hachi than waveform models, but match alone cannot overcome access.
- Use shared participant identities across any MiPACT publications/substudies if ever admitted. Michigan Genomics/EHR-linked reuse and model-training overlap must be audited; no public source establishes universal disjointness.

### Gaps

- Registry remains `rejected_for_task`; no approved users or team Michigan collaborator. No request, account, agreement, or probe was made.
- Whole-cohort missing-day percentages, current longitudinal completion counts, infection/recovery label intersections, and detailed archive terms were not verified. Wear time conditional on wearing is not an overall missingness percentage.
- Search results for the University of Bath's **Multidimensional Individualised Physical Activity (MIPACT)** trial describe a different study; its public files do not remove Michigan MiPACT's access barrier. The name collision is explicit in that trial's original publication. [Bath trial](https://pmc.ncbi.nlm.nih.gov/articles/PMC7414690/)
