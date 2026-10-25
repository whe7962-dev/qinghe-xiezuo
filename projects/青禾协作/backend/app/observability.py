"""可观测性：结构化日志、指标、轨迹（对齐 PRD 的可观测 / 可度量验收标准）。

指标口径（对齐 PRD 成功标准）：
- 三样产物齐全率：导出是否每次都产出 任务表 / 建议清单 / 变更说明。
- 建议可核对率：含聊天编号与原话引用的建议条数 ÷ 建议总条数。
- 重复导入幂等率：重复导入后新增行数为 0 的批次占比。
- 已确认字段保护率：重复导入后已确认字段未变更数 ÷ 已确认字段总数。
- 模型调用失败率：分析失败次数 ÷ 分析总次数。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.config import LOG_PATH

logger = logging.getLogger("qinghe")


def setup_logging() -> None:
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(sh)


def log_event(event: str, **kwargs) -> None:
    setup_logging()
    detail = " ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info("%s %s", event, detail)


def log_model_call(model: str, input_tokens: int, output_tokens: int, elapsed: float, stop_reason: str) -> None:
    log_event("model_call", model=model, in_tokens=input_tokens, out_tokens=output_tokens,
              secs=round(elapsed, 2), stop=stop_reason)


def record_model_failure(model: str, reason: str) -> None:
    log_event("model_failure", model=model, reason=reason)


@dataclass
class Metrics:
    """运行期指标累计。"""
    load_total: int = 0
    duplicate_loads: int = 0
    analyze_total: int = 0
    analyze_failures: int = 0
    suggestion_total: int = 0
    suggestion_with_evidence: int = 0
    applied_total: int = 0
    export_total: int = 0
    export_complete: int = 0            # 三样产物齐全次数
    reimport_total: int = 0             # 重复导入批次次数
    reimport_zero_new_rows: int = 0     # 重复导入且 0 新增行次数
    confirmed_fields_total: int = 0     # 重复导入时应保护的已确认字段数
    confirmed_fields_protected: int = 0
    traces: list = field(default_factory=list)

    # ---- 派生指标 ----
    def snapshot(self) -> dict:
        return {
            "model_failure_rate": _ratio(self.analyze_failures, self.analyze_total),
            "suggestion_verifiability_rate": _ratio(self.suggestion_with_evidence, self.suggestion_total),
            "reimport_idempotency_rate": _ratio(self.reimport_zero_new_rows, self.reimport_total),
            "confirmed_field_protection_rate": _ratio(self.confirmed_fields_protected, self.confirmed_fields_total),
            "export_completeness_rate": _ratio(self.export_complete, self.export_total),
            "counters": {
                "load_total": self.load_total,
                "analyze_total": self.analyze_total,
                "analyze_failures": self.analyze_failures,
                "suggestion_total": self.suggestion_total,
                "applied_total": self.applied_total,
                "export_total": self.export_total,
            },
        }

    def record_trace(self, batch: str, step: str, status: str, detail: str = "") -> None:
        self.traces.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "batch": batch,
                            "step": step, "status": status, "detail": detail})
        if len(self.traces) > 200:
            self.traces = self.traces[-200:]


def _ratio(numerator: int, denominator: int):
    if not denominator:
        return None
    return round(numerator / denominator, 4)


metrics = Metrics()
setup_logging()
