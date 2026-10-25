"""工具系统（s02）：JSON schema 严格、参数校验、错误回传统一。

每个工具的输入/输出/副作用/权限在 schema 里声明；执行由 harness 统一走
「校验参数 → pre 钩子（可阻断）→ 执行 → post 钩子（可观察）」，错误统一回传 ToolResult。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class ParamError(ValueError):
    """参数校验失败。"""


@dataclass
class ToolResult:
    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "error": self.error}


def require_params(kwargs: dict, required: list[str]) -> None:
    for k in required:
        if kwargs.get(k) in (None, ""):
            raise ParamError(f"缺少参数：{k}")


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    permission: str          # allow / ask（写回类为 ask）
    fn: Callable             # fn(**kwargs) -> ToolResult

    def run(self, **kwargs) -> ToolResult:
        try:
            require_params(kwargs, list(self.input_schema.get("required", [])))
            return self.fn(**kwargs)
        except ParamError as exc:
            return ToolResult(ok=False, error=str(exc))
        except Exception as exc:  # 工具异常不打断主循环，统一回传
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "permission": self.permission,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"未知工具：{name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]


def build_tools(store) -> ToolRegistry:
    """按 方案.md 工具清单注册六个工具。store 为会话状态。"""
    from app import csv_io
    registry = ToolRegistry()

    registry.register(Tool(
        name="load_task_table",
        description="解析上传的任务表 CSV（UTF-8 带 BOM），读入编号/工作项/责任人/当前安排/截止日/验收条件",
        input_schema={"type": "object", "properties": {"csv_text": {"type": "string"}}, "required": ["csv_text"]},
        permission="allow",
        fn=lambda csv_text: ToolResult(ok=True, data={"tasks": [t.to_row() for t in csv_io.parse_task_csv(csv_text)]}),
    ))
    registry.register(Tool(
        name="load_chat_records",
        description="解析上传的一批聊天记录 CSV（UTF-8 带 BOM），读入编号/时间/来源/内容",
        input_schema={"type": "object", "properties": {"csv_text": {"type": "string"}}, "required": ["csv_text"]},
        permission="allow",
        fn=lambda csv_text: ToolResult(ok=True, data={"chats": [{"id": c.id, "source": c.source, "content": c.content}
                                                               for c in csv_io.parse_chat_csv(csv_text)]}),
    ))
    registry.register(Tool(
        name="analyze_fields",
        description="真实调用外部对话模型，对任务表字段产出建议（原值/建议值/依据原话/不确定点）",
        input_schema={"type": "object", "properties": {"tasks": {"type": "array"}, "chats": {"type": "array"}},
                      "required": ["tasks", "chats"]},
        permission="ask",
        fn=lambda tasks, chats: ToolResult(ok=True, data={}),  # 实际由 harness 调用 analyzer
    ))
    registry.register(Tool(
        name="record_decision",
        description="记录使用者对某条建议的决定：待确认/采纳/否决/修改后采纳",
        input_schema={"type": "object", "properties": {"index": {"type": "integer"}, "decision": {"type": "string"},
                                                        "modified_value": {"type": "string"}},
                      "required": ["index", "decision"]},
        permission="ask",
        fn=lambda **kw: ToolResult(ok=True, data={}),
    ))
    registry.register(Tool(
        name="apply_changes",
        description="只把已采纳/修改后采纳的建议写回对应字段；未经确认不写回",
        input_schema={"type": "object", "properties": {}, "required": []},
        permission="ask",
        fn=lambda **kw: ToolResult(ok=True, data={}),
    ))
    registry.register(Tool(
        name="export_outputs",
        description="导出更新后的任务表 CSV、建议清单 JSON、变更说明 Markdown 三样产物",
        input_schema={"type": "object", "properties": {}, "required": []},
        permission="allow",
        fn=lambda **kw: ToolResult(ok=True, data={}),
    ))
    return registry
