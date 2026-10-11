import type { Coverage, DataMode, ImportStatus } from "@hachi/contracts";
import { requestJson, waitForPoll } from "../api";
import { parseContractDocument } from "../contract-validation";

function readImportStatus(value: unknown): ImportStatus {
  try {
    return parseContractDocument<ImportStatus>("ImportStatus", value);
  } catch {
    throw new Error("The Hachi API returned an invalid import status.");
  }
}

function readCoverage(value: unknown): Coverage {
  try {
    return parseContractDocument<Coverage>("Coverage", value);
  } catch {
    throw new Error("The Hachi API returned invalid coverage data.");
  }
}

export async function submitImport(
  file: File,
  subjectId: string,
  timeZone: string,
  dataMode: DataMode,
  signal: AbortSignal,
  apiBaseUrl: string,
): Promise<ImportStatus> {
  const sourceFormat = file.name.toLowerCase().endsWith(".zip")
    ? "apple_health_export_zip"
    : "apple_health_export_xml";
  const query = new URLSearchParams({
    subject_id: subjectId,
    tz_name: timeZone,
    source_format: sourceFormat,
    data_mode: dataMode,
  });
  const status = await requestJson<ImportStatus>(`/v1/imports?${query}`, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/octet-stream" },
    signal,
  }, apiBaseUrl);
  return readImportStatus(status);
}

export async function pollImport(
  importId: string,
  signal: AbortSignal,
  onProgress: (status: ImportStatus) => void,
  apiBaseUrl: string,
): Promise<ImportStatus> {
  for (;;) {
    const status = readImportStatus(
      await requestJson<ImportStatus>(`/v1/imports/${encodeURIComponent(importId)}`, { signal }, apiBaseUrl),
    );
    onProgress(status);
    if (status.state === "succeeded" || status.state === "failed") return status;
    await waitForPoll(signal);
  }
}

export async function getCoverage(
  subjectId: string,
  asOf: string | null,
  signal: AbortSignal,
  apiBaseUrl: string,
): Promise<Coverage> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  return readCoverage(
    await requestJson<Coverage>(
      `/v1/subjects/${encodeURIComponent(subjectId)}/coverage${query}`,
      { signal },
      apiBaseUrl,
    ),
  );
}

export async function getInitialCoverage(
  subjectId: string,
  signal: AbortSignal,
  apiBaseUrl: string,
): Promise<{ coverage: Coverage; asOf: string }> {
  const initial = await getCoverage(subjectId, null, signal, apiBaseUrl);
  const asOf = latestHour(initial.span_end_utc);
  return {
    coverage: asOf ? await getCoverage(subjectId, asOf, signal, apiBaseUrl) : initial,
    asOf,
  };
}

function latestHour(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  date.setUTCMinutes(0, 0, 0);
  return date.toISOString().replace(".000Z", "Z");
}
