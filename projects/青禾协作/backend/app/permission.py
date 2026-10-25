"""权限系统（s03）：写回门槛。

任务表写回属于对外部状态的写入操作，未经使用者逐条采纳，任务表不变。
"""
from __future__ import annotations

from app.models import Suggestion
from app.rules import can_apply


class PermissionError(Exception):
    """越权：未经确认的写回、未知字段、越出工作区等。"""


def guard_apply(suggestion: Suggestion) -> None:
    """写回前校验：缺决定即拒绝，任务表保持不变。"""
    if not can_apply(suggestion):
        raise PermissionError(
            f"建议 {suggestion.task_id}.{suggestion.field} 尚未被采纳，不得写回任务表。"
        )


def guard_field(field: str) -> None:
    from app.models import FIELD_KEY
    if field not in FIELD_KEY:
        raise PermissionError(f"字段「{field}」不在任务表字段范围内。")


def guard_export_path(path) -> None:
    """导出只允许写入项目内 exports/ 目录（数据访问边界，默认限定在项目内）。"""
    from app.config import EXPORT_DIR
    resolved = path.resolve()
    if not str(resolved).startswith(str(EXPORT_DIR.resolve())):
        raise PermissionError(f"导出路径越出允许范围：{resolved}")
