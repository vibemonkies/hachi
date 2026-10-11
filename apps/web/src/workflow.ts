import type { Coverage, DataMode, ImportStatus } from "@hachi/contracts";
import type { ReportPair } from "./features/reports/api";

export const sections = [
  "import",
  "overview",
  "forecast",
  "anomaly",
  "symptoms",
  "sleep",
] as const;
export type Section = (typeof sections)[number];
export type Point = { utc: string; value: number | null; lower?: number; upper?: number };
export type Panel = { kind: "illustrative"; points: Point[] } | { kind: "unavailable"; reason: string };

export type ImportSubmission = {
  file: File;
  subjectId: string;
  timeZone: string;
  dataMode: DataMode;
};

export type Workflow =
  | { kind: "empty" }
  | { kind: "uploading"; operationId: string; submission: ImportSubmission }
  | { kind: "importing"; operationId: string; submission: ImportSubmission; status: ImportStatus }
  | { kind: "import-error"; submission: ImportSubmission; message: string }
  | { kind: "coverage-loading"; operationId: string; imported: ImportStatus; asOf: string | null; previousCoverage: Coverage | null }
  | { kind: "coverage-error"; imported: ImportStatus; coverage: Coverage | null; asOf: string; message: string }
  | { kind: "coverage"; imported: ImportStatus; coverage: Coverage; asOf: string }
  | { kind: "reporting"; operationId: string; imported: ImportStatus; coverage: Coverage; asOf: string }
  | { kind: "report"; imported: ImportStatus; coverage: Coverage; asOf: string; reports: ReportPair };

export type Action =
  | { type: "begin-import"; operationId: string; submission: ImportSubmission }
  | { type: "import-created"; operationId: string; status: ImportStatus }
  | { type: "import-progress"; operationId: string; status: ImportStatus }
  | { type: "import-finished"; operationId: string; coverageOperationId: string; status: ImportStatus }
  | { type: "import-request-failed"; operationId: string; message: string }
  | { type: "coverage-finished"; operationId: string; coverage: Coverage; asOf: string }
  | { type: "coverage-request-failed"; operationId: string; message: string }
  | { type: "retry-initial-coverage"; operationId: string }
  | { type: "refresh-coverage"; operationId: string; asOf: string }
  | { type: "begin-reports"; operationId: string }
  | { type: "reports-finished"; operationId: string; reports: ReportPair }
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
          imported: action.status,
          asOf: null,
          previousCoverage: null,
        };
      }
      return {
        kind: "import-error",
        submission: state.submission,
        message: action.status.failure?.action ?? "The Apple Health export could not be imported.",
      };
    case "import-request-failed":
      if ((state.kind === "uploading" || state.kind === "importing") && state.operationId === action.operationId) {
        return { kind: "import-error", submission: state.submission, message: action.message };
      }
      return state;
    case "coverage-finished":
      return state.kind === "coverage-loading" && state.operationId === action.operationId
        ? {
            kind: "coverage",
            imported: state.imported,
            coverage: action.coverage,
            asOf: action.asOf,
          }
        : state;
    case "coverage-request-failed":
      return state.kind === "coverage-loading" && state.operationId === action.operationId
        ? {
            kind: "coverage-error",
            imported: state.imported,
            coverage: state.previousCoverage,
            asOf: state.asOf ?? "",
            message: action.message,
          }
        : state;
    case "retry-initial-coverage":
      return state.kind === "coverage-error" && !state.coverage
        ? { kind: "coverage-loading", operationId: action.operationId, imported: state.imported, asOf: null, previousCoverage: null }
        : state;
    case "refresh-coverage":
      if (state.kind === "coverage" || state.kind === "report") {
        return {
            kind: "coverage-loading",
            operationId: action.operationId,
            imported: state.imported,
            asOf: action.asOf,
            previousCoverage: state.coverage,
          };
      }
      return state.kind === "coverage-error"
        ? { kind: "coverage-loading", operationId: action.operationId, imported: state.imported, asOf: action.asOf, previousCoverage: state.coverage }
        : state;
    case "begin-reports":
      return (state.kind === "coverage" || state.kind === "report") && state.asOf
        ? {
            kind: "reporting",
            operationId: action.operationId,
            imported: state.imported,
            coverage: state.coverage,
            asOf: state.asOf,
          }
        : state;
    case "reports-finished":
      return state.kind === "reporting" && state.operationId === action.operationId
        ? {
            kind: "report",
            imported: state.imported,
            coverage: state.coverage,
            asOf: state.asOf,
            reports: action.reports,
          }
        : state;
  }
}
