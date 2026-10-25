"""任务规划（s05）：连续场景的状态跟踪 + 持久化 + 进度可查询。

载入 → 分析 → 核对 → 确认 → 导出 → 载入下一批，是一串可中断、可汇报进度的多轮流程。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import BASE_DIR

STAGES = ["载入", "分析", "核对", "确认", "导出"]
PLAN_PATH = BASE_DIR / "state" / "plan.json"


class Planner:
    def __init__(self) -> None:
        self.stage = "载入"
        self.steps: list[dict] = []

    def set_stage(self, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"未知阶段：{stage}")
        self.stage = stage

    def log_step(self, step: str, status: str, detail: str = "") -> None:
        self.steps.append({"step": step, "status": status, "detail": detail})

    def snapshot(self) -> dict:
        return {"stage": self.stage, "steps": self.steps}

    # ---- 持久化：计划与进度可恢复、可查询 ----
    def save(self) -> None:
        PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLAN_PATH.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        if not PLAN_PATH.exists():
            return
        data = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        self.stage = data.get("stage", "载入")
        self.steps = data.get("steps", [])
