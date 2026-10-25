// 青禾协作 · 任务表更新 前端逻辑
const $ = (id) => document.getElementById(id);

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return res.json();
}

function renderTable(tasks) {
  if (!tasks || !tasks.length) { $("task-table").textContent = "（空）"; return; }
  const cols = ["编号", "工作项", "责任人", "当前安排", "截止日", "验收条件"];
  let html = "<table><tr>" + cols.map(c => `<th>${c}</th>`).join("") + "</tr>";
  for (const t of tasks) {
    html += "<tr>" + t.map(v => `<td>${esc(v)}</td>`).join("") + "</tr>";
  }
  html += "</table>";
  $("task-table").innerHTML = html;
}

function renderSuggestions(suggestions) {
  const box = $("suggestions");
  if (!suggestions || !suggestions.length) { box.innerHTML = '<span class="muted">没有建议。</span>'; return; }
  box.innerHTML = "";
  suggestions.forEach((s, i) => {
    const div = document.createElement("div");
    div.className = "suggestion";
    const evidence = (s.evidence || []).map(e => `${e.chat_id}「${esc(e.quote)}」`).join("；");
    div.innerHTML = `
      <div class="meta">#${i} ${esc(s.task_id)} · ${esc(s.field)}</div>
      <div class="diff">${esc(s.original_value)} → <strong>${esc(s.suggested_value)}</strong></div>
      ${evidence ? `<div class="evidence">依据：${evidence}</div>` : ""}
      ${s.uncertainty ? `<div class="uncertainty">待核实：${esc(s.uncertainty)}</div>` : ""}
      <div class="actions">
        <button data-i="${i}" data-d="采纳">采纳</button>
        <button data-i="${i}" data-d="否决">否决</button>
        <button data-i="${i}" data-d="修改后采纳">修改后采纳</button>
        <span class="decision-pill" id="pill-${i}">${esc(s.decision)}</span>
      </div>`;
    box.appendChild(div);
  });
  box.querySelectorAll("button[data-d]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const i = btn.dataset.i;
      const d = btn.dataset.d;
      let modified = "";
      if (d === "修改后采纳") {
        modified = prompt("请输入修改后的值：", "");
        if (modified === null) return;
      }
      const r = await postJSON("/api/decide", { index: parseInt(i), decision: d, modified_value: modified });
      if (r.ok) {
        document.getElementById(`pill-${i}`).textContent = r.suggestion.decision;
        refreshState();
      } else {
        alert(r.error);
      }
    });
  });
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

async function refreshState() {
  const r = await fetch("/api/state").then(x => x.json());
  if (r.stage) $("stage").textContent = "阶段：" + r.stage;
  renderTable(r.tasks);
  renderSuggestions(r.suggestions);
  $("apply-btn").disabled = !(r.suggestions || []).some(s => s.decision === "采纳" || s.decision === "修改后采纳");
  $("export-btn").disabled = !(r.tasks && r.tasks.length);
}

// 载入
$("load-btn").addEventListener("click", async () => {
  const tf = $("task-file").files[0], cf = $("chat-file").files[0];
  if (!tf || !cf) { alert("请选择任务表 CSV 和聊天记录 CSV。"); return; }
  const fd = new FormData();
  fd.append("task_csv", tf);
  fd.append("chat_csv", cf);
  $("load-info").textContent = "载入中…";
  const res = await fetch("/api/load", { method: "POST", body: fd });
  const r = await res.json();
  if (r.ok) {
    $("load-info").textContent = `已载入：任务表 ${r.task_count} 行，聊天 ${r.chat_count} 条（新增 ${r.new_chat_count}，重复 ${r.duplicate_count}）。`;
    $("analyze-btn").disabled = r.new_chat_count === 0;
    $("analyze-error").textContent = "";
    refreshState();
  } else {
    $("load-info").textContent = "";
    $("analyze-error").textContent = r.error;
  }
});

// 分析
$("analyze-btn").addEventListener("click", async () => {
  $("analyze-status").textContent = "处理中…";
  $("analyze-error").textContent = "";
  $("analyze-btn").disabled = true;
  const r = await postJSON("/api/analyze", {});
  if (r.ok) {
    $("analyze-status").textContent = r.skipped
      ? r.message
      : `完成：${(r.suggestions || []).length} 条建议（模型 ${r.model}）。`;
    refreshState();
  } else {
    $("analyze-status").textContent = "失败";
    $("analyze-error").textContent = r.error;
    $("analyze-btn").disabled = false;
  }
});

// 写回
$("apply-btn").addEventListener("click", async () => {
  const r = await postJSON("/api/apply", {});
  if (r.ok) {
    $("export-btn").disabled = false;
    refreshState();
  } else {
    alert(r.error);
  }
});

// 导出
$("export-btn").addEventListener("click", async () => {
  const r = await postJSON("/api/export", {});
  if (r.ok) {
    const links = Object.entries(r.files).map(([k, v]) =>
      `<a href="/api/download?name=${encodeURIComponent(v.split("/").pop())}" download>${v.split("/").pop()}</a>`).join("　");
    $("export-info").innerHTML = "已导出：" + links;
  } else {
    alert(r.error);
  }
});

refreshState();
