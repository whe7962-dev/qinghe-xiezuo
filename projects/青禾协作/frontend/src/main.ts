import {
  getState, loadFiles, runAnalyze, submitDecision, applyChanges, exportOutputs, undoAction,
  type Suggestion, type StateData,
} from "./api";
import "./style.css";

const NO_TASK = "不对应现有任务";
const FIELD_ORDER = ["责任人", "截止日", "当前安排", "验收条件", "工作项"];
const URGENCY_RANK: Record<string, number> = { 高: 0, 中: 1, 低: 2 };
const CHECK_KEY = "qinghe.checked";

let current: StateData = { tasks: [], suggestions: [], stage: "", steps: [], last_error: "" };

function el(tag: string, cls?: string, text?: string): HTMLElement {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function getChecked(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(CHECK_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function saveChecked(ids: Set<string>): void {
  localStorage.setItem(CHECK_KEY, JSON.stringify([...ids]));
}

// ---- 三重编码 ----
function natureOf(s: Suggestion) {
  if (s.task_id === NO_TASK) return { label: "无法归属", icon: "？", cls: "nature-unknown" };
  if (s.no_change) return { label: "保持原样", icon: "＝", cls: "nature-keep" };
  if (s.suggested_value === "待核实" || s.uncertainty) return { label: "待核实", icon: "⚠", cls: "nature-verify" };
  return { label: "建议修改", icon: "↻", cls: "nature-change" };
}

function decisionOf(d: string) {
  switch (d) {
    case "采纳": return { label: "已采纳", icon: "✓", cls: "dec-adopt" };
    case "否决": return { label: "已否决", icon: "✕", cls: "dec-reject" };
    case "修改后采纳": return { label: "修改后采纳", icon: "✓*", cls: "dec-modify" };
    default: return { label: "待你决定", icon: "○", cls: "dec-pending" };
  }
}

function badge(text: string, cls: string, icon: string): HTMLElement {
  const b = el("span", "badge " + cls);
  b.appendChild(el("span", "", icon));
  b.appendChild(el("span", "", text));
  return b;
}

function urgencyCls(u: string): string {
  return u === "高" ? "urgency-high" : u === "低" ? "urgency-low" : "urgency-mid";
}

// ---- 全局元素 ----
let statusBox: HTMLElement;
let stepperBox: HTMLElement;
let summaryBox: HTMLElement;
let suggestionsBox: HTMLElement;
let taskTableBox: HTMLElement;
let downloadsBox: HTMLElement;

function setStatus(text: string, kind: "info" | "ok" | "error" = "info"): void {
  statusBox.textContent = text;
  statusBox.className = "status " + kind;
}

function setBusy(v: boolean): void {
  document.querySelectorAll<HTMLButtonElement>("[data-busy]").forEach((b) => {
    b.disabled = v;
  });
}

function stepIndex(stage: string): number {
  if (stage === "导出") return 3;
  if (stage === "确认" || stage === "核对") return 2;
  if (stage === "分析") return 1;
  return 0;
}

function renderSteps(stage: string): void {
  stepperBox.innerHTML = "";
  const cur = stepIndex(stage);
  const names = ["载入", "分析", "核对", "导出"];
  names.forEach((name, i) => {
    const st = el("span", "step" + (i === cur ? " active" : i < cur ? " done" : ""));
    st.appendChild(el("span", "dot", i < cur ? "✓" : String(i + 1)));
    st.appendChild(el("span", "", name));
    stepperBox.appendChild(st);
    if (i < names.length - 1) stepperBox.appendChild(el("span", "step-sep", "›"));
  });
}

function renderSummary(list: Suggestion[]): void {
  summaryBox.innerHTML = "";
  if (!list.length) {
    summaryBox.textContent = "尚未分析";
    return;
  }
  const handled = list.filter((s) => s.decision !== "待确认").length;
  const changed = list.filter((s) => s.decision === "采纳" || s.decision === "修改后采纳").length;
  const parts: (string | HTMLElement)[] = ["本批 ", el("strong", "", String(list.length)), " 条建议 · 已处理 ",
    el("strong", "", String(handled)), " · 待处理 ", el("strong", "", String(list.length - handled)),
    " · 其中 ", el("strong", "", String(changed)), " 条有实际变更"];
  for (const p of parts) summaryBox.appendChild(typeof p === "string" ? document.createTextNode(p) : p);
}

function sortSuggestions(list: Suggestion[]): Suggestion[] {
  return [...list].sort((a, b) => {
    const ua = URGENCY_RANK[a.urgency] ?? 1;
    const ub = URGENCY_RANK[b.urgency] ?? 1;
    if (ua !== ub) return ua - ub;
    if (a.task_id !== b.task_id) return a.task_id < b.task_id ? -1 : 1;
    const fa = FIELD_ORDER.indexOf(a.field);
    const fb = FIELD_ORDER.indexOf(b.field);
    return (fa === -1 ? 99 : fa) - (fb === -1 ? 99 : fb);
  });
}

function taskName(tasks: string[][], id: string): string {
  const row = tasks.find((r) => r[0] === id);
  return row ? row[1] : "";
}

function renderCard(s: Suggestion, all: Suggestion[]): HTMLElement {
  const idx = all.indexOf(s);
  const nat = natureOf(s);
  const dec = decisionOf(s.decision);
  const card = el("div", "card");

  const head = el("div", "card-head");
  head.appendChild(el("span", "title", s.task_id + (s.field ? " · " + s.field : "")));
  head.appendChild(badge(nat.label, nat.cls, nat.icon));
  head.appendChild(badge("紧急·" + (s.urgency || "中"), urgencyCls(s.urgency || "中"), "◆"));
  head.appendChild(badge(dec.label, dec.cls, dec.icon));
  card.appendChild(head);

  const diff = el("div", "diff");
  if (s.task_id !== NO_TASK) {
    const oldRow = el("div", "old");
    oldRow.appendChild(el("span", "", "原值："));
    oldRow.appendChild(el("del", "", s.original_value || "（空）"));
    diff.appendChild(oldRow);
    if (s.no_change) {
      diff.appendChild(el("div", "new", "＝ 保持原样"));
    } else {
      const newRow = el("div");
      newRow.appendChild(el("span", "", "建议值："));
      newRow.appendChild(el("span", "new", s.suggested_value || "（空）"));
      diff.appendChild(newRow);
    }
  } else {
    diff.appendChild(el("div", "", "建议：" + (s.suggested_value || "待核实")));
  }
  card.appendChild(diff);

  if (s.evidence && s.evidence.length) {
    const ev = el("details", "evidence");
    ev.appendChild(el("summary", "", `依据（${s.evidence.length} 条原话，点击展开）`));
    const ul = el("ul");
    for (const e of s.evidence) ul.appendChild(el("li", "", `${e.chat_id}「${e.quote}」`));
    ev.appendChild(ul);
    card.appendChild(ev);
  }

  if (s.uncertainty) card.appendChild(el("div", "uncertainty", "不确定点：" + s.uncertainty));

  const row = el("div", "decide-row");
  for (const d of ["采纳", "否决", "修改后采纳"]) {
    const btn = el("button", "btn small" + (s.decision === d ? " on" : ""), d) as HTMLButtonElement;
    btn.setAttribute("data-busy", "");
    btn.addEventListener("click", () => onDecide(idx, d));
    row.appendChild(btn);
  }
  if (s.decision !== "待确认") {
    const undoBtn = el("button", "btn small", "撤销") as HTMLButtonElement;
    undoBtn.setAttribute("data-busy", "");
    undoBtn.addEventListener("click", () => void onUndo(idx));
    row.appendChild(undoBtn);
  }
  card.appendChild(row);

  if (s.decided_at) {
    card.appendChild(el("div", "trace", `${dec.icon} ${dec.label} · ${s.decided_at} · ${s.decided_by || "维护人"}`));
  }

  return card;
}

function renderSuggestions(list: Suggestion[], tasks: string[][]): void {
  suggestionsBox.innerHTML = "";
  if (!list.length) {
    suggestionsBox.appendChild(el("p", "muted", "还没有建议。发起分析后会按任务分组显示在这里。"));
    return;
  }
  const sorted = sortSuggestions(list);
  const map = new Map<string, Suggestion[]>();
  for (const s of sorted) {
    if (s.task_id === NO_TASK) continue;
    if (!map.has(s.task_id)) map.set(s.task_id, []);
    map.get(s.task_id)!.push(s);
  }
  const keys = [...map.keys()].sort();

  for (const id of keys) {
    const items = map.get(id)!;
    const changeItems = items.filter((s) => !s.no_change);
    const keepItems = items.filter((s) => s.no_change);
    const g = el("div", "group");

    const head = el("div", "group-head");
    head.appendChild(el("span", "", `${id} ${taskName(tasks, id)}`));
    const handledG = items.filter((s) => s.decision !== "待确认").length;
    head.appendChild(el("span", "count", `${items.length} 条建议 · 已处理 ${handledG}`));
    g.appendChild(head);

    const body = el("div", "group-body");
    for (const s of changeItems) body.appendChild(renderCard(s, list));
    if (keepItems.length) {
      const fold = el("details", "keep-fold");
      fold.appendChild(el("summary", "", `另有 ${keepItems.length} 条保持原样（展开）`));
      for (const s of keepItems) fold.appendChild(renderCard(s, list));
      body.appendChild(fold);
    }
    g.appendChild(body);
    suggestionsBox.appendChild(g);
  }

  const unknown = list.filter((s) => s.task_id === NO_TASK);
  if (unknown.length) {
    const g = el("div", "group");
    const head = el("div", "group-head");
    head.appendChild(el("span", "", "无法归属现有任务"));
    head.appendChild(el("span", "count", `${unknown.length} 条`));
    g.appendChild(head);
    const body = el("div", "group-body");
    for (const s of unknown) body.appendChild(renderCard(s, list));
    g.appendChild(body);
    suggestionsBox.appendChild(g);
  }
}

function renderTasks(tasks: string[][]): void {
  taskTableBox.innerHTML = "";
  if (!tasks.length) {
    taskTableBox.appendChild(el("p", "muted", "尚未载入任务表。"));
    return;
  }
  const checked = getChecked();
  const table = el("table", "task-table") as HTMLTableElement;
  const thead = el("thead");
  const tr = el("tr");
  tr.appendChild(el("th", "", "已核对"));
  for (const h of ["编号", "工作项", "责任人", "当前安排", "截止日", "验收条件"]) tr.appendChild(el("th", "", h));
  thead.appendChild(tr);
  table.appendChild(thead);

  const tbody = el("tbody");
  for (const row of tasks) {
    const r = el("tr");
    const td = el("td", "checked-mark");
    const label = el("label", "checkbox-line");
    const cb = el("input") as HTMLInputElement;
    cb.type = "checkbox";
    cb.checked = checked.has(row[0]);
    cb.setAttribute("aria-label", `已核对 ${row[0]}`);
    cb.addEventListener("change", () => {
      const set = getChecked();
      if (cb.checked) set.add(row[0]);
      else set.delete(row[0]);
      saveChecked(set);
    });
    label.appendChild(cb);
    label.appendChild(el("span", "", "已核对"));
    td.appendChild(label);
    r.appendChild(td);
    for (const cell of row) r.appendChild(el("td", "", cell));
    tbody.appendChild(r);
  }
  table.appendChild(tbody);
  taskTableBox.appendChild(table);
}

function onDecide(index: number, decision: string): void {
  const s = current.suggestions[index];
  if (!s) return;
  if (decision === "修改后采纳") {
    const v = window.prompt("请输入修改后要写回的值（只能改建议值，不能改原值）：", s.suggested_value);
    if (v === null) return;
    const mv = v.trim();
    if (!mv) {
      setStatus("修改后采纳需要填写值。", "error");
      return;
    }
    showConfirm(index, decision, { modified: mv });
    return;
  }
  if (decision === "否决") {
    showConfirm(index, decision, { reject: true });
    return;
  }
  showConfirm(index, decision);
}

function showConfirm(index: number, decision: string, opts?: { modified?: string; reject?: boolean }): void {
  const s = current.suggestions[index];
  const mask = el("div", "modal-mask");
  const modal = el("div", "modal");
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");

  modal.appendChild(el("h3", "", "确认" + decision));
  modal.appendChild(el("div", "kv", `任务：${s.task_id}${s.field ? " · " + s.field : ""}`));
  if (s.task_id !== NO_TASK) {
    modal.appendChild(el("div", "kv", `原值：${s.original_value || "（空）"}`));
    const newVal =
      decision === "采纳" ? s.suggested_value
        : decision === "修改后采纳" ? (opts?.modified || s.suggested_value)
          : "（不写回）";
    modal.appendChild(el("div", "kv", `新值：${newVal}`));
  }

  let reasonInput: HTMLInputElement | null = null;
  if (opts?.reject) {
    modal.appendChild(el("div", "kv", "否决理由（可选）："));
    reasonInput = el("input") as HTMLInputElement;
    reasonInput.type = "text";
    reasonInput.placeholder = "理由（可选，不填记为未填理由）";
    modal.appendChild(reasonInput);
  }

  modal.appendChild(el("div", "warn", "此操作不可撤销。"));

  const row = el("div", "btn-row");
  const cancel = el("button", "btn", "取消") as HTMLButtonElement;
  cancel.addEventListener("click", () => mask.remove());
  const ok = el("button", "btn primary", "确认" + decision) as HTMLButtonElement;
  ok.addEventListener("click", () => {
    const reason = reasonInput ? reasonInput.value.trim() : "";
    mask.remove();
    void doDecide(index, decision, opts?.modified || "", reason);
  });
  row.appendChild(cancel);
  row.appendChild(ok);
  modal.appendChild(row);
  mask.appendChild(modal);
  document.body.appendChild(mask);
  ok.focus();
}

async function doDecide(index: number, decision: string, modified: string, reason: string): Promise<void> {
  setBusy(true);
  try {
    await submitDecision(index, decision, modified, reason);
    setStatus(`已记录：${decision}${reason ? "（理由已保存）" : ""}`, "ok");
    await refreshState();
  } catch (e) {
    setStatus((e as Error).message, "error");
  } finally {
    setBusy(false);
  }
}

async function doLoad(): Promise<void> {
  const taskFile = (document.getElementById("task-file") as HTMLInputElement).files?.[0];
  const chatFile = (document.getElementById("chat-file") as HTMLInputElement).files?.[0];
  if (!taskFile || !chatFile) {
    setStatus("请先选择任务表和聊天记录两个 CSV 文件。", "error");
    return;
  }
  const fd = new FormData();
  fd.append("task_csv", taskFile);
  fd.append("chat_csv", chatFile);
  setBusy(true);
  setStatus("载入中…");
  try {
    const r = await loadFiles(fd);
    setStatus(`已载入：任务表 ${r.task_count} 行，聊天 ${r.chat_count} 条（新增 ${r.new_chat_count}，重复 ${r.duplicate_count}）。可发起分析。`, "ok");
    await refreshState();
  } catch (e) {
    setStatus((e as Error).message, "error");
  } finally {
    setBusy(false);
  }
}

async function doAnalyze(): Promise<void> {
  setBusy(true);
  setStatus("分析中（真实调用模型，最多约 3 分钟）…");
  try {
    const r = await runAnalyze();
    if (r.skipped) {
      setStatus(r.message ?? "本批聊天均已处理，未产生新建议。");
    } else {
      setStatus(`分析完成：${r.suggestions?.length ?? 0} 条建议。请逐条核对并确认。`, "ok");
    }
    await refreshState();
  } catch (e) {
    setStatus((e as Error).message, "error");
  } finally {
    setBusy(false);
  }
}

async function onUndo(index: number): Promise<void> {
  setBusy(true);
  try {
    await undoAction("decision", index);
    setStatus("已撤销该决定。", "ok");
    await refreshState();
  } catch (e) {
    setStatus((e as Error).message, "error");
  } finally {
    setBusy(false);
  }
}

async function onUndoApply(): Promise<void> {
  setBusy(true);
  try {
    await undoAction("apply");
    setStatus("已撤销本次写回。", "ok");
    await refreshState();
  } catch (e) {
    setStatus((e as Error).message, "error");
  } finally {
    setBusy(false);
  }
}

async function doApply(): Promise<void> {
  setBusy(true);
  setStatus("写回中…");
  try {
    const r = await applyChanges();
    setStatus(`已写回 ${r.applied?.length ?? 0} 条建议。`, "ok");
    await refreshState();
  } catch (e) {
    setStatus((e as Error).message, "error");
  } finally {
    setBusy(false);
  }
}

async function doExport(): Promise<void> {
  setBusy(true);
  setStatus("导出中…");
  try {
    const r = await exportOutputs();
    setStatus("已导出三份产物：任务表.csv、建议清单.json、变更说明.md。", "ok");
    renderDownloads(r.files ?? {});
    await refreshState();
  } catch (e) {
    setStatus((e as Error).message, "error");
  } finally {
    setBusy(false);
  }
}

function renderDownloads(files: Record<string, string>): void {
  downloadsBox.innerHTML = "";
  for (const key of Object.keys(files)) {
    const fn = files[key].split("/").pop() ?? "";
    const a = el("a", "", `下载 ${fn}`) as HTMLAnchorElement;
    a.href = `/api/download?name=${encodeURIComponent(fn)}`;
    downloadsBox.appendChild(a);
  }
}

async function refreshState(): Promise<void> {
  try {
    current = await getState();
    renderSteps(current.stage);
    renderSummary(current.suggestions);
    renderSuggestions(current.suggestions, current.tasks);
    renderTasks(current.tasks);
  } catch (e) {
    setStatus((e as Error).message, "error");
  }
}

function makeDropzone(label: string, id: string): HTMLElement {
  const dz = el("label", "dropzone");
  const input = el("input") as HTMLInputElement;
  input.type = "file";
  input.id = id;
  input.accept = ".csv";
  input.style.display = "none";
  const name = el("div", "dz-name", "未选择文件");

  dz.appendChild(input);
  dz.appendChild(el("div", "dz-icon", "⬆"));
  dz.appendChild(el("div", "dz-title", label));
  dz.appendChild(el("div", "dz-hint", "点击选择，或拖拽 CSV 到这里"));
  dz.appendChild(name);

  input.addEventListener("change", () => {
    const f = input.files?.[0];
    name.textContent = f ? f.name : "未选择文件";
    dz.classList.toggle("has-file", !!f);
  });
  dz.addEventListener("dragover", (e) => {
    e.preventDefault();
    dz.classList.add("drag");
  });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("drag");
    const f = e.dataTransfer?.files?.[0];
    if (f) {
      const dt = new DataTransfer();
      dt.items.add(f);
      input.files = dt.files;
      name.textContent = f.name;
      dz.classList.add("has-file");
    }
  });
  return dz;
}

function build(): void {
  const app = document.getElementById("app");
  if (!app) return;

  // 头部
  const header = el("div", "header");
  header.appendChild(el("h1", "app-title", "青禾协作"));
  header.appendChild(el("p", "app-sub", "根据聊天记录更新任务表 · 上传 → 分析 → 核对 → 导出"));
  app.appendChild(header);

  // 顶栏：步骤条 + 汇总条
  const topbar = el("div", "topbar");
  stepperBox = el("div", "stepper");
  topbar.appendChild(stepperBox);
  summaryBox = el("div", "summary");
  summaryBox.textContent = "尚未分析";
  topbar.appendChild(summaryBox);
  app.appendChild(topbar);

  // 状态
  statusBox = el("div", "status info", "就绪。");
  app.appendChild(statusBox);

  // 左右分栏
  const layout = el("div", "layout");
  const sidebar = el("div", "sidebar");
  const main = el("div", "main");

  // ① 载入（拖拽上传）
  const loadPanel = el("div", "panel");
  loadPanel.appendChild(el("h2", "", "① 载入"));
  loadPanel.appendChild(makeDropzone("任务表 CSV", "task-file"));
  loadPanel.appendChild(makeDropzone("聊天记录 CSV", "chat-file"));
  const loadBtn = el("button", "btn primary block", "载入") as HTMLButtonElement;
  loadBtn.setAttribute("data-busy", "");
  loadBtn.addEventListener("click", () => void doLoad());
  loadPanel.appendChild(loadBtn);
  sidebar.appendChild(loadPanel);

  // ② 分析
  const analyzePanel = el("div", "panel");
  analyzePanel.appendChild(el("h2", "", "② 分析"));
  const analyzeBtn = el("button", "btn primary block", "发起分析") as HTMLButtonElement;
  analyzeBtn.setAttribute("data-busy", "");
  analyzeBtn.addEventListener("click", () => void doAnalyze());
  analyzePanel.appendChild(analyzeBtn);
  sidebar.appendChild(analyzePanel);

  // ④ 写回与导出
  const exportPanel = el("div", "panel");
  exportPanel.appendChild(el("h2", "", "④ 写回与导出"));
  const applyBtn = el("button", "btn block", "写回（只写已采纳/修改后采纳）") as HTMLButtonElement;
  applyBtn.setAttribute("data-busy", "");
  applyBtn.addEventListener("click", () => void doApply());
  const exportBtn = el("button", "btn block", "导出三份产物") as HTMLButtonElement;
  exportBtn.setAttribute("data-busy", "");
  exportBtn.addEventListener("click", () => void doExport());
  const undoApplyBtn = el("button", "btn block", "撤销本次写回") as HTMLButtonElement;
  undoApplyBtn.setAttribute("data-busy", "");
  undoApplyBtn.addEventListener("click", () => void onUndoApply());
  exportPanel.appendChild(applyBtn);
  exportPanel.appendChild(exportBtn);
  exportPanel.appendChild(undoApplyBtn);
  downloadsBox = el("div", "downloads");
  exportPanel.appendChild(downloadsBox);
  sidebar.appendChild(exportPanel);

  layout.appendChild(sidebar);

  // ③ 核对
  const reviewPanel = el("div", "panel");
  reviewPanel.appendChild(el("h2", "", "③ 核对（逐条决定，无撤销）"));
  suggestionsBox = el("div", "suggestions");
  reviewPanel.appendChild(suggestionsBox);
  main.appendChild(reviewPanel);

  // 当前任务表
  const taskPanel = el("div", "panel");
  taskPanel.appendChild(el("h2", "", "当前任务表（「已核对」仅自己标记，不进导出）"));
  taskTableBox = el("div", "task-box");
  taskPanel.appendChild(taskTableBox);
  main.appendChild(taskPanel);

  layout.appendChild(main);
  app.appendChild(layout);

  void refreshState();
}

build();
