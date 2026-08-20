import type { ApiEnvelope, ApiListParams } from "@/lib/api/types";

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;

  constructor(message: string, status: number, code?: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api/v1";
const AUTH_TOKEN_KEY = "deltaledger.authToken";

export type AuthTokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  subject: string;
  role: string;
};

export function apiBaseUrl() {
  return API_BASE_URL;
}

export function setApiAuthToken(token: string) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  }
}

export function clearApiAuthToken() {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
  }
}

export async function issueApiAuthToken(body: {
  username: string;
  password: string;
}): Promise<AuthTokenResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/token`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });
  const envelope = await parseEnvelope<AuthTokenResponse>(response);
  if (!response.ok || envelope.error) {
    const message =
      envelope.error?.message ??
      (typeof envelope.data === "string" ? envelope.data : null) ??
      `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, envelope.error?.code, envelope.error?.details);
  }
  setApiAuthToken(envelope.data.access_token);
  return envelope.data;
}

export async function request<T>(
  path: string,
  options: RequestInit & { params?: ApiListParams } = {}
): Promise<T> {
  const { params, headers, ...init } = options;
  const requestHeaders = new Headers(headers);
  requestHeaders.set("Accept", "application/json");
  if (init.body && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }
  const token = authToken();
  if (token) {
    requestHeaders.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}${queryString(params)}`, {
    ...init,
    headers: requestHeaders
  });

  const envelope = await parseEnvelope<T>(response);
  if (!response.ok || envelope.error) {
    const message =
      envelope.error?.message ??
      (typeof envelope.data === "string" ? envelope.data : null) ??
      `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, envelope.error?.code, envelope.error?.details);
  }
  return envelope.data;
}

function authToken() {
  return typeof window === "undefined" ? undefined : window.localStorage.getItem(AUTH_TOKEN_KEY);
}

function queryString(params?: ApiListParams) {
  if (!params) {
    return "";
  }
  const values = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      values.set(key, String(value));
    }
  }
  const serialized = values.toString();
  return serialized ? `?${serialized}` : "";
}

async function parseEnvelope<T>(response: Response): Promise<ApiEnvelope<T>> {
  const text = await response.text();
  if (!text) {
    return { data: undefined as T, meta: {}, error: null };
  }
  const parsed = JSON.parse(text) as ApiEnvelope<T> | { detail?: unknown };
  if ("data" in parsed) {
    return parsed;
  }
  const detail = parsed.detail;
  const message =
    typeof detail === "string"
      ? detail
      : typeof detail === "object" && detail && "message" in detail
        ? String(detail.message)
        : "Request failed";
  return {
    data: undefined as T,
    meta: {},
    error: { message, details: detail }
  };
}
