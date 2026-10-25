"""集成 Harness（s15）：把 s01 循环、s02 工具、s03 权限、s04 钩子、s05 规划归一为单一循环。

- 单一循环：载入 → 分析 → 核对 → 确认 → 写回 → 导出，每个动作走「pre 钩子 → 工具 → post 钩子」。
- 共享客户端：analyzer 与分析流程共用一份模型配置。
- 跨模块状态协调：store（状态）、planner（进度）、hooks（留痕）、metrics（指标）在这里串起来。
"""
from __future__ import annotations

from app import csv_io, store as store_module
from app.analyzer import Analyzer
from app.hooks import HookRunner, AuditLog
from app.llm_client import build_client_from_env, ModelError
from app.observability import metrics, log_event
from app.permission import PermissionError
from app.tools import build_tools


class Harness:
    def __init__(self, store=None, client_factory=None):
        self.store = store or store_module.store
        self.client_factory = client_factory or build_client_from_env
        self.tools = build_tools(self.store)
        self.hooks = HookRunner()
        self.hooks.register_pre(self._pre_guard)
        self.hooks.register_post(self._post_audit)

    # ---- 钩子 ----
    def _pre_guard(self, tool_name: str, kwargs: dict) -> bool:
        """PreToolUse：可阻断。apply_changes 在没有任何已采纳建议时阻断。"""
        if tool_name == "apply_changes":
            if not any(s.decision in ("采纳", "修改后采纳") for s in self.store.suggestions):
                return False
        return True

    def _post_audit(self, tool_name: str, result) -> None:
        """PostToolUse：可观察。记录工具结果，异常不影响主循环。"""
        ok = getattr(result, "ok", True)
        self.store.audit.record_tool(tool_name, ok)
        log_event("tool", name=tool_name, ok=ok)

    # ---- 载入 ----
    def load(self, task_csv_text: str, chat_csv_text: str) -> dict:
        ok, reason = self.hooks.run_pre("load_task_table", csv_text=task_csv_text)
        if not ok:
            return {"ok": False, "error": reason}
        try:
            tasks = csv_io.parse_task_csv(task_csv_text)
            chats = csv_io.parse_chat_csv(chat_csv_text)
        except (csv_io.CsvError, ValueError) as exc:
            metrics.record_trace("load", "载入", "失败", str(exc))
            return {"ok": False, "error": str(exc)}

        info = self.store.load(tasks, chats)
        metrics.load_total += 1
        if info["duplicate_count"] > 0:
            metrics.reimport_total += 1
            if info["new_chat_count"] == 0:
                metrics.reimport_zero_new_rows += 1
            metrics.confirmed_fields_total += info.get("protected_total", 0)
            metrics.confirmed_fields_protected += info.get("protected_fields", 0)
        metrics.record_trace("load", "载入", "完成",
                             f"任务 {info['task_count']} 行，聊天新增 {info['new_chat_count']} / 重复 {info['duplicate_count']}")
        self.store.save()
        self.hooks.run_post("load_task_table", None)
        return {"ok": True, **info, "stage": self.store.planner.stage}

    # ---- 分析 ----
    def analyze(self) -> dict:
        if not self.store.tasks or not self.store.chats:
            return {"ok": False, "error": "请先载入任务表和聊天记录。"}
        if not self.store.new_chats:
            return {"ok": True, "skipped": True, "message": "本批聊天均已处理过，未产生新建议（重复导入不新增行动）。"}

        ok, reason = self.hooks.run_pre("analyze_fields")
        if not ok:
            return {"ok": False, "error": reason}
        metrics.analyze_total += 1
        try:
            analyzer = Analyzer(self.client_factory())
            suggestions, result = analyzer.analyze(self.store.tasks, self.store.new_chats)
        except ModelError as exc:
            metrics.analyze_failures += 1
            self.store.last_error = f"分析失败：{exc}"
            self.store.planner.log_step("分析", "失败", self.store.last_error)
            metrics.record_trace("analyze", "分析", "失败", str(exc))
            return {"ok": False, "error": self.store.last_error}
        except Exception as exc:  # 防御：任何异常都进入失败状态
            metrics.analyze_failures += 1
            self.store.last_error = f"分析失败：{exc}"
            metrics.record_trace("analyze", "分析", "失败", str(exc))
            return {"ok": False, "error": self.store.last_error}

        self.store.set_suggestions(suggestions)
        self.store.mark_analyzed()
        metrics.suggestion_total += len(suggestions)
        metrics.suggestion_with_evidence += sum(1 for s in suggestions if s.evidence)
        metrics.record_trace("analyze", "分析", "完成", f"{len(suggestions)} 条建议，模型 {result.model}")
        self.store.last_error = ""
        self.store.save()
        self.hooks.run_post("analyze_fields", None)
        return {"ok": True, "suggestions": [s.to_dict() for s in suggestions],
                "model": result.model, "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens}

    # ---- 核对 / 确认 ----
    def decide(self, index: int, decision: str, modified_value: str = "") -> dict:
        ok, reason = self.hooks.run_pre("record_decision", index=index, decision=decision)
        if not ok:
            return {"ok": False, "error": reason}
        try:
            s = self.store.decide(index, decision, modified_value)
        except (ValueError, IndexError) as exc:
            return {"ok": False, "error": str(exc)}
        self.store.save()
        self.hooks.run_post("record_decision", None)
        return {"ok": True, "suggestion": s.to_dict()}

    # ---- 写回 ----
    def apply(self) -> dict:
        ok, reason = self.hooks.run_pre("apply_changes")
        if not ok:
            return {"ok": False, "error": "没有已采纳（或修改后采纳）的建议，无需写回。"}
        try:
            applied = self.store.apply_confirmed()
        except PermissionError as exc:
            return {"ok": False, "error": str(exc)}
        metrics.applied_total += len(applied)
        metrics.record_trace("apply", "写回", "完成", f"{len(applied)} 条")
        self.store.save()
        self.hooks.run_post("apply_changes", None)
        return {"ok": True, "applied": [s.to_dict() for s in applied],
                "tasks": [t.to_row() for t in self.store.tasks]}

    # ---- 导出 ----
    def export(self) -> dict:
        try:
            paths = self.store.export()
        except PermissionError as exc:
            return {"ok": False, "error": str(exc)}
        metrics.export_total += 1
        if len(paths) == 3:
            metrics.export_complete += 1
        metrics.record_trace("export", "导出", "完成", "三样产物已写入 exports/")
        self.store.save()
        self.hooks.run_post("export_outputs", None)
        return {"ok": True, "files": paths}

    # ---- 状态 ----
    def snapshot(self) -> dict:
        data = self.store.snapshot()
        data["metrics"] = metrics.snapshot()
        data["tools"] = [t["name"] for t in self.tools.schemas()]
        return data
