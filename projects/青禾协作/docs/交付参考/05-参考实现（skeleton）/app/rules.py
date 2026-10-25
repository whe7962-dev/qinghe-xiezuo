"""业务规则（需求文档第 5 节的十条规则，落地为可检查的约束）。

- 任务表表示当前已确认的安排；「开发中」「本期不做」等都是安排，不表示完成。
- 可提议改表的依据：项目负责人的决定；已核对且对得上验收条件的事实。
- 销售承诺/客户希望/开发自测进度单独可见，不能单独改写责任人/截止日/验收状态。
- 同一事项按时间读；后出现的负责人决定覆盖更早请求；不拿整批最后一条覆盖整表。
- 一条信息可只改一个字段；同一行其余已确认字段保持不动。
- 原有任务始终保留；某批没提到的任务原样留下。
- 没有依据不猜；输出「不建议修改」或「待核实」。
- 客户说清问题≠功能做好；开发说做完≠验收通过。
- 使用者确认之前，任务表不变。
- 同一批相同编号相同正文再次导入：不新增任务、不新增重复行动、不引入新业务事实、不覆盖已确认字段。
"""
from __future__ import annotations

from app.models import Task, Suggestion, APPLY_DECISIONS, NO_TASK_MARK


def can_apply(suggestion: Suggestion) -> bool:
    """只有采纳 / 修改后采纳写回字段；待确认与否决不改表。"""
    return suggestion.decision in APPLY_DECISIONS


def field_is_writable(field: str) -> bool:
    from app.models import FIELD_KEY
    return field in FIELD_KEY


def task_exists(tasks: list[Task], task_id: str) -> bool:
    return any(t.id == task_id for t in tasks)


def apply_suggestion(tasks: list[Task], suggestion: Suggestion) -> bool:
    """字段级更新：只改指定字段，同一行其余字段不动。返回是否实际改动。"""
    if not can_apply(suggestion):
        return False
    if not field_is_writable(suggestion.field):
        return False
    if suggestion.task_id == NO_TASK_MARK:
        return False  # 不对应现有任务 → 不新增任务
    for t in tasks:
        if t.id == suggestion.task_id:
            t.set(suggestion.field, suggestion.effective_value)
            return True
    return False


def dedup_new_chats(incoming, processed_keys: set[str]) -> tuple[list, set[str]]:
    """同一批相同编号、相同正文再次导入 → 不重复分析。返回（新聊天，本次新增的 key 集合）。"""
    new_chats = []
    new_keys = set()
    seen = set(processed_keys)
    for c in incoming:
        key = c.dedup_key
        if key in seen:
            continue
        seen.add(key)
        new_chats.append(c)
        new_keys.add(key)
    return new_chats, new_keys


def unchanged_tasks(tasks: list[Task], applied_ids: set[str]) -> list[Task]:
    """没被改到的行保持原安排，供变更说明使用。"""
    return [t for t in tasks if t.id not in applied_ids]
