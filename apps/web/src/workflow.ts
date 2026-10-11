import type { Coverage, DataMode, ImportStatus } from "@hachi/contracts";
import type { ReportJob } from "@hachi/contracts";
import type { ReportPair } from "./features/reports/api";

export const sections = [
  "import",
  "overview",
  "forecast",
  "anomaly",
  "symptoms",
  "sleep",
  "replay",
] as const;
export type Section = (typeof sections)[number];

export type ImportSubmission = {
  file: File;
  subjectId: string;
  timeZone: string;
  dataMode: DataMode;
  importId?: string;
};

export type SubjectSelection = {
  subjectId: string;
  imported: ImportStatus | null;
};

export type Workflow =
  | { kind: "empty" }
  | { kind: "uploading"; operationId: string; submission: ImportSubmission }
  | { kind: "importing"; operationId: string; submission: ImportSubmission; status: ImportStatus }
  | { kind: "import-error"; submission: ImportSubmission; message: string; failureCode?: string; action?: string }
  | { kind: "coverage-loading"; operationId: string; subject: SubjectSelection; asOf: string | null; previousCoverage: Coverage | null }
  | { kind: "coverage-error"; subject: SubjectSelection; coverage: Coverage | null; asOf: string; message: string }
  | { kind: "coverage"; subject: SubjectSelection; coverage: Coverage; asOf: string }
  | { kind: "reporting"; operationId: string; subject: SubjectSelection; coverage: Coverage; asOf: string }
  | { kind: "report"; subject: SubjectSelection; coverage: Coverage; asOf: string; reports: ReportPair }
  | { kind: "replay-loading"; operationId: string }
  | { kind: "replay-error"; message: string }
  | { kind: "replay-report"; job: ReportJob };

export type Action =
  | { type: "begin-import"; operationId: string; submission: ImportSubmission }
  | { type: "import-created"; operationId: string; status: ImportStatus }
  | { type: "import-progress"; operationId: string; status: ImportStatus }
  | { type: "import-finished"; operationId: string; coverageOperationId: string; status: ImportStatus }
  | { type: "import-request-failed"; operationId: string; message: string }
  | { type: "begin-subject"; operationId: string; subjectId: string }
  | { type: "coverage-finished"; operationId: string; coverage: Coverage; asOf: string }
  | { type: "coverage-request-failed"; operationId: string; message: string }
  | { type: "retry-initial-coverage"; operationId: string }
  | { type: "refresh-coverage"; operationId: string; asOf: string }
  | { type: "begin-reports"; operationId: string }
  | { type: "reports-finished"; operationId: string; reports: ReportPair }
  | { type: "begin-replay"; operationId: string }
  | { type: "replay-finished"; operationId: string; job: ReportJob }
  | { type: "replay-failed"; operationId: string; message: string }
  | { type: "reset" };

export function reducer(state: Workflow, action: Action): Workflow {
  switch (action.type) {
    case "reset":
      return { kind: "empty" };
    case "begin-import":
      return { kind: "uploading", operationId: action.operationId, submission: action.submission };
    case "import-created":
      return state.kind === "uploading" && state.operationId === action.operationId
        ? { kind: "importing", operationId: action.operationId, submission: state.submission, status: action.status }
        : state;
    case "import-progress":
      return state.kind === "importing" && state.operationId === action.operationId
        ? { ...state, status: action.status }
        : state;
    case "import-finished":
      if (state.kind !== "importing" || state.operationId !== action.operationId) return state;
      if (action.status.state === "succeeded") {
        return {
          kind: "coverage-loading",
          operationId: action.coverageOperationId,
          subject: { subjectId: action.status.subject_id, imported: action.status },
          asOf: null,
          previousCoverage: null,
        };
      }
      return {
        kind: "import-error",
        submission: { ...state.submission, importId: action.status.import_id },
        message: action.status.failure?.message ?? "The Apple Health export could not be imported.",
        failureCode: action.status.failure?.error_code,
        action: action.status.failure?.action,
      };
    case "import-request-failed":
      if ((state.kind === "uploading" || state.kind === "importing") && state.operationId === action.operationId) {
        return { kind: "import-error", submission: state.submission, message: action.message };
      }
      return state;
    case "begin-subject":
      return {
        kind: "coverage-loading",
        operationId: action.operationId,
        subject: { subjectId: action.subjectId, imported: null },
        asOf: null,
        previousCoverage: null,
      };
    case "coverage-finished":
      return state.kind === "coverage-loading" && state.operationId === action.operationId
        ? { kind: "coverage", subject: state.subject, coverage: action.coverage, asOf: action.asOf }
        : state;
    case "coverage-request-failed":
      return state.kind === "coverage-loading" && state.operationId === action.operationId
        ? {
            kind: "coverage-error",
            subject: state.subject,
            coverage: state.previousCoverage,
            asOf: state.asOf ?? "",
            message: action.message,
          }
        : state;
    case "retry-initial-coverage":
      return state.kind === "coverage-error" && !state.coverage
        ? { kind: "coverage-loading", operationId: action.operationId, subject: state.subject, asOf: null, previousCoverage: null }
        : state;
    case "refresh-coverage":
      if (state.kind === "coverage" || state.kind === "report") {
        return {
          kind: "coverage-loading",
          operationId: action.operationId,
          subject: state.subject,
          asOf: action.asOf,
          previousCoverage: state.coverage,
        };
      }
      return state.kind === "coverage-error"
        ? { kind: "coverage-loading", operationId: action.operationId, subject: state.subject, asOf: action.asOf, previousCoverage: state.coverage }
        : state;
    case "begin-reports":
      return (state.kind === "coverage" || state.kind === "report") && state.asOf
        ? {
            kind: "reporting",
            operationId: action.operationId,
            subject: state.subject,
            coverage: state.coverage,
            asOf: state.asOf,
          }
        : state;
    case "begin-replay":
      return { kind: "replay-loading", operationId: action.operationId };
    case "replay-finished":
      return state.kind === "replay-loading" && state.operationId === action.operationId
        ? { kind: "replay-report", job: action.job }
        : state;
    case "replay-failed":
      return state.kind === "replay-loading" && state.operationId === action.operationId
        ? { kind: "replay-error", message: action.message }
        : state;
    case "reports-finished":
      return state.kind === "reporting" && state.operationId === action.operationId
        ? { kind: "report", subject: state.subject, coverage: state.coverage, asOf: state.asOf, reports: action.reports }
        : state;
  }
}
