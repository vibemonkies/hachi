/* Generated from src/hachi/contracts by `make build`. Do not edit by hand. */

/**
 * Opaque id of letters, digits, '_' and '-'; never usable as a path.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Identifier".
 */
export type Identifier = string;
/**
 * Pseudonymous subject id. Identity mapping stays outside Git.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SubjectId".
 */
export type SubjectId = string;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Metric".
 */
export type Metric =
  | "heart_rate"
  | "resting_heart_rate_vendor"
  | "hrv_sdnn"
  | "hrv_rmssd"
  | "respiratory_rate"
  | "oxygen_saturation"
  | "wrist_temperature_deviation"
  | "body_temperature"
  | "steps"
  | "active_energy"
  | "walking_running_distance"
  | "sleep_in_bed"
  | "sleep_asleep_unspecified"
  | "sleep_asleep_core"
  | "sleep_asleep_deep"
  | "sleep_asleep_rem"
  | "sleep_awake";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Unit".
 */
export type Unit =
  "bpm" | "ms" | "breaths_per_min" | "percent" | "degC" | "count" | "kcal" | "m" | "s";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Resolution".
 */
export type Resolution = "hour" | "day";
/**
 * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "UtcDatetime".
 */
export type UtcDatetime = string;
/**
 * IANA timezone name. Local time decides day and sleep boundaries.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "IanaTimezone".
 */
export type IanaTimezone = string;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Aggregation".
 */
export type Aggregation = "mean" | "median" | "min" | "max" | "sum";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "VersionString".
 */
export type VersionString = string;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Text".
 */
export type Text = string;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SchemaVersion".
 */
export type SchemaVersion = "0.1";
/**
 * Whether a document derives from real observations or a synthetic fixture.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "DataMode".
 */
export type DataMode = "real" | "synthetic";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "GitSha".
 */
export type GitSha = string;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "WarningCode".
 */
export type WarningCode =
  | "LOW_COVERAGE"
  | "SPARSE_HISTORY"
  | "UNCALIBRATED_INTERVALS"
  | "DEVICE_SHIFT"
  | "OUT_OF_DISTRIBUTION"
  | "STALE_DATA";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Sha256".
 */
export type Sha256 = string;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ApiErrorCode".
 */
export type ApiErrorCode =
  | "VALIDATION_FAILED"
  | "SCHEMA_VERSION_UNSUPPORTED"
  | "NOT_FOUND"
  | "CONFLICT"
  | "PAYLOAD_TOO_LARGE"
  | "INTERNAL_ERROR";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SourceKind".
 */
export type SourceKind =
  | "watch"
  | "phone"
  | "ring"
  | "fitness_tracker"
  | "third_party_app"
  | "manual_entry"
  | "research_device"
  | "unknown";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "TaskName".
 */
export type TaskName =
  "physiology_forecast" | "anomaly" | "illness_onset" | "recovery" | "alertness";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "UnavailableReason".
 */
export type UnavailableReason =
  | "NO_VALIDATED_ILLNESS_ARTIFACT"
  | "NO_VALIDATED_RECOVERY_ARTIFACT"
  | "NO_ARTIFACT_FOR_TASK"
  | "INSUFFICIENT_HISTORY"
  | "NO_SUPPORTED_METRICS"
  | "METRIC_NOT_OBSERVED"
  | "LOW_COVERAGE"
  | "ONGOING_EPISODE"
  | "NO_ONGOING_EPISODE"
  | "LABELS_UNAVAILABLE"
  | "DATA_ACCESS_PENDING";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ReportErrorCode".
 */
export type ReportErrorCode =
  | "ARTIFACT_INTEGRITY_FAILED"
  | "ARTIFACT_INCOMPATIBLE"
  | "DATA_READ_FAILED"
  | "INFERENCE_FAILED"
  | "INFERENCE_TIMEOUT"
  | "GPU_UNAVAILABLE"
  | "INTERNAL_ERROR";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "FeatureName".
 */
export type FeatureName = string;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ImportErrorCode".
 */
export type ImportErrorCode =
  | "FILE_TOO_LARGE"
  | "ARCHIVE_UNSAFE"
  | "MALFORMED_XML"
  | "NOT_AN_APPLE_HEALTH_EXPORT"
  | "UNSUPPORTED_FORMAT"
  | "INTERNAL_ERROR";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "RecordIssueCode".
 */
export type RecordIssueCode =
  | "UNKNOWN_UNIT"
  | "INVALID_TIMESTAMP"
  | "END_BEFORE_START"
  | "VALUE_OUT_OF_RANGE"
  | "MISSING_FIELD";
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "LabelSource".
 */
export type LabelSource = "study_survey" | "self_report" | "clinician" | "derived";
/**
 * Local wall-clock time, without an offset.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "LocalDateTime".
 */
export type LocalDateTime = string;
/**
 * An outcome-table row: a symptom episode, a test result, or a period of unknown status.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Outcome".
 */
export type Outcome = SymptomEpisode | TestResult | StatusUnknown;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Probability".
 */
export type Probability = number;
/**
 * Path relative to an approved storage root; no '..' segments.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "RelativePath".
 */
export type RelativePath = string;
/**
 * POST /v1/reports body. Alertness goes through POST /v1/scenarios instead.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ReportRequest".
 */
export type ReportRequest =
  | PhysiologyForecastHourlyRequest
  | PhysiologyForecastDailyRequest
  | AnomalyRequest
  | IllnessOnsetRequest
  | RecoveryRequest;
/**
 * A report outcome. Narrow on `status`, then on `task`.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ReportResult".
 */
export type ReportResult =
  | PhysiologyForecastResult
  | AnomalyResult
  | IllnessOnsetResult
  | RecoveryResult
  | AlertnessResult
  | UnavailableResult
  | ErrorResult;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SelfReportEntry".
 */
export type SelfReportEntry =
  | SymptomOnsetEntry
  | SymptomCheckInEntry
  | SymptomResolutionEntry
  | TestResultEntry
  | AlertnessRatingEntry
  | PvtResultEntry
  | ConfounderEntry;
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Symptom".
 */
export type Symptom =
  | "fever"
  | "chills"
  | "cough"
  | "sore_throat"
  | "runny_nose"
  | "congestion"
  | "headache"
  | "fatigue"
  | "body_aches"
  | "shortness_of_breath"
  | "loss_of_taste_or_smell"
  | "nausea"
  | "diarrhea"
  | "other";
/**
 * 1 mild, 2 moderate, 3 severe.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Severity".
 */
export type Severity = 1 | 2 | 3;

/**
 * Hachi contracts v0.1. Generated from src/hachi/contracts.
 */
export interface HachiContracts {
  [k: string]: unknown | undefined;
}
/**
 * One metric summarised over an hourly or local-day bin.
 *
 * An empty bin is missing (`value` null with a `null_reason`), never zero.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Aggregate".
 */
export interface Aggregate {
  dataset_id: Identifier;
  subject_id: SubjectId;
  metric: Metric;
  unit: Unit;
  resolution: Resolution;
  interval_start_utc: UtcDatetime;
  interval_end_utc: UtcDatetime;
  /**
   * Local calendar day. Required for day bins.
   */
  local_date: string | null;
  /**
   * Timezone of local_date. Required for days.
   */
  tz_name: IanaTimezone | null;
  aggregation: Aggregation;
  value: number | null;
  null_reason: ("no_observations" | "insufficient_coverage" | "quarantined") | null;
  observed_count: number;
  /**
   * Fraction of the bin with usable observations.
   */
  coverage: number;
  source_ids: Identifier[];
  pipeline_version: VersionString;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AlertBurden".
 */
export interface AlertBurden {
  false_alert_episodes_per_30_healthy_days: number;
  evaluation_report: Text;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AlertnessCurve".
 */
export interface AlertnessCurve {
  schedule_id: Identifier;
  /**
   * @minItems 2
   */
  points: [AlertnessPoint, AlertnessPoint, ...AlertnessPoint[]];
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AlertnessPoint".
 */
export interface AlertnessPoint {
  time_utc: UtcDatetime;
  value: number;
}
/**
 * A simulation shows assumptions, never an accuracy claim.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AlertnessPayload".
 */
export interface AlertnessPayload {
  mode: "simulation" | "validated_prediction";
  /**
   * Equations or implementation, with citation.
   */
  model_description: string;
  scale: AlertnessScale;
  tz_name: IanaTimezone;
  assumptions: ScenarioAssumptions;
  /**
   * @minItems 1
   */
  curves: [AlertnessCurve, ...AlertnessCurve[]];
  /**
   * Required for validated_prediction; must be null for a simulation.
   */
  validation: AlertnessValidation | null;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AlertnessScale".
 */
export interface AlertnessScale {
  name: Text;
  unit: Text;
  minimum: number;
  maximum: number;
  higher_is_more_alert: boolean;
}
/**
 * Explicit inputs the simulation depends on. Nothing is silently defaulted.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ScenarioAssumptions".
 */
export interface ScenarioAssumptions {
  /**
   * Sleep obtained in the 24 hours before the first scenario bedtime.
   */
  prior_sleep_hours: number;
  caffeine: "none" | "not_modeled";
  light_exposure: "not_modeled";
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AlertnessValidation".
 */
export interface AlertnessValidation {
  /**
   * Aggregate evaluation report backing the prediction.
   */
  report: string;
  metric: Text;
  value: number;
  n_observations: number;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AlertnessRatingEntry".
 */
export interface AlertnessRatingEntry {
  entry_id: Identifier;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  entered_at_utc: string;
  /**
   * entry_id of the version this entry corrects; null for an original entry. Corrections are appended, never edited in place, so an earlier as_of still sees what was known then. An episode is identified by its original onset's entry_id.
   */
  supersedes?: Identifier | null;
  kind: "alertness_rating";
  rated_at_utc: UtcDatetime;
  /**
   * Karolinska Sleepiness Scale: 1 extremely alert, 9 very sleepy.
   */
  scale: "kss_1_9";
  value: number;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AlertnessResult".
 */
export interface AlertnessResult {
  schema_version: SchemaVersion;
  report_id: Identifier;
  subject_id: SubjectId;
  as_of: UtcDatetime;
  data_mode: DataMode;
  generated_at_utc: UtcDatetime;
  git_sha: GitSha;
  warnings: ResultWarning[];
  replay: ReplayInfo | null;
  status: "ok";
  provenance: Provenance;
  task: "alertness";
  alertness: AlertnessPayload;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ResultWarning".
 */
export interface ResultWarning {
  code: WarningCode;
  message: Text;
}
/**
 * Present when a saved result is shown instead of a live run.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ReplayInfo".
 */
export interface ReplayInfo {
  source_report_id: Identifier;
  recorded_at_utc: UtcDatetime;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Provenance".
 */
export interface Provenance {
  /**
   * Required for every task except an alertness simulation.
   */
  dataset_snapshot: DatasetSnapshotRef | null;
  artifact: ArtifactRef;
  feature_coverage: FeatureCoverage[];
}
/**
 * Identifies the exact dataset snapshot a document was computed from.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "DatasetSnapshotRef".
 */
export interface DatasetSnapshotRef {
  dataset_id: Identifier;
  dataset_version: VersionString;
  snapshot_sha256: Sha256;
}
/**
 * Identifies an immutable model artifact directory by id and checksum.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ArtifactRef".
 */
export interface ArtifactRef {
  artifact_id: Identifier;
  artifact_sha256: Sha256;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "FeatureCoverage".
 */
export interface FeatureCoverage {
  metric: Metric;
  /**
   * Fraction of the lookback window with usable observations.
   */
  coverage: number;
}
/**
 * Deviation from the person's own baseline. This is not an illness probability.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AnomalyPayload".
 */
export interface AnomalyPayload {
  /**
   * What the score measures; higher is more unusual.
   */
  score_definition: string;
  alert_state: "no_alert" | "alert" | "abstained";
  score: number | null;
  alert_threshold: number;
  baseline_window_start_utc: UtcDatetime;
  baseline_window_end_utc: UtcDatetime;
  changed_features: ChangedFeature[];
  timeline: AnomalyTimelinePoint[];
  /**
   * Null until measured.
   */
  observed_alert_burden: AlertBurden | null;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ChangedFeature".
 */
export interface ChangedFeature {
  metric: Metric;
  unit: Unit;
  observed: number;
  baseline_median: number;
  robust_z: number;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AnomalyTimelinePoint".
 */
export interface AnomalyTimelinePoint {
  interval_start_utc: UtcDatetime;
  interval_end_utc: UtcDatetime;
  /**
   * Null when the detector abstained.
   */
  score: number | null;
  alert: boolean;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AnomalyRequest".
 */
export interface AnomalyRequest {
  schema_version: SchemaVersion;
  subject_id: SubjectId;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  as_of: string;
  task: "anomaly";
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "AnomalyResult".
 */
export interface AnomalyResult {
  schema_version: SchemaVersion;
  report_id: Identifier;
  subject_id: SubjectId;
  as_of: UtcDatetime;
  data_mode: DataMode;
  generated_at_utc: UtcDatetime;
  git_sha: GitSha;
  warnings: ResultWarning[];
  replay: ReplayInfo | null;
  status: "ok";
  provenance: Provenance;
  task: "anomaly";
  anomaly: AnomalyPayload;
}
/**
 * Body of every non-2xx API response.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ApiError".
 */
export interface ApiError {
  schema_version: SchemaVersion;
  error_code: ApiErrorCode;
  message: Text;
  request_id: Identifier;
  field_issues: FieldIssue[];
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "FieldIssue".
 */
export interface FieldIssue {
  path: string;
  message: Text;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "CalibrationRef".
 */
export interface CalibrationRef {
  cohort: Text;
  version: VersionString;
  method: Text;
}
/**
 * Something that can move physiology without illness.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ConfounderEntry".
 */
export interface ConfounderEntry {
  entry_id: Identifier;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  entered_at_utc: string;
  /**
   * entry_id of the version this entry corrects; null for an original entry. Corrections are appended, never edited in place, so an earlier as_of still sees what was known then. An episode is identified by its original onset's entry_id.
   */
  supersedes?: Identifier | null;
  kind: "confounder";
  factor:
    | "alcohol"
    | "vaccination"
    | "travel"
    | "intense_exercise"
    | "sleep_loss"
    | "medication"
    | "other";
  occurred_earliest_utc: UtcDatetime;
  occurred_latest_utc: UtcDatetime;
}
/**
 * GET /v1/subjects/{id}/coverage response: what data exists and what it can support.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Coverage".
 */
export interface Coverage {
  schema_version: SchemaVersion;
  subject_id: SubjectId;
  data_mode: DataMode;
  generated_at_utc: UtcDatetime;
  dataset_snapshot: DatasetSnapshotRef | null;
  history: "empty" | "insufficient" | "sufficient";
  span_start_utc: UtcDatetime | null;
  span_end_utc: UtcDatetime | null;
  metrics: MetricCoverage[];
  task_support: TaskSupport[];
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "MetricCoverage".
 */
export interface MetricCoverage {
  metric: Metric;
  unit: Unit;
  first_utc: UtcDatetime;
  last_utc: UtcDatetime;
  days_with_data: number;
  /**
   * Fraction of the subject's span with usable observations of this metric.
   */
  coverage: number;
  longest_gap_hours: number;
  /**
   * @minItems 1
   */
  source_kinds: [SourceKind, ...SourceKind[]];
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "TaskSupport".
 */
export interface TaskSupport {
  task: TaskName;
  supported: boolean;
  reason_code: UnavailableReason | null;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ErrorResult".
 */
export interface ErrorResult {
  schema_version: SchemaVersion;
  report_id: Identifier;
  subject_id: SubjectId;
  as_of: UtcDatetime;
  data_mode: DataMode;
  generated_at_utc: UtcDatetime;
  git_sha: GitSha;
  warnings: ResultWarning[];
  replay: ReplayInfo | null;
  status: "error";
  task: TaskName;
  error_code: ReportErrorCode;
  /**
   * Safe to show; contains no participant data.
   */
  message: string;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Exclusion".
 */
export interface Exclusion {
  subject_id: SubjectId;
  /**
   * Null excludes the whole subject.
   */
  record_id: Identifier | null;
  reason: Text;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ForecastPayload".
 */
export interface ForecastPayload {
  resolution: Resolution;
  /**
   * Required for day resolution.
   */
  tz_name: IanaTimezone | null;
  /**
   * @minItems 1
   */
  series: [ForecastSeries, ...ForecastSeries[]];
  unavailable_metrics: MetricUnavailable[];
}
/**
 * A forecast with intervals, or a point-only forecast (`interval_calibration: "none"`).
 *
 * A point-only series has no interval and makes no coverage claim: every point's `lower` and
 * `upper` and the series' `nominal_coverage` are null. Draw it as points, never as a band.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ForecastSeries".
 */
export interface ForecastSeries {
  metric: Metric;
  unit: Unit;
  /**
   * Intended probability that the outcome falls in [lower, upper]. Null exactly for a point-only forecast.
   */
  nominal_coverage: number | null;
  /**
   * 'validated' only when held-out coverage was measured for this artifact; 'none' for a point-only forecast, which has no interval.
   */
  interval_calibration: "validated" | "uncalibrated" | "none";
  baseline: PersonalBaseline | null;
  /**
   * @minItems 1
   */
  points: [ForecastPoint, ...ForecastPoint[]];
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "PersonalBaseline".
 */
export interface PersonalBaseline {
  value: number;
  definition: Text;
  window_start_utc: UtcDatetime;
  window_end_utc: UtcDatetime;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ForecastPoint".
 */
export interface ForecastPoint {
  interval_start_utc: UtcDatetime;
  interval_end_utc: UtcDatetime;
  /**
   * Local day for day-resolution points.
   */
  local_date: string | null;
  median: number;
  /**
   * Null exactly for a point-only forecast.
   */
  lower: number | null;
  /**
   * Null exactly for a point-only forecast.
   */
  upper: number | null;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "MetricUnavailable".
 */
export interface MetricUnavailable {
  metric: Metric;
  reason_code: UnavailableReason;
}
/**
 * GET /healthz response. Contains no participant data.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "HealthStatus".
 */
export interface HealthStatus {
  schema_version: SchemaVersion;
  status: "ok" | "degraded";
  git_sha: GitSha;
  artifacts: ArtifactRef[];
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "IllnessOnsetPayload".
 */
export interface IllnessOnsetPayload {
  horizon_hours: 24 | 48 | 72;
  /**
   * Probability of a new symptom onset within the horizon after as_of.
   */
  onset_probability: number;
  target_definition: Text;
  calibration: CalibrationRef;
  distribution_status: "in_distribution" | "out_of_distribution" | "unknown";
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "IllnessOnsetRequest".
 */
export interface IllnessOnsetRequest {
  schema_version: SchemaVersion;
  subject_id: SubjectId;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  as_of: string;
  task: "illness_onset";
  horizon_hours: 24 | 48 | 72;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "IllnessOnsetResult".
 */
export interface IllnessOnsetResult {
  schema_version: SchemaVersion;
  report_id: Identifier;
  subject_id: SubjectId;
  as_of: UtcDatetime;
  data_mode: DataMode;
  generated_at_utc: UtcDatetime;
  git_sha: GitSha;
  warnings: ResultWarning[];
  replay: ReplayInfo | null;
  status: "ok";
  provenance: Provenance;
  task: "illness_onset";
  illness_onset: IllnessOnsetPayload;
}
/**
 * Every record seen lands in exactly one bucket.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ImportCounts".
 */
export interface ImportCounts {
  records_seen: number;
  records_accepted: number;
  records_duplicate: number;
  /**
   * Valid records of a type Hachi does not use.
   */
  records_unsupported: number;
  records_rejected: number;
  /**
   * Records held back instead of guessed, e.g. an unknown unit.
   */
  records_quarantined: number;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ImportFailure".
 */
export interface ImportFailure {
  error_code: ImportErrorCode;
  message: Text;
  /**
   * What the person can do next.
   */
  action: string;
}
/**
 * GET /v1/imports/{id} response.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ImportStatus".
 */
export interface ImportStatus {
  schema_version: SchemaVersion;
  import_id: Identifier;
  subject_id: SubjectId;
  data_mode: DataMode;
  source_format:
    "apple_health_export_zip" | "apple_health_export_xml" | "pmdata_archive" | "synthetic";
  declared_tz_name: IanaTimezone;
  state: "pending" | "running" | "succeeded" | "failed";
  created_at_utc: UtcDatetime;
  updated_at_utc: UtcDatetime;
  counts: ImportCounts | null;
  record_issues: RecordIssueSummary[];
  failure: ImportFailure | null;
}
/**
 * Aggregate count per issue. Raw records never appear in API responses.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "RecordIssueSummary".
 */
export interface RecordIssueSummary {
  disposition: "rejected" | "quarantined";
  code: RecordIssueCode;
  count: number;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ModelRef".
 */
export interface ModelRef {
  model_id: Identifier;
  /**
   * Upstream checkpoint, e.g. a Hub repo id.
   */
  checkpoint_source: Text | null;
  checkpoint_revision: VersionString | null;
  license: Text | null;
}
/**
 * One source measurement, as recorded, in canonical units.
 *
 * `source_id` is a pseudonymous stable id used for deduplication precedence. Raw source
 * names (for example "Alex's Apple Watch") can contain personal names and stay out of
 * canonical tables.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "Observation".
 */
export interface Observation {
  dataset_id: Identifier;
  subject_id: SubjectId;
  record_id: Identifier;
  source_kind: SourceKind;
  source_id: Identifier;
  device_model: string | null;
  metric: Metric;
  value: number;
  unit: Unit;
  start_utc: UtcDatetime;
  end_utc: UtcDatetime;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  available_at_utc: string;
  /**
   * 'observed' when the source records availability (e.g. Apple creationDate); 'assumed' when a documented rule supplied it.
   */
  availability: "observed" | "assumed";
  /**
   * Id of the documented availability assumption. Required iff assumed.
   */
  availability_rule: Identifier | null;
  tz_name: IanaTimezone | null;
  utc_offset_minutes: number | null;
  tz_provenance: "record_offset" | "user_declared" | "dataset_documentation" | "unknown";
}
/**
 * A labeled symptom episode. Onset and resolution are intervals expressing uncertainty.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SymptomEpisode".
 */
export interface SymptomEpisode {
  kind: "symptom_episode";
  dataset_id: Identifier;
  subject_id: SubjectId;
  episode_id: Identifier;
  onset_earliest_utc: UtcDatetime;
  onset_latest_utc: UtcDatetime;
  resolution_status: "resolved" | "right_censored";
  resolution_earliest_utc: UtcDatetime | null;
  resolution_latest_utc: UtcDatetime | null;
  /**
   * Id of the prespecified resolution endpoint. Required when resolved.
   */
  resolution_definition: Identifier | null;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  last_follow_up_utc: string;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  observed_at_utc: string;
  label_source: LabelSource;
  confidence: "confirmed" | "probable" | "uncertain";
}
/**
 * A diagnostic test. A test date is not a symptom onset and is never used as one.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "TestResult".
 */
export interface TestResult {
  kind: "test_result";
  dataset_id: Identifier;
  subject_id: SubjectId;
  test_id: Identifier;
  episode_id: Identifier | null;
  pathogen: "sars_cov_2" | "influenza" | "rsv" | "other" | "unknown";
  method: "pcr" | "antigen" | "other" | "unknown";
  result: "positive" | "negative" | "inconclusive";
  collected_earliest_utc: UtcDatetime;
  collected_latest_utc: UtcDatetime;
  observed_at_utc: UtcDatetime;
  label_source: LabelSource;
}
/**
 * An interval without outcome information. Unknown is not healthy.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "StatusUnknown".
 */
export interface StatusUnknown {
  kind: "status_unknown";
  dataset_id: Identifier;
  subject_id: SubjectId;
  start_utc: UtcDatetime;
  end_utc: UtcDatetime;
  reason: "no_survey" | "lost_to_follow_up" | "withdrawn" | "other";
  note: Text | null;
}
/**
 * Whatever was resolved before a result became unavailable or failed.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "PartialProvenance".
 */
export interface PartialProvenance {
  dataset_snapshot: DatasetSnapshotRef | null;
  artifact: ArtifactRef | null;
  feature_coverage: FeatureCoverage[];
}
/**
 * Forecast the next completed local day after `as_of`.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "PhysiologyForecastDailyRequest".
 */
export interface PhysiologyForecastDailyRequest {
  schema_version: SchemaVersion;
  subject_id: SubjectId;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  as_of: string;
  task: "physiology_forecast";
  /**
   * Metrics to forecast; null requests every supported metric.
   */
  metrics?: [Metric, ...Metric[]] | null;
  resolution: "day";
  horizon_days?: 1;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "PhysiologyForecastHourlyRequest".
 */
export interface PhysiologyForecastHourlyRequest {
  schema_version: SchemaVersion;
  subject_id: SubjectId;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  as_of: string;
  task: "physiology_forecast";
  /**
   * Metrics to forecast; null requests every supported metric.
   */
  metrics?: [Metric, ...Metric[]] | null;
  resolution: "hour";
  horizon_hours?: number;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "PhysiologyForecastResult".
 */
export interface PhysiologyForecastResult {
  schema_version: SchemaVersion;
  report_id: Identifier;
  subject_id: SubjectId;
  as_of: UtcDatetime;
  data_mode: DataMode;
  generated_at_utc: UtcDatetime;
  git_sha: GitSha;
  warnings: ResultWarning[];
  replay: ReplayInfo | null;
  status: "ok";
  provenance: Provenance;
  task: "physiology_forecast";
  forecast: ForecastPayload;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "PvtResultEntry".
 */
export interface PvtResultEntry {
  entry_id: Identifier;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  entered_at_utc: string;
  /**
   * entry_id of the version this entry corrects; null for an original entry. Corrections are appended, never edited in place, so an earlier as_of still sees what was known then. An episode is identified by its original onset's entry_id.
   */
  supersedes?: Identifier | null;
  kind: "pvt_result";
  started_at_utc: UtcDatetime;
  duration_seconds: number;
  trials: number;
  mean_reaction_time_ms: number;
  /**
   * Responses slower than 500 ms.
   */
  lapses: number;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "RecoveryPayload".
 */
export interface RecoveryPayload {
  episode_id: Identifier;
  endpoint_definition: Text;
  /**
   * @minItems 2
   */
  survival: [SurvivalPoint, SurvivalPoint, ...SurvivalPoint[]];
  /**
   * Null when the median is not reached within supported follow-up.
   */
  median_days_after_as_of: number | null;
  supported_follow_up_days: number;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SurvivalPoint".
 */
export interface SurvivalPoint {
  days_after_as_of: number;
  probability_still_symptomatic: Probability;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "RecoveryRequest".
 */
export interface RecoveryRequest {
  schema_version: SchemaVersion;
  subject_id: SubjectId;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  as_of: string;
  task: "recovery";
  episode_id: Identifier;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "RecoveryResult".
 */
export interface RecoveryResult {
  schema_version: SchemaVersion;
  report_id: Identifier;
  subject_id: SubjectId;
  as_of: UtcDatetime;
  data_mode: DataMode;
  generated_at_utc: UtcDatetime;
  git_sha: GitSha;
  warnings: ResultWarning[];
  replay: ReplayInfo | null;
  status: "ok";
  provenance: Provenance;
  task: "recovery";
  recovery: RecoveryPayload;
}
/**
 * POST /v1/reports and GET /v1/reports/{id} response. Poll until state is completed.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ReportJob".
 */
export interface ReportJob {
  schema_version: SchemaVersion;
  report_id: Identifier;
  state: "queued" | "running" | "completed";
  submitted_at_utc: UtcDatetime;
  updated_at_utc: UtcDatetime;
  request: ReportRequest;
  result: ReportResult | null;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "UnavailableResult".
 */
export interface UnavailableResult {
  schema_version: SchemaVersion;
  report_id: Identifier;
  subject_id: SubjectId;
  as_of: UtcDatetime;
  data_mode: DataMode;
  generated_at_utc: UtcDatetime;
  git_sha: GitSha;
  warnings: ResultWarning[];
  replay: ReplayInfo | null;
  status: "unavailable";
  task: TaskName;
  reason_code: UnavailableReason;
  /**
   * What would have to exist for this result to become available.
   *
   * @minItems 1
   */
  requirements: [Text, ...Text[]];
  provenance: PartialProvenance | null;
}
/**
 * Everything needed to trace a prediction back to its code, data, model and environment.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "RunManifest".
 */
export interface RunManifest {
  schema_version: SchemaVersion;
  run_id: Identifier;
  created_at_utc: UtcDatetime;
  git_sha: GitSha;
  /**
   * True when the run used uncommitted code.
   */
  git_dirty: boolean;
  config_sha256: Sha256;
  dataset_snapshot: DatasetSnapshotRef;
  split_manifest_sha256: Sha256;
  task: TaskName;
  /**
   * @minItems 1
   */
  feature_order: [FeatureName, ...FeatureName[]];
  model: ModelRef;
  /**
   * Digest of the lockfile or container image.
   */
  environment_sha256: string;
  seed: number;
  /**
   * Null for runs that export no artifact.
   */
  artifact: ArtifactRef | null;
  metrics_paths: RelativePath[];
}
/**
 * POST /v1/scenarios body: compare candidate sleep schedules for one subject.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "ScenarioRequest".
 */
export interface ScenarioRequest {
  schema_version: SchemaVersion;
  subject_id: SubjectId;
  tz_name: IanaTimezone;
  /**
   * @minItems 1
   * @maxItems 4
   */
  schedules:
    | [SleepSchedule]
    | [SleepSchedule, SleepSchedule]
    | [SleepSchedule, SleepSchedule, SleepSchedule]
    | [SleepSchedule, SleepSchedule, SleepSchedule, SleepSchedule];
  assumptions: ScenarioAssumptions;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SleepSchedule".
 */
export interface SleepSchedule {
  schedule_id: Identifier;
  bedtime_local: LocalDateTime;
  wake_time_local: LocalDateTime;
}
/**
 * Symptoms began somewhere in [onset_earliest_utc, onset_latest_utc].
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SymptomOnsetEntry".
 */
export interface SymptomOnsetEntry {
  entry_id: Identifier;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  entered_at_utc: string;
  /**
   * entry_id of the version this entry corrects; null for an original entry. Corrections are appended, never edited in place, so an earlier as_of still sees what was known then. An episode is identified by its original onset's entry_id.
   */
  supersedes?: Identifier | null;
  kind: "symptom_onset";
  onset_earliest_utc: UtcDatetime;
  onset_latest_utc: UtcDatetime;
  /**
   * @minItems 1
   */
  symptoms: [Symptom, ...Symptom[]];
  severity: Severity;
}
/**
 * Status over a period. A check-in records absence too; no check-in means unknown.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SymptomCheckInEntry".
 */
export interface SymptomCheckInEntry {
  entry_id: Identifier;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  entered_at_utc: string;
  /**
   * entry_id of the version this entry corrects; null for an original entry. Corrections are appended, never edited in place, so an earlier as_of still sees what was known then. An episode is identified by its original onset's entry_id.
   */
  supersedes?: Identifier | null;
  kind: "symptom_checkin";
  period_start_utc: UtcDatetime;
  period_end_utc: UtcDatetime;
  symptoms_present: boolean;
  symptoms: Symptom[];
  severity: Severity | null;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SymptomResolutionEntry".
 */
export interface SymptomResolutionEntry {
  entry_id: Identifier;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  entered_at_utc: string;
  /**
   * entry_id of the version this entry corrects; null for an original entry. Corrections are appended, never edited in place, so an earlier as_of still sees what was known then. An episode is identified by its original onset's entry_id.
   */
  supersedes?: Identifier | null;
  kind: "symptom_resolution";
  onset_entry_id: Identifier;
  resolved_earliest_utc: UtcDatetime;
  resolved_latest_utc: UtcDatetime;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "TestResultEntry".
 */
export interface TestResultEntry {
  entry_id: Identifier;
  /**
   * UTC instant in ISO 8601. Naive and non-UTC timestamps are rejected.
   */
  entered_at_utc: string;
  /**
   * entry_id of the version this entry corrects; null for an original entry. Corrections are appended, never edited in place, so an earlier as_of still sees what was known then. An episode is identified by its original onset's entry_id.
   */
  supersedes?: Identifier | null;
  kind: "test_result";
  pathogen: "sars_cov_2" | "influenza" | "rsv" | "other" | "unknown";
  method: "pcr" | "antigen" | "other" | "unknown";
  result: "positive" | "negative" | "inconclusive";
  collected_earliest_utc: UtcDatetime;
  collected_latest_utc: UtcDatetime;
}
/**
 * GET /v1/subjects/{id}/observations response: every stored entry, in recording order.
 *
 * The whole history comes in one response and may be empty. The 1-200 bound applies only
 * to a single POST batch (`SelfReportRequest`). Entries are immutable once recorded.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SelfReportHistory".
 */
export interface SelfReportHistory {
  schema_version: SchemaVersion;
  subject_id: SubjectId;
  entries: SelfReportEntry[];
}
/**
 * POST /v1/subjects/{id}/observations body.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SelfReportRequest".
 */
export interface SelfReportRequest {
  schema_version: SchemaVersion;
  /**
   * @minItems 1
   * @maxItems 200
   */
  entries: [SelfReportEntry, ...SelfReportEntry[]];
}
/**
 * Participant-grouped partitions and rolling-origin settings for one evaluation fold.
 *
 * Immutable once `test_opened_at_utc` is set; changes produce a new manifest id.
 *
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "SplitManifest".
 */
export interface SplitManifest {
  schema_version: SchemaVersion;
  manifest_id: Identifier;
  created_at_utc: UtcDatetime;
  dataset_snapshot: DatasetSnapshotRef;
  task: TaskName;
  fold: number | null;
  n_folds: number | null;
  /**
   * @minItems 1
   */
  train_subjects: [SubjectId, ...SubjectId[]];
  validation_subjects: SubjectId[];
  test_subjects: SubjectId[];
  exclusions: Exclusion[];
  lookback_hours: number;
  horizon_hours: number;
  /**
   * Gap purged between the cutoff and the first target window.
   */
  embargo_hours: number;
  cutoff_stride_hours: number;
  min_history_hours: number;
  evaluation_window: TimeWindow | null;
  seed: number;
  test_opened_at_utc: UtcDatetime | null;
}
/**
 * This interface was referenced by `HachiContracts`'s JSON-Schema
 * via the `definition` "TimeWindow".
 */
export interface TimeWindow {
  start_utc: UtcDatetime;
  end_utc: UtcDatetime;
}
