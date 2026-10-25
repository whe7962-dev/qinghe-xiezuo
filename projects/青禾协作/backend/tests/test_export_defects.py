"""导出缺陷回归测试：双 BOM、重导入字段保护率。"""
from pathlib import Path
import tempfile

from app import csv_io
from app.models import Task, Suggestion
from app.store import Store

TASK_CSV = "\ufeff编号,工作项,责任人,当前安排,截止日,验收条件\n" \
    "W-01,账单导出支持全部结果,林川,开发中,9 月 18 日,跨页导出无遗漏，总额可核对\n"
CHAT_CSV = "\ufeff编号,时间,来源,内容\n" \
    "B-01,9 月 16 日 09:00,项目负责人,W-01 改由周宁接手\n"


def test_no_double_bom_on_write():
    tasks = csv_io.parse_task_csv(TASK_CSV)
    text = csv_io.export_task_csv(tasks)   # 自带一个 BOM
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "任务表.csv"
        csv_io.write_utf8_bom(p, text)
        raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    # 只允许一个 BOM：紧接 BOM 的不能又是 BOM
    assert not raw[3:].startswith(b"\xef\xbb\xbf"), "出现双 BOM"
    # 仍可再次载入
    assert csv_io.parse_task_csv(raw.decode("utf-8-sig"))[0].id == "W-01"


def test_applied_fields_tracked_for_protection_rate():
    store = Store()
    store.processed_keys = set()
    store.applied_fields = {}
    store.load(csv_io.parse_task_csv(TASK_CSV), csv_io.parse_chat_csv(CHAT_CSV))
    store.mark_analyzed()          # 标记本批已处理，再次导入才算重复
    store.suggestions = [Suggestion("W-01", "责任人", "林川", "周宁", decision="采纳")]
    store.apply_confirmed()
    assert store.applied_fields["W-01"]["责任人"] == "周宁"

    # 带着已确认值再导入同一批 → 应记为受保护
    updated = csv_io.export_task_csv(store.tasks)
    info = store.load(csv_io.parse_task_csv(updated), csv_io.parse_chat_csv(CHAT_CSV))
    assert info["duplicate_count"] == 1
    assert info["protected_total"] >= 1
    assert info["protected_fields"] >= 1
