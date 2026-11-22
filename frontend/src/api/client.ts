/**
 * Small typed wrapper around fetch for the backend API (same origin; the login cookie is
 * sent automatically). Types come from the backend's OpenAPI schema (`npm run api-types`).
 */
import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Me = Schemas["Me"];
export type EventOut = Schemas["EventOut"];
export type ScanSummary = Schemas["ScanSummary"];
export type ScanStatus = Schemas["ScanStatus"];
export type UploadOut = Schemas["UploadOut"];

/** Every failure, including "no connection" (status 0, code "network"). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** Worth trying again later: no connection, timeouts, rate limits, server errors. */
  get retryable(): boolean {
    return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500;
  }
}

const MESSAGES: Record<string, string> = {
  network: "No connection to the server. Check the Wi-Fi; uploads will wait and retry.",
  wrong_pin: "Wrong PIN. Ask the event supervisor for the tournament PIN.",
  too_many_attempts: "Too many wrong PINs from this device. Wait a few minutes and try again.",
  not_logged_in: "You've been logged out. Log in again.",
  admin_only: "Only a supervisor can do this.",
  too_large: "That file is too big (25 MB at most). Take a normal photo instead.",
  unsupported_type: "That file isn't a photo or PDF.",
  bad_page_count: "That PDF has too many pages (60 at most).",
  not_found: "Not found. It may have been removed.",
};

/** A sentence to show a grader for any error. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (MESSAGES[err.code]) return MESSAGES[err.code]!;
    if (err.status >= 500) return "The server had a problem. Try again in a moment.";
    return err.message || "Something went wrong.";
  }
  return "Something went wrong.";
}

/** Turn a failed response into an ApiError using the backend's {detail, code} shape. */
export async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object") {
      const b = body as { code?: unknown; detail?: unknown };
      if (typeof b.code === "string") code = b.code;
      if (typeof b.detail === "string") detail = b.detail;
    }
  } catch {
    // not JSON (e.g. a proxy error page): keep the status text
  }
  return new ApiError(res.status, code, detail);
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, "network", "No connection");
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  me: () => request<Me>("/api/me"),
  login: (pin: string, graderName: string) =>
    request<Me>("/api/login", json("POST", { pin, grader_name: graderName })),
  logout: () => request<void>("/api/logout", { method: "POST" }),
  events: () => request<EventOut[]>("/api/events"),
  scans: (eventCode: string) =>
    request<ScanSummary[]>(`/api/events/${encodeURIComponent(eventCode)}/scans`),
};

/**
 * Upload one file with progress (fetch can't report upload progress, XHR can).
 * Rejects with ApiError; status 0 means the network failed.
 */
export function uploadScan(
  eventCode: string,
  file: Blob,
  filename: string,
  onProgress?: (fraction: number) => void,
): Promise<UploadOut> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("event_code", eventCode);
    form.append("file", file, filename);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/scans");
    xhr.withCredentials = true;
    xhr.timeout = 120_000;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: { code?: string; detail?: string } & Partial<UploadOut> = {};
      try {
        body = JSON.parse(xhr.responseText || "{}");
      } catch {
        // keep empty body
      }
      if (xhr.status >= 200 && xhr.status < 300 && body.scans) {
        resolve(body as UploadOut);
      } else {
        reject(
          new ApiError(
            xhr.status,
            body.code ?? `http_${xhr.status}`,
            body.detail ?? `HTTP ${xhr.status}`,
          ),
        );
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "No connection"));
    xhr.ontimeout = () => reject(new ApiError(0, "network", "Upload timed out"));
    xhr.send(form);
  });
}
