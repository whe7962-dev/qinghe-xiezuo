"""CSV 读写：UTF-8 带 BOM，保留原始编号与正文含义。

读入：任务表（编号、工作项、责任人、当前安排、截止日、验收条件）
      聊天记录（编号、时间、来源、内容）
导出：更新后的完整任务表（可再次作为现有任务表载入）。
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from app.models import TASK_COLUMNS, CHAT_COLUMNS, Task, Chat


class CsvError(ValueError):
    """CSV 解析失败，页面应进入失败状态。"""


def _sniff_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t").delimiter
    except Exception:
        return ","


def _rows(text: str) -> list[list[str]]:
    text = text.lstrip("\ufeff")  # 去 BOM
    if not text.strip():
        raise CsvError("文件为空")
    delim = _sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any(c.strip() for c in r)]
    return rows


def _require_columns(rows: list[list[str]], expected: list[str], kind: str) -> None:
    header = [c.strip() for c in rows[0]]
    missing = [c for c in expected if c not in header]
    if missing:
        raise CsvError(f"{kind}缺少列：{'、'.join(missing)}（现有：{'、'.join(header)}）")


def parse_task_csv(text: str) -> list[Task]:
    rows = _rows(text)
    _require_columns(rows, TASK_COLUMNS, "任务表")
    header = [c.strip() for c in rows[0]]
    idx = {name: header.index(name) for name in TASK_COLUMNS}
    tasks: list[Task] = []
    for r in rows[1:]:
        if len(r) < len(TASK_COLUMNS):
            raise CsvError(f"任务表第 {len(tasks) + 2} 行列数不足")
        tasks.append(Task(
            id=r[idx["编号"]].strip(),
            item=r[idx["工作项"]].strip(),
            owner=r[idx["责任人"]].strip(),
            status=r[idx["当前安排"]].strip(),
            due=r[idx["截止日"]].strip(),
            acceptance=r[idx["验收条件"]].strip(),
        ))
    if not tasks:
        raise CsvError("任务表没有数据行")
    return tasks


def parse_chat_csv(text: str) -> list[Chat]:
    rows = _rows(text)
    _require_columns(rows, CHAT_COLUMNS, "聊天记录")
    header = [c.strip() for c in rows[0]]
    idx = {name: header.index(name) for name in CHAT_COLUMNS}
    chats: list[Chat] = []
    for r in rows[1:]:
        if len(r) < len(CHAT_COLUMNS):
            raise CsvError(f"聊天记录第 {len(chats) + 2} 行列数不足")
        chats.append(Chat(
            id=r[idx["编号"]].strip(),
            time=r[idx["时间"]].strip(),
            source=r[idx["来源"]].strip(),
            content=r[idx["内容"]].strip(),
        ))
    if not chats:
        raise CsvError("聊天记录没有数据行")
    return chats


def export_task_csv(tasks: list[Task]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TASK_COLUMNS)
    for t in tasks:
        writer.writerow(t.to_row())
    return "\ufeff" + buf.getvalue()  # UTF-8 带 BOM


def write_utf8_bom(path: Path, text: str) -> Path:
    """写入 UTF-8 带 BOM 文件。先去掉文本自带的 BOM，避免 utf-8-sig 再写一次导致双 BOM。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.lstrip("\ufeff"), encoding="utf-8-sig")
    return path
