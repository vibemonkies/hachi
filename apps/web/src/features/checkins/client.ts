import type {
  RecoveryRequest,
  ScenarioRequest,
  SelfReportRequest,
} from "../../../../../contracts/typescript/index";
import { parseDocument } from "./schema";

export function createCheckinApi(baseUrl: string) {
  const base = baseUrl.replace(/\/$/, "");
  async function request(path: string, init?: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(`${base}${path}`, init);
    } catch {
      throw new Error(
        "Cannot reach the local Hachi API. Check that it is running, then retry. Your draft is still here.",
      );
    }
    if (!response.ok) {
      let message = `The API refused this request (${response.status}). Retry after checking your input.`;
      try {
        const error = parseDocument("ApiError", await response.json());
        message = `${error.message}${error.field_issues.map((issue) => ` ${issue.path}: ${issue.message}`).join("")}`;
      } catch {
        /* Keep the safe status message for non-contract errors. */
      }
      throw new Error(message);
    }
    return response.status === 204 ? null : response.json();
  }
  const json = (
    body: SelfReportRequest | RecoveryRequest | ScenarioRequest,
  ) => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const subjectPath = (subjectId: string) =>
    `/v1/subjects/${encodeURIComponent(subjectId)}`;
  return {
    async history(subjectId: string, versions: "current" | "all" = "current") {
      return parseDocument(
        "SelfReportHistory",
        await request(
          `${subjectPath(subjectId)}/observations${versions === "all" ? "?versions=all" : ""}`,
        ),
      );
    },
    async deleteEntry(subjectId: string, entryId: string) {
      await request(
        `${subjectPath(subjectId)}/observations/${encodeURIComponent(entryId)}?confirm=${encodeURIComponent(entryId)}`,
        { method: "DELETE" },
      );
    },
    async save(subjectId: string, body: SelfReportRequest) {
      return parseDocument(
        "SelfReportRequest",
        await request(`${subjectPath(subjectId)}/observations`, json(body)),
      );
    },
    async deleteSubject(subjectId: string) {
      await request(
        `${subjectPath(subjectId)}?confirm=${encodeURIComponent(subjectId)}`,
        { method: "DELETE" },
      );
    },
    async recovery(body: RecoveryRequest) {
      return parseDocument(
        "ReportJob",
        await request("/v1/reports", json(body)),
      );
    },
    async report(reportId: string) {
      return parseDocument(
        "ReportJob",
        await request(`/v1/reports/${encodeURIComponent(reportId)}`),
      );
    },
    async scenario(body: ScenarioRequest) {
      return parseDocument(
        "ReportResult",
        await request("/v1/scenarios", json(body)),
      );
    },
  };
}
export type CheckinApi = ReturnType<typeof createCheckinApi>;
