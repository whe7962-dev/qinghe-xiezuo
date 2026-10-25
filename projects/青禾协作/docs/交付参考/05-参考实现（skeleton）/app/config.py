"""运行配置：从 .env 注入模型服务地址、模型名与密钥。页面与日志不展示密钥。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
EXPORT_DIR = BASE_DIR / "exports"

load_dotenv(BASE_DIR / ".env", override=False)


def get_model_config() -> dict:
    """返回模型调用配置；缺少密钥时 api_key 为空字符串，调用层据此进入失败状态。"""
    return {
        "api_key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
        "model": os.getenv("MODEL_ID", "glm-5.3-flash").strip(),
        "base_url": os.getenv("ANTHROPIC_BASE_URL", "https://open.bigmodel.cn/api/anthropic").strip(),
        "max_tokens": int(os.getenv("MAX_OUTPUT_TOKENS", "16000")),
    }


def has_credentials() -> bool:
    key = get_model_config()["api_key"]
    return bool(key) and not any(m in key.lower() for m in ("xxx", "your", "你的", "placeholder"))
