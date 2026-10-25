"""模型调用层（s01 Agent Loop 的模型侧）：重试、超时、token 上限、stop_reason 完整处理。

- Anthropic-compatible 网关（DeepSeek / GLM / Kimi / MiniMax / Anthropic）。
- 思考型模型（如 deepseek-v4-pro）会先输出 thinking 块，再输出 text 块；本层只取 text 块。
- 缺少密钥或调用失败抛 ModelError，由上层进入失败状态，不写回、不导出。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.observability import log_model_call, record_model_failure


class ModelError(RuntimeError):
    """模型调用失败或返回不可解析结果。"""


@dataclass
class ModelResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str = ""
    attempts: int = 1


class LLMClient:
    """真实模型客户端。测试时可用 FakeLLMClient 替换（见 tests）。"""

    def __init__(self, api_key: str, model: str, base_url: str | None, max_tokens: int,
                 max_retries: int = 2):
        if not api_key:
            raise ModelError("缺少模型密钥：请在 .env 填写 ANTHROPIC_API_KEY。")
        from anthropic import Anthropic
        self.model = model
        self.base_max_tokens = max_tokens
        self.max_retries = max_retries
        self.client = Anthropic(api_key=api_key, base_url=base_url, timeout=120.0, max_retries=0)

    def complete(self, system: str, prompt: str) -> ModelResult:
        max_tokens = self.base_max_tokens
        last_err = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._call(system, prompt, max_tokens, attempt)
            except _Truncated as exc:
                # 思考型模型思考 token 也计入 max_tokens，输出被截断时自动加倍重试一次
                if attempt < self.max_retries and max_tokens < self.base_max_tokens * 4:
                    max_tokens *= 2
                    last_err = str(exc)
                    continue
                raise ModelError(str(exc))
            except ModelError as exc:
                last_err = str(exc)
                continue
        raise ModelError(f"模型调用连续 {self.max_retries} 次失败：{last_err}")

    def _call(self, system: str, prompt: str, max_tokens: int, attempt: int) -> ModelResult:
        started = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        stop_reason = getattr(response, "stop_reason", None)
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        elapsed = time.time() - started

        if stop_reason == "refusal":
            record_model_failure(self.model, "refusal")
            raise ModelError("模型拒绝了分析请求。")
        # 只取 text 块；thinking 块跳过（思考过程不作为最终答案）
        text = "".join(getattr(b, "text", "") for b in response.content
                       if getattr(b, "type", None) == "text")
        result = ModelResult(text=text, model=self.model, input_tokens=input_tokens,
                             output_tokens=output_tokens, stop_reason=stop_reason or "",
                             attempts=attempt)
        log_model_call(self.model, input_tokens, output_tokens, elapsed, stop_reason or "")
        if stop_reason == "max_tokens":
            raise _Truncated(f"输出被截断（max_tokens={max_tokens}，本次输出 {output_tokens} tokens）")
        if not text.strip():
            record_model_failure(self.model, "empty_text")
            raise ModelError("模型返回了空的文本答案（可能只有思考块）。")
        return result


class _Truncated(Exception):
    pass


def build_client_from_env() -> LLMClient:
    from app.config import get_model_config
    cfg = get_model_config()
    return LLMClient(cfg["api_key"], cfg["model"], cfg["base_url"], cfg["max_tokens"])
