export type Session = {
  token: string;
  user_id: string;
  workspace_id: string;
  project_id: string;
  role: string;
};

const KEY = "evalforge.session";

export function loadSession(): Session | null {
  const raw = localStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  localStorage.setItem(KEY, JSON.stringify(session));
}

export function clearSession(): void {
  localStorage.removeItem(KEY);
}

export type ApiFailure = {
  message: string;
  details: { line: number | null; message: string }[];
};

export class ApiError extends Error {
  status: number;
  details: ApiFailure["details"];

  constructor(status: number, message: string, details: ApiFailure["details"] = []) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const session = loadSession();
  const headers = new Headers(init.headers);
  if (session) headers.set("Authorization", `Bearer ${session.token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const error = payload?.error;
    throw new ApiError(response.status, error?.message || "Request failed", error?.details || []);
  }
  return payload as T;
}

export async function download(path: string, filename: string): Promise<void> {
  const session = loadSession();
  const headers = new Headers();
  if (session) headers.set("Authorization", `Bearer ${session.token}`);
  const response = await fetch(path, { headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(response.status, payload?.error?.message || "Download failed");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export const EVALUATORS = [
  "exact_match",
  "normalized_match",
  "token_f1",
  "json_schema",
  "latency",
  "token_usage",
  "error_rate",
  "recall_at_5",
  "precision_at_5",
  "faithfulness",
  "answer_relevance",
  "correctness",
  "citation_correctness",
];
