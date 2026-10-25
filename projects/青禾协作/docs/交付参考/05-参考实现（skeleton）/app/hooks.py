"""钩子系统（s04）：PreToolUse 可阻断、PostToolUse 可观察、异常不影响主循环。

- 审计钩子：记录每次工具调用与每次使用者决定。
- 权限钩子：apply_changes / record_decision 在未满足条件时可阻断。
- 变更说明与建议清单仍由本模块生成。
"""
from __future__ import annotations

import time
from datetime import datetime

from app.models import Suggestion, Task
from app.observability import log_event


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class HookRunner:
    """挂在循环上的钩子集合。pre 返回 False 即阻断；钩子异常只记录、不打断主循环。"""

    def __init__(self) -> None:
        self.pre_hooks: list = []
        self.post_hooks: list = []

    def register_pre(self, fn) -> None:
        self.pre_hooks.append(fn)

    def register_post(self, fn) -> None:
        self.post_hooks.append(fn)

    def run_pre(self, tool_name: str, **kwargs) -> tuple[bool, str]:
        for fn in self.pre_hooks:
            try:
                if fn(tool_name, kwargs) is False:
                    return False, f"工具 {tool_name} 被钩子阻断"
            except Exception as exc:  # 异常不影响主循环
                log_event("hook_error", hook=fn.__name__, tool=tool_name, error=str(exc))
        return True, ""

    def run_post(self, tool_name: str, result) -> None:
        for fn in self.post_hooks:
            try:
                fn(tool_name, result)
            except Exception as exc:
                log_event("hook_error", hook=fn.__name__, tool=tool_name, error=str(exc))


class AuditLog:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record_decision(self, suggestion: Suggestion) -> None:
        entry = {
            "time": now(),
            "task_id": suggestion.task_id,
            "field": suggestion.field,
            "decision": suggestion.decision,
            "effective_value": suggestion.effective_value if suggestion.decision in ("采纳", "修改后采纳") else "",
        }
        self.entries.append(entry)
        log_event("decision", **entry)

    def record_tool(self, tool_name: str, ok: bool, detail: str = "") -> None:
        self.entries.append({"time": now(), "tool": tool_name, "ok": ok, "detail": detail})


def build_change_log(tasks_before: list[Task], tasks_after: list[Task],
                     applied: list[Suggestion], rejected_or_pending: list[Suggestion]) -> str:
    """生成简短变更说明。"""
    lines = ["# 变更说明", "", f"生成时间：{now()}", ""]

    before = {t.id: t for t in tasks_before}
    after = {t.id: t for t in tasks_after}

    lines.append("## 改了什么")
    changed = False
    for t in tasks_after:
        b = before.get(t.id)
        if b is None:
            continue
        diffs = []
        for field, key in [("工作项", "item"), ("责任人", "owner"), ("当前安排", "status"),
                           ("截止日", "due"), ("验收条件", "acceptance")]:
            if getattr(b, key) != getattr(t, key):
                diffs.append(f"{field}：{getattr(b, key)} → {getattr(t, key)}")
        if diffs:
            changed = True
            evidence = _evidence_for(applied, t.id)
            lines.append(f"- **{t.id}** " + "；".join(diffs))
            if evidence:
                lines.append(f"  - 依据：{evidence}")
    if not changed:
        lines.append("- 本批没有字段被写回。")

    lines.append("")
    lines.append("## 被放下的请求（保留依据，未写回）")
    dropped = [s for s in rejected_or_pending if s.decision in ("否决", "待确认")]
    if dropped:
        for s in dropped:
            ev = _evidence_for([s], s.task_id)
            lines.append(f"- {s.task_id}.{s.field}：{s.decision}（{ev or '无依据'}）")
    else:
        lines.append("- 无。")

    lines.append("")
    lines.append("## 没改的行（保持原安排）")
    kept = [t.id for t in tasks_after if before.get(t.id) is not None
            and all(getattr(before[t.id], k) == getattr(t, k)
                    for _, k in [("工作项", "item"), ("责任人", "owner"), ("当前安排", "status"),
                                 ("截止日", "due"), ("验收条件", "acceptance")])]
    lines.append("；".join(kept) if kept else "- 无")

    lines.append("")
    lines.append("## 还缺什么")
    pending = [s for s in rejected_or_pending if s.uncertainty or s.decision == "待确认"]
    if pending:
        for s in pending:
            lines.append(f"- {s.task_id}.{s.field}：{s.uncertainty or '待确认'}")
    else:
        lines.append("- 无。")

    return "\n".join(lines) + "\n"


def _evidence_for(suggestions: list[Suggestion], task_id: str) -> str:
    parts = []
    for s in suggestions:
        if s.task_id == task_id and s.evidence:
            for ev in s.evidence:
                parts.append(f"{ev.get('chat_id', '')}「{ev.get('quote', '')}」")
    return "；".join(parts)


def build_review_pack(suggestions: list[Suggestion]) -> str:
    """仍可核对的建议清单（含依据原话与使用者决定）。"""
    import json
    return json.dumps([s.to_dict() for s in suggestions], ensure_ascii=False, indent=2)
