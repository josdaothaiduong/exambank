// EB-106 — API client dùng chung: gắn JWT, xử lý 401 -> về trang đăng nhập.
export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("exambank_token");
}

export function setToken(token: string) {
  localStorage.setItem("exambank_token", token);
}

export function clearToken() {
  localStorage.removeItem("exambank_token");
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isForm ? {} : { "Content-Type": "application/json" }),
    ...((init.headers as Record<string, string>) || {}),
  };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new Error("Phiên đăng nhập đã hết hạn");
  }
  if (!res.ok) {
    let msg = `Lỗi ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export interface Workspace { id: string; name: string; school_name: string | null; owner_id: string }
export interface SourceExam {
  id: string; workspace_id: string; title: string; grade: number | null;
  exam_kind: string | null; source_name: string | null; school_year: string | null;
}
export interface Tag { id: string; kind: string; code: string; label: string }
export interface QuestionItem {
  id: string; question_type: string; stem_text: string; status: string;
  difficulty: string | null; answer_source: string; answer_confidence: number | null;
  correct_option_id: string | null; stem_html?: string; passage_text?: string | null; passage_html?: string | null; tags: string[];
  options: { id: string; label: string; content_text: string; content_html?: string }[];
}
export interface ImportStats { total: number; with_answer: number; needs_answer: number; duplicates: number; failed: number }
export interface ImportResult { import_job_id: string; status: string; stats: ImportStats; error_log: unknown[] }
export interface ReviewQueue { items: QuestionItem[]; total: number }
export interface QuestionPage { items: QuestionItem[]; total: number; page: number; page_size: number }
