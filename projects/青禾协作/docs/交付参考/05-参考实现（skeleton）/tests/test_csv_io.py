"""CSV 读写测试：BOM、列校验、导出可再次载入。"""
import pytest

from app import csv_io
from app.csv_io import CsvError

TASK_CSV = "\ufeff编号,工作项,责任人,当前安排,截止日,验收条件\nW-01,账单导出支持全部结果,林川,开发中,9 月 18 日,跨页导出无遗漏，总额可核对\n"
CHAT_CSV = "\ufeff编号,时间,来源,内容\nA-01,9 月 15 日 09:00,客户甲／客服转交,账单比页面少了两千多\n"


def test_parse_task_csv_with_bom():
    tasks = csv_io.parse_task_csv(TASK_CSV)
    assert len(tasks) == 1
    assert tasks[0].id == "W-01"
    assert tasks[0].owner == "林川"


def test_export_roundtrip_with_bom():
    tasks = csv_io.parse_task_csv(TASK_CSV)
    exported = csv_io.export_task_csv(tasks)
    assert exported.startswith("\ufeff")
    again = csv_io.parse_task_csv(exported)
    assert again[0].to_row() == tasks[0].to_row()


def test_parse_chat_csv():
    chats = csv_io.parse_chat_csv(CHAT_CSV)
    assert chats[0].id == "A-01"
    assert chats[0].source == "客户甲／客服转交"


def test_missing_column_raises():
    with pytest.raises(CsvError):
        csv_io.parse_task_csv("\ufeff编号,工作项\nW-01,xx\n")


def test_empty_raises():
    with pytest.raises(CsvError):
        csv_io.parse_task_csv("")
