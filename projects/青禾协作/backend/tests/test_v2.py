"""V2 后端改动测试：紧急程度、决定留痕、否决理由、导出审计。"""
import json
import re

from app.analyzer import Analyzer
from app.llm_client import ModelResult
from app.models import Suggestion, Task, Chat
from app.rules import fallback_urgency
from app.store import Store


def test_fallback_urgency_high():
    assert fallback_urgency(Suggestion("W-01", "责任人", "林川", "周宁")) == "高"
    assert fallback_urgency(Suggestion("W-01", "截止日", "9 月 18 日", "9 月 19 日")) == "高"


def test_fallback_urgency_middle():
    assert fallback_urgency(Suggestion("W-01", "当前安排", "开发中", "x")) == "中"
    assert fallback_urgency(Suggestion("W-01", "验收条件", "a", "b")) == "中"
    assert fallback_urgency(Suggestion("不对应现有任务", "", "", "待核实")) == "中"


def test_fallback_urgency_low():
    assert fallback_urgency(Suggestion("W-01", "工作项", "a", "b")) == "低"
    assert fallback_urgency(Suggestion("W-01", "责任人", "a", "b", no_change=True)) == "低"


def test_decide_sets_audit_trail():
    store = Store()
    store.processed_keys = set()
    s = Suggestion("W-01", "责任人", "林川", "周宁")
    store.suggestions = [s]
    store.decide(0, "采纳")
    assert s.decision == "采纳"
    assert s.decided_by == "维护人"
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", s.decided_at)


def test_reject_reason_recorded():
    store = Store()
    store.processed_keys = set()
    s = Suggestion("W-01", "责任人", "林川", "周宁")
    store.suggestions = [s]
    store.decide(0, "否决", reject_reason="客户尚未确认")
    assert s.reject_reason == "客户尚未确认"
    assert s.decided_at


def test_export_dict_excludes_urgency_includes_audit():
    s = Suggestion("W-01", "责任人", "林川", "周宁", urgency="高",
                   decided_at="2026-10-26 10:30:00", decided_by="维护人")
    d = s.to_export_dict()
    assert "urgency" not in d
    assert d["decided_at"] == "2026-10-26 10:30:00"
    assert d["decided_by"] == "维护人"
    assert s.to_dict()["urgency"] == "高"


def test_analyzer_urgency_rule_fallback():
    # 模型不输出 urgency 时，按规则兜底（截止日 → 高）
    resp = json.dumps({"suggestions": [{
        "task_id": "W-01", "field": "截止日", "original_value": "9 月 18 日",
        "suggested_value": "9 月 19 日", "no_change": False, "evidence": [], "uncertainty": "",
    }]})

    class Fake:
        def complete(self, system, prompt):
            return ModelResult(text=resp, model="fake", input_tokens=0, output_tokens=0)

    tasks = [Task("W-01", "x", "林川", "开发中", "9 月 18 日", "y")]
    chats = [Chat("B-01", "t", "s", "c")]
    sugg, _ = Analyzer(Fake()).analyze(tasks, chats)
    assert sugg[0].urgency == "高"


def test_undo_decision_before_apply():
    store = Store()
    store.processed_keys = set()
    s = Suggestion("W-01", "责任人", "林川", "周宁")
    store.suggestions = [s]
    store.decide(0, "采纳")
    assert s.decision == "采纳"
    store.undo_decision(0)
    assert s.decision == "待确认"
    assert s.decided_at == ""


def test_undo_decision_after_apply_reverts_field():
    store = Store()
    store.processed_keys = set()
    t = Task("W-01", "账单", "林川", "开发中", "9 月 18 日", "验收")
    store.tasks = [t]
    s = Suggestion("W-01", "责任人", "林川", "周宁")
    store.suggestions = [s]
    store.decide(0, "采纳")
    store.apply_confirmed()
    assert t.owner == "周宁"
    store.undo_decision(0)
    assert t.owner == "林川"  # 字段回退
    assert s.decision == "待确认"


def test_undo_apply_reverts_all():
    store = Store()
    store.processed_keys = set()
    t = Task("W-01", "账单", "林川", "开发中", "9 月 18 日", "验收")
    store.tasks = [t]
    s1 = Suggestion("W-01", "责任人", "林川", "周宁")
    s2 = Suggestion("W-01", "截止日", "9 月 18 日", "9 月 19 日")
    store.suggestions = [s1, s2]
    store.decide(0, "采纳")
    store.decide(1, "采纳")
    store.apply_confirmed()
    assert t.owner == "周宁" and t.due == "9 月 19 日"
    idx = store.undo_apply()
    assert len(idx) == 2
    assert t.owner == "林川" and t.due == "9 月 18 日"
    assert s1.decision == "待确认" and s2.decision == "待确认"


def test_analyzer_keeps_model_urgency():
    resp = json.dumps({"suggestions": [{
        "task_id": "W-01", "field": "责任人", "original_value": "林川",
        "suggested_value": "周宁", "no_change": False, "evidence": [], "uncertainty": "",
        "urgency": "低",
    }]})

    class Fake:
        def complete(self, system, prompt):
            return ModelResult(text=resp, model="fake", input_tokens=0, output_tokens=0)

    tasks = [Task("W-01", "x", "林川", "开发中", "9 月 18 日", "y")]
    chats = [Chat("B-01", "t", "s", "c")]
    sugg, _ = Analyzer(Fake()).analyze(tasks, chats)
    # 模型给了合法值，则保留模型的判定
    assert sugg[0].urgency == "低"
