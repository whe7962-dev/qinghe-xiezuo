"""领域数据结构：任务表、聊天记录、建议与决定。

决定只有四种：待确认、采纳、否决、修改后采纳。
只有「采纳」和「修改后采纳」会写回对应字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 任务表字段（中文名 → 内部属性名）
FIELD_KEY = {
    "工作项": "item",
    "责任人": "owner",
    "当前安排": "status",
    "截止日": "due",
    "验收条件": "acceptance",
}
TASK_FIELDS = list(FIELD_KEY.keys())

# 任务表列（导出顺序固定）
TASK_COLUMNS = ["编号", "工作项", "责任人", "当前安排", "截止日", "验收条件"]
CHAT_COLUMNS = ["编号", "时间", "来源", "内容"]

DECISIONS = ["待确认", "采纳", "否决", "修改后采纳"]
APPLY_DECISIONS = {"采纳", "修改后采纳"}
NO_TASK_MARK = "不对应现有任务"


@dataclass
class Task:
    id: str
    item: str
    owner: str
    status: str
    due: str
    acceptance: str

    def get(self, field: str) -> str:
        if field not in FIELD_KEY:
            raise ValueError(f"未知字段：{field}")
        return getattr(self, FIELD_KEY[field])

    def set(self, field: str, value: str) -> None:
        if field not in FIELD_KEY:
            raise ValueError(f"未知字段：{field}")
        setattr(self, FIELD_KEY[field], value)

    def to_row(self) -> list[str]:
        return [self.id, self.item, self.owner, self.status, self.due, self.acceptance]


@dataclass
class Chat:
    id: str
    time: str
    source: str
    content: str

    @property
    def dedup_key(self) -> str:
        """同一批相同编号、相同正文再次导入时据此去重。"""
        return f"{self.id}|{self.content.strip()}"


@dataclass
class Suggestion:
    task_id: str
    field: str
    original_value: str
    suggested_value: str
    no_change: bool = False
    evidence: list = field(default_factory=list)   # [{chat_id, quote}]
    uncertainty: str = ""
    decision: str = "待确认"
    modified_value: str = ""

    @property
    def effective_value(self) -> str:
        """写回时采用的值：修改后采纳用修改值，否则用建议值。"""
        if self.decision == "修改后采纳":
            return self.modified_value
        return self.suggested_value

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "field": self.field,
            "original_value": self.original_value,
            "suggested_value": self.suggested_value,
            "no_change": self.no_change,
            "evidence": self.evidence,
            "uncertainty": self.uncertainty,
            "decision": self.decision,
            "modified_value": self.modified_value,
        }
