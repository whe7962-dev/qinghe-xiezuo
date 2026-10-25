"""会话状态：任务表、聊天、建议、决定、已处理批次、流程阶段。

- 服务内存为主，state.json 兜底持久化，保证 A 批 → B 批 → 重复导入的连续场景。
- 导出物（任务表 CSV、建议清单、变更说明）写进 exports/。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import STATE_PATH, SCHEMA_VERSION
from app.models import Task, Chat, Suggestion
from app.planner import Planner
from app.hooks import AuditLog


class Store:
    def __init__(self) -> None:
        self.tasks: list[Task] = []
        self.chats: list[Chat] = []          # 当前这批已载入的聊天（含重复导入的）
        self.new_chats: list[Chat] = []      # 本批中尚未分析过的新聊天
        self.suggestions: list[Suggestion] = []
        self.processed_keys: set[str] = set()
        self.planner = Planner()
        self.audit = AuditLog()
        self.last_error: str = ""
        # 已确认字段快照：task_id -> {field: value}；重复导入时据此校验未被覆盖
        self.applied_fields: dict[str, dict[str, str]] = {}
        self.planner.load()

    # ---- 载入 ----
    def load(self, tasks: list[Task], chats: list[Chat]) -> dict:
        from app.rules import dedup_new_chats
        previous = {t.id: t for t in self.tasks}
        self.tasks = tasks
        self.chats = chats
        new_chats, new_keys = dedup_new_chats(chats, self.processed_keys)
        self.new_chats = new_chats
        self.suggestions = []
        self.planner.set_stage("载入")
        self.planner.log_step("载入", "完成",
                              f"任务表 {len(tasks)} 行；聊天 {len(chats)} 条，其中新增 {len(new_chats)} 条、重复 {len(chats) - len(new_chats)} 条")

        # 重复导入时校验：之前确认过的字段是否被新载入的表覆盖
        protected = total = 0
        if len(new_chats) < len(chats):
            for task_id, fields in self.applied_fields.items():
                for field, value in fields.items():
                    total += 1
                    cur = next((t for t in tasks if t.id == task_id), None)
                    if cur is not None and cur.get(field) == value:
                        protected += 1

        return {
            "task_count": len(tasks),
            "chat_count": len(chats),
            "new_chat_count": len(new_chats),
            "duplicate_count": len(chats) - len(new_chats),
            "new_keys": sorted(new_keys),
            "protected_fields": protected,
            "protected_total": total,
        }

    # ---- 分析 ----
    def set_suggestions(self, suggestions: list[Suggestion]) -> None:
        self.suggestions = suggestions
        self.planner.set_stage("分析")
        self.planner.log_step("分析", "完成", f"产生 {len(suggestions)} 条建议")

    def mark_analyzed(self) -> None:
        """本批新聊天已分析完，记入 processed_keys，重复导入不再处理。"""
        for c in self.new_chats:
            self.processed_keys.add(c.dedup_key)

    # ---- 核对 / 确认 ----
    def decide(self, index: int, decision: str, modified_value: str = "", reject_reason: str = "") -> Suggestion:
        from datetime import datetime
        from app.models import DECISIONS
        if decision not in DECISIONS:
            raise ValueError(f"决定只能是：{'、'.join(DECISIONS)}")
        if not (0 <= index < len(self.suggestions)):
            raise IndexError("建议序号越界")
        s = self.suggestions[index]
        s.decision = decision
        if decision == "修改后采纳":
            s.modified_value = modified_value  # 只改建议值，原值不变（6.4 #3）
        if decision == "否决":
            s.reject_reason = reject_reason.strip()
        s.decided_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        s.decided_by = "维护人"
        self.audit.record_decision(s)
        self.planner.set_stage("确认")
        return s

    # ---- 写回 ----
    def apply_confirmed(self) -> list[Suggestion]:
        from app.rules import apply_suggestion
        from app.permission import guard_apply, guard_field
        applied = []
        snapshot: dict[str, dict[str, str]] = {}  # task_id -> {field: 写回前的值}
        for s in self.suggestions:
            if s.decision not in ("采纳", "修改后采纳"):
                continue
            guard_apply(s)
            guard_field(s.field) if s.field else None
            old = None
            for t in self.tasks:
                if t.id == s.task_id:
                    old = t.get(s.field)
                    break
            if apply_suggestion(self.tasks, s):
                applied.append(s)
                if old is not None:
                    snapshot.setdefault(s.task_id, {})[s.field] = old
                self.applied_fields.setdefault(s.task_id, {})[s.field] = s.effective_value
        self.last_apply = {
            "indices": [self.suggestions.index(s) for s in applied],
            "snapshot": snapshot,
        }
        self.planner.set_stage("确认")
        self.planner.log_step("写回", "完成", f"写回 {len(applied)} 条建议")
        return applied

    # ---- 撤销（产品经理要求，改 PRD 6.3 #5：由不提供改为提供）----
    def undo_decision(self, index: int) -> Suggestion:
        """撤销单条决定：回到待确认；若该字段已写回，一并回退任务表。"""
        if not (0 <= index < len(self.suggestions)):
            raise IndexError("建议序号越界")
        s = self.suggestions[index]
        if s.decision == "待确认":
            return s
        if s.task_id != "不对应现有任务" and s.field and s.task_id in self.applied_fields \
                and s.field in self.applied_fields.get(s.task_id, {}):
            for t in self.tasks:
                if t.id == s.task_id:
                    t.set(s.field, s.original_value)
                    break
            self.applied_fields[s.task_id].pop(s.field, None)
        s.decision = "待确认"
        s.decided_at = ""
        s.decided_by = ""
        s.modified_value = ""
        s.reject_reason = ""
        self.planner.set_stage("确认")
        return s

    def undo_apply(self) -> list[int]:
        """撤销本次写回：回退任务表，并把已写回的建议重置为待确认。"""
        last = getattr(self, "last_apply", None)
        if not last:
            return []
        snapshot: dict[str, dict[str, str]] = last["snapshot"]
        indices: list[int] = last["indices"]
        for task_id, fields in snapshot.items():
            for t in self.tasks:
                if t.id == task_id:
                    for field, old in fields.items():
                        t.set(field, old)
                    break
            for field in fields:
                if task_id in self.applied_fields:
                    self.applied_fields[task_id].pop(field, None)
        for i in indices:
            if 0 <= i < len(self.suggestions):
                s = self.suggestions[i]
                s.decision = "待确认"
                s.decided_at = ""
                s.decided_by = ""
                s.modified_value = ""
                s.reject_reason = ""
        self.last_apply = None
        self.planner.set_stage("确认")
        self.planner.log_step("撤销写回", "完成", f"撤销 {len(indices)} 条写回")
        return indices

    # ---- 导出 ----
    def export(self) -> dict:
        from app.csv_io import export_task_csv, write_utf8_bom
        from app.hooks import build_change_log, build_review_pack
        from app.config import EXPORT_DIR
        from app.permission import guard_export_path

        tasks_before = self.tasks  # 写回后即当前值；变更说明由 hooks 依据建议列表生成
        # 变更说明需要写回前后对比，此处用「应用过的建议」重建 before 值
        applied = [s for s in self.suggestions if s.decision in ("采纳", "修改后采纳")]
        before_map = {t.id: _revert(t, applied) for t in self.tasks}

        task_csv = export_task_csv(self.tasks)
        review_pack = build_review_pack(self.suggestions)
        change_log = build_change_log(list(before_map.values()), self.tasks, applied,
                                      [s for s in self.suggestions if s.decision not in ("采纳", "修改后采纳")])

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        paths = {}
        p1 = EXPORT_DIR / "任务表.csv"
        p2 = EXPORT_DIR / "建议清单.json"
        p3 = EXPORT_DIR / "变更说明.md"
        guard_export_path(p1), guard_export_path(p2), guard_export_path(p3)
        write_utf8_bom(p1, task_csv)
        write_utf8_bom(p2, review_pack)
        write_utf8_bom(p3, change_log)
        paths = {"task_table": str(p1), "review_pack": str(p2), "change_log": str(p3)}

        self.planner.set_stage("导出")
        self.planner.log_step("导出", "完成", f"任务表 / 建议清单 / 变更说明 已写入 exports/")
        self.planner.save()
        return paths

    # ---- 状态 ----
    def snapshot(self) -> dict:
        return {
            "tasks": [t.to_row() for t in self.tasks],
            "chats": [{"id": c.id, "time": c.time, "source": c.source, "content": c.content} for c in self.chats],
            "new_chats": [c.id for c in self.new_chats],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "stage": self.planner.stage,
            "steps": self.planner.steps,
            "last_error": self.last_error,
        }

    def save(self) -> None:
        import os
        import tempfile
        data = {
            "schema_version": SCHEMA_VERSION,
            "processed_keys": sorted(self.processed_keys),
            "tasks": [t.to_row() for t in self.tasks],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "applied_fields": self.applied_fields,
        }
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(STATE_PATH.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False, indent=2))
            os.replace(tmp, STATE_PATH)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load_state(self) -> None:
        if not STATE_PATH.exists():
            return
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.last_error = "state.json 损坏，已回退到空状态。"
            return
        self.processed_keys = set(data.get("processed_keys", []))
        self.applied_fields = data.get("applied_fields", {})
        try:
            self.tasks = [Task(*r) for r in data.get("tasks", [])]
            self.suggestions = [_suggestion_from_dict(d) for d in data.get("suggestions", [])]
        except (TypeError, ValueError, KeyError):
            pass  # 旧数据或结构不兼容时，只恢复幂等键与已确认快照


def _suggestion_from_dict(d: dict) -> Suggestion:
    return Suggestion(
        task_id=d.get("task_id", ""),
        field=d.get("field", ""),
        original_value=d.get("original_value", ""),
        suggested_value=d.get("suggested_value", ""),
        no_change=bool(d.get("no_change", False)),
        evidence=list(d.get("evidence", []) or []),
        uncertainty=d.get("uncertainty", ""),
        decision=d.get("decision", "待确认"),
        modified_value=d.get("modified_value", ""),
        urgency=d.get("urgency", "中"),
        decided_at=d.get("decided_at", ""),
        decided_by=d.get("decided_by", ""),
        reject_reason=d.get("reject_reason", ""),
    )


def _revert(task: Task, applied: list[Suggestion]) -> Task:
    """按应用过的建议把任务回退到写回前的值，供变更说明对比。"""
    from app.models import Task as T
    reverted = T(task.id, task.item, task.owner, task.status, task.due, task.acceptance)
    for s in applied:
        if s.task_id == task.id:
            reverted.set(s.field, s.original_value)
    return reverted


# 全局单例（骨架第一版为单进程、单人使用）
store = Store()
store.load_state()
