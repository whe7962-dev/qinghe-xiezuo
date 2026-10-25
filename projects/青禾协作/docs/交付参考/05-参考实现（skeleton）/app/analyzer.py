"""分析器：任务表 + 聊天记录 → 字段级建议。

- 真实调用模型，解析 JSON，做本地 schema 校验（不依赖模型输出格式完全正确）。
- 校验失败或返回不可解析时抛 ModelError，由上层进入失败状态。
"""
from __future__ import annotations

import json
import re

from app.models import Task, Chat, Suggestion, TASK_FIELDS, NO_TASK_MARK
from app import prompt
from app.llm_client import LLMClient, ModelError, ModelResult


def extract_json(text: str):
    """从模型输出里取出第一个 JSON 对象；容忍围栏与前后解释。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if "{" not in text:
        raise ModelError("模型输出里没有 JSON 对象。")
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        end = _matching_brace(text, start)
        if end is None:
            continue
        try:
            return json.loads(text[start:end + 1], strict=False)
        except json.JSONDecodeError:
            continue
    raise ModelError("模型输出的 JSON 无法解析。")


def _matching_brace(text: str, start: int) -> int | None:
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _coerce_suggestion(raw: dict) -> Suggestion:
    field = str(raw.get("field", "")).strip()
    task_id = str(raw.get("task_id", NO_TASK_MARK)).strip() or NO_TASK_MARK
    no_change = bool(raw.get("no_change", False))
    suggested = str(raw.get("suggested_value", "")).strip()
    if no_change:
        suggested = "不建议修改"
    if task_id != NO_TASK_MARK and field not in TASK_FIELDS:
        raise ModelError(f"建议字段非法：{field}")
    evidence = []
    for ev in raw.get("evidence", []) or []:
        if isinstance(ev, dict):
            evidence.append({
                "chat_id": str(ev.get("chat_id", "")).strip(),
                "quote": str(ev.get("quote", "")).strip(),
            })
    return Suggestion(
        task_id=task_id,
        field=field if task_id != NO_TASK_MARK else "",
        original_value=str(raw.get("original_value", "")).strip(),
        suggested_value=suggested,
        no_change=no_change,
        evidence=evidence,
        uncertainty=str(raw.get("uncertainty", "")).strip(),
    )


def parse_suggestions(text: str) -> list[Suggestion]:
    data = extract_json(text)
    if not isinstance(data, dict) or "suggestions" not in data:
        raise ModelError("模型输出缺少 suggestions 字段。")
    raw_list = data["suggestions"]
    if not isinstance(raw_list, list):
        raise ModelError("suggestions 必须是数组。")
    return [_coerce_suggestion(r) for r in raw_list]


class Analyzer:
    """分析入口。client 参数便于测试注入假实现。"""

    def __init__(self, client: LLMClient):
        self.client = client

    def analyze(self, tasks: list[Task], chats: list[Chat]) -> tuple[list[Suggestion], ModelResult]:
        result = self.client.complete(prompt.SYSTEM_PROMPT, prompt.build_user_prompt(tasks, chats))
        suggestions = parse_suggestions(result.text)
        # 依据核对：建议的证据必须能指回本批聊天编号，否则降级为待核实
        chat_ids = {c.id for c in chats}
        for s in suggestions:
            s.evidence = [e for e in s.evidence if e["chat_id"] in chat_ids]
        return suggestions, result
