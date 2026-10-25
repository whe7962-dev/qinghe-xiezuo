"""运行配置：从 .env 注入模型服务地址、模型名与密钥。页面与日志不展示密钥。

数据边界：程序只读写本项目内 data/ 目录（state.json、exports/、logs/），不读工作目录以外的路径。
restart-check.sh 用 QINGHE_DATA_DIR 指向临时目录，避免碰真实数据。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
load_dotenv(BASE_DIR / ".env", override=False)

DATA_DIR = Path(os.getenv("QINGHE_DATA_DIR", str(BASE_DIR / "data")))
EXPORT_DIR = DATA_DIR / "exports"                          # 三份导出产物
LOG_PATH = DATA_DIR / "logs" / "app.log"
STATE_PATH = DATA_DIR / "state.json"
PLAN_PATH = DATA_DIR / "plan.json"
SCHEMA_VERSION = 1


def get_model_config() -> dict:
    """返回模型调用配置；缺少密钥时 api_key 为空字符串，调用层据此进入失败状态。"""
    return {
        "api_key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "model": os.getenv("MODEL_ID", "deepseek-chat").strip(),
        "base_url": os.getenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic").strip(),
        "max_tokens": int(os.getenv("MAX_OUTPUT_TOKENS", "16000")),
        "timeout_seconds": float(os.getenv("MODEL_TIMEOUT_SECONDS", "170")),
    }


def has_credentials() -> bool:
    key = get_model_config()["api_key"]
    return bool(key) and not any(m in key.lower() for m in ("xxx", "your", "你的", "placeholder"))


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
