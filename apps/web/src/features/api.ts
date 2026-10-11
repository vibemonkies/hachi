import type { SchemaVersion } from "@hachi/contracts";

type ContractDocument = { schema_version: SchemaVersion };

export class ApiRequestError extends Error {
  readonly requestId: string | null;

  constructor(message: string, requestId: string | null = null) {
    super(message);
    this.name = "ApiRequestError";
    this.requestId = requestId;
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function waitForPoll(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve();
    }, 750);
    const cancel = () => {
      window.clearTimeout(timer);
      reject(new DOMException("The operation was cancelled.", "AbortError"));
    };
    signal.addEventListener("abort", cancel, { once: true });
  });
}

export async function requestJson<T extends ContractDocument>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiRequestError("The local Hachi API could not be reached.");
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiRequestError(`The Hachi API returned an unreadable response (${response.status}).`);
  }

  if (!isRecord(body) || body.schema_version !== "0.1") {
    throw new ApiRequestError(`The Hachi API returned an unsupported response (${response.status}).`);
  }

  if (!response.ok) {
    const message = typeof body.message === "string" ? body.message : `The Hachi API request failed (${response.status}).`;
    const requestId = typeof body.request_id === "string" ? body.request_id : null;
    const fields = Array.isArray(body.field_issues)
      ? body.field_issues
          .filter(isRecord)
          .filter((issue) => typeof issue.path === "string" && typeof issue.message === "string")
          .map((issue) => `${issue.path}: ${issue.message}`)
          .join("; ")
      : "";
    const detail = fields ? `${message} ${fields}` : message;
    throw new ApiRequestError(
      `${detail}${requestId ? ` Request ID: ${requestId}.` : ""}`,
      requestId,
    );
  }

  return body as unknown as T;
}
