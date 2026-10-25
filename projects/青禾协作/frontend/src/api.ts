// 集中式 API 层：所有接口调用与类型定义都在这里，页面组件不散落 fetch。

export interface Evidence {
  chat_id: string;
  quote: string;
}

export interface Suggestion {
  task_id: string;
  field: string;
  original_value: string;
  suggested_value: string;
  no_change: boolean;
  evidence: Evidence[];
  uncertainty: string;
  decision: string;
  modified_value: string;
  urgency: string;       // 高/中/低，仅展示排序
  decided_at: string;    // YYYY-MM-DD HH:MM:SS
  decided_by: string;
  reject_reason: string;
}

export interface Step {
  step: string;
  status: string;
  detail: string;
}

export interface StateData {
  tasks: string[][];
  suggestions: Suggestion[];
  stage: string;
  steps: Step[];
  last_error: string;
  metrics?: Record<string, unknown>;
}

export interface LoadResult {
  ok: boolean;
  task_count: number;
  chat_count: number;
  new_chat_count: number;
  duplicate_count: number;
  stage?: string;
}

export interface AnalyzeResult {
  ok: boolean;
  suggestions?: Suggestion[];
  model?: string;
  skipped?: boolean;
  message?: string;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  let data: unknown = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) {
    const err = (data as { error?: { message?: string } }).error;
    throw new Error(err?.message ?? `HTTP ${res.status}`);
  }
  return data as T;
}

export const getState = () => api<StateData>("/api/state");

export const loadFiles = (fd: FormData) =>
  api<LoadResult>("/api/load", { method: "POST", body: fd });

export const runAnalyze = () => api<AnalyzeResult>("/api/analyze", { method: "POST" });

export const submitDecision = (
  index: number,
  decision: string,
  modifiedValue = "",
  rejectReason = "",
) =>
  api<{ ok: boolean }>("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      index,
      decision,
      modified_value: modifiedValue,
      reject_reason: rejectReason,
    }),
  });

export const applyChanges = () =>
  api<{ ok: boolean; applied?: Suggestion[] }>("/api/apply", { method: "POST" });

export const undoAction = (action: "decision" | "apply", index = -1) =>
  api<{ ok: boolean }>("/api/undo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, index }),
  });

export const exportOutputs = () =>
  api<{ ok: boolean; files?: Record<string, string> }>("/api/export", { method: "POST" });
