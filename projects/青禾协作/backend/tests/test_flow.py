"""核心循环集成测试：载入 → 分析 → 核对 → 确认 → 写回 → 导出 → 下一批 → 重复导入。

用 FakeLLMClient 注入模型输出，验证业务规则（不调用真实模型）。
"""
import json

from app import csv_io
from app.analyzer import Analyzer
from app.llm_client import ModelResult
from app.store import Store

TASK_CSV = "\ufeff编号,工作项,责任人,当前安排,截止日,验收条件\n" \
    "W-01,账单导出支持全部结果,林川,开发中,9 月 18 日,跨页导出无遗漏，总额可核对\n" \
    "W-02,邀请新成员前增加审批,周宁,本期不做，保留待讨论,未定,未定\n" \
    "W-03,旧共享链接关闭与核查,周宁,已关闭已知旧链接，等待核查,9 月 16 日,确认受影响范围，并验证旧链接不可访问\n" \
    "W-04,按项目查看费用,林川,待需求确认，未排开发,未定,明确用户分组方式及统计口径\n"

A_CHAT_CSV = "\ufeff编号,时间,来源,内容\n" \
    "A-08,9 月 15 日 13:30,客服,客户说页面现在不太顺。暂时联系不上，具体哪个页面、怎么不顺还不知道。\n"

B_CHAT_CSV = "\ufeff编号,时间,来源,内容\n" \
    "B-01,9 月 16 日 09:00,项目负责人,林川今天开始请假到 20 日。W-01 改由周宁接手，交付日调整到 19 日；跨页导出的验收条件不变。\n"

# 模型按规则给出的 A 批结果：不对应现有任务，只留待核实，不新增任务
A_RESPONSE = json.dumps({"suggestions": [{
    "task_id": "不对应现有任务", "field": "", "original_value": "",
    "suggested_value": "待核实", "no_change": False,
    "evidence": [{"chat_id": "A-08", "quote": "客户说页面现在不太顺"}],
    "uncertainty": "缺页面和具体现象",
}]})

# 模型按规则给出的 B 批结果：W-01 责任人、截止日改，验收条件不变
B_RESPONSE = json.dumps({"suggestions": [
    {"task_id": "W-01", "field": "责任人", "original_value": "林川", "suggested_value": "周宁",
     "no_change": False, "evidence": [{"chat_id": "B-01", "quote": "W-01 改由周宁接手"}], "uncertainty": ""},
    {"task_id": "W-01", "field": "截止日", "original_value": "9 月 18 日", "suggested_value": "9 月 19 日",
     "no_change": False, "evidence": [{"chat_id": "B-01", "quote": "交付日调整到 19 日"}], "uncertainty": ""},
]})


class FakeLLMClient:
    def __init__(self, text: str):
        self.text = text

    def complete(self, system, prompt):
        return ModelResult(text=self.text, model="fake", input_tokens=0, output_tokens=0)


def _new_store():
    s = Store()
    s.processed_keys = set()
    return s


def test_a_batch_unknown_stays_no_new_task():
    store = _new_store()
    store.load(csv_io.parse_task_csv(TASK_CSV), csv_io.parse_chat_csv(A_CHAT_CSV))
    suggestions, _ = Analyzer(FakeLLMClient(A_RESPONSE)).analyze(store.tasks, store.new_chats)
    store.set_suggestions(suggestions)
    store.mark_analyzed()
    # A-08 不确定 → 不新增任务，保留待核实
    assert len(store.tasks) == 4
    assert suggestions[0].task_id == "不对应现有任务"
    # 即使误点采纳，也不写回、不新增行
    store.decide(0, "采纳")
    applied = store.apply_confirmed()
    assert applied == []
    assert len(store.tasks) == 4


def test_b_batch_changes_owner_and_due_only():
    store = _new_store()
    store.load(csv_io.parse_task_csv(TASK_CSV), csv_io.parse_chat_csv(B_CHAT_CSV))
    suggestions, _ = Analyzer(FakeLLMClient(B_RESPONSE)).analyze(store.tasks, store.new_chats)
    store.set_suggestions(suggestions)
    store.mark_analyzed()
    store.decide(0, "采纳")   # 责任人
    store.decide(1, "采纳")   # 截止日
    applied = store.apply_confirmed()
    assert len(applied) == 2
    w01 = next(t for t in store.tasks if t.id == "W-01")
    assert w01.owner == "周宁"
    assert w01.due == "9 月 19 日"
    # 验收条件、工作项保持不动
    assert w01.acceptance == "跨页导出无遗漏，总额可核对"
    assert w01.item == "账单导出支持全部结果"


def test_reexport_task_csv_is_reloadable():
    store = _new_store()
    store.load(csv_io.parse_task_csv(TASK_CSV), csv_io.parse_chat_csv(B_CHAT_CSV))
    suggestions, _ = Analyzer(FakeLLMClient(B_RESPONSE)).analyze(store.tasks, store.new_chats)
    store.set_suggestions(suggestions)
    store.mark_analyzed()
    store.decide(0, "采纳")
    store.decide(1, "采纳")
    store.apply_confirmed()
    exported = csv_io.export_task_csv(store.tasks)
    again = csv_io.parse_task_csv(exported)
    assert [t.to_row() for t in again] == [t.to_row() for t in store.tasks]


def test_reimport_same_batch_no_duplicate():
    store = _new_store()
    store.load(csv_io.parse_task_csv(TASK_CSV), csv_io.parse_chat_csv(B_CHAT_CSV))
    store.mark_analyzed()
    # 再次导入同一批（相同编号、相同正文）
    info = store.load(csv_io.parse_task_csv(TASK_CSV), csv_io.parse_chat_csv(B_CHAT_CSV))
    assert info["new_chat_count"] == 0
    assert info["duplicate_count"] == 1
    assert store.new_chats == []
