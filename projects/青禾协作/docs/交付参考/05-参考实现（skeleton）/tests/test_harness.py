"""集成 Harness 测试：钩子阻断、指标采集、循环串联（FakeLLMClient，不调真实模型）。"""
import json

from app import csv_io
from app.llm_client import ModelResult
from app.store import Store

TASK_CSV = "\ufeff编号,工作项,责任人,当前安排,截止日,验收条件\n" \
    "W-01,账单导出支持全部结果,林川,开发中,9 月 18 日,跨页导出无遗漏，总额可核对\n" \
    "W-02,邀请新成员前增加审批,周宁,本期不做，保留待讨论,未定,未定\n"

CHAT_CSV = "\ufeff编号,时间,来源,内容\n" \
    "B-01,9 月 16 日 09:00,项目负责人,林川今天开始请假到 20 日。W-01 改由周宁接手，交付日调整到 19 日。\n"

RESPONSE = json.dumps({"suggestions": [{
    "task_id": "W-01", "field": "责任人", "original_value": "林川", "suggested_value": "周宁",
    "no_change": False, "evidence": [{"chat_id": "B-01", "quote": "W-01 改由周宁接手"}], "uncertainty": "",
}]})


class FakeClient:
    def complete(self, system, prompt):
        return ModelResult(text=RESPONSE, model="fake", input_tokens=1, output_tokens=1)


def _fresh_harness():
    from app.harness import Harness
    from app.observability import metrics
    # 重置全局指标，避免测试间串数
    for name in ["load_total", "analyze_total", "analyze_failures", "suggestion_total",
                 "suggestion_with_evidence", "applied_total", "export_total", "export_complete"]:
        setattr(metrics, name, 0)
    store = Store()
    store.processed_keys = set()
    return Harness(store=store, client_factory=lambda: FakeClient())


def test_harness_full_loop_and_metrics():
    h = _fresh_harness()
    r = h.load(TASK_CSV, CHAT_CSV)
    assert r["ok"] is True
    r = h.analyze()
    assert r["ok"] is True
    assert len(r["suggestions"]) == 1
    r = h.decide(0, "采纳")
    assert r["ok"] is True
    r = h.apply()
    assert r["ok"] is True
    w01 = next(t for t in h.store.tasks if t.id == "W-01")
    assert w01.owner == "周宁"
    r = h.export()
    assert r["ok"] is True and len(r["files"]) == 3
    snap = h.snapshot()
    assert snap["metrics"]["counters"]["analyze_total"] == 1
    assert snap["metrics"]["suggestion_verifiability_rate"] == 1.0


def test_harness_apply_blocked_without_confirm():
    h = _fresh_harness()
    h.load(TASK_CSV, CHAT_CSV)
    h.analyze()
    # 未做任何决定就写回 → pre 钩子阻断
    r = h.apply()
    assert r["ok"] is False
    assert "没有已采纳" in r["error"]


def test_harness_reimport_idempotent():
    h = _fresh_harness()
    h.load(TASK_CSV, CHAT_CSV)
    h.analyze()
    h.mark_analyzed = None  # 不依赖
    # 模拟：处理完后再次导入同一批
    h.store.mark_analyzed()
    r = h.load(TASK_CSV, CHAT_CSV)
    assert r["new_chat_count"] == 0
    assert r["duplicate_count"] == 1
