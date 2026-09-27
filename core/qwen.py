"""Small, shared DashScope OpenAI-compatible Qwen client."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import requests


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = os.getenv("ANIMEWAY_QWEN_MODEL", "qwen-turbo").strip() or "qwen-turbo"


class QwenAPIError(RuntimeError):
    pass


def endpoint() -> str:
    base = os.getenv("DASHSCOPE_COMPATIBLE_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme != "https" or not parts.hostname:
        raise QwenAPIError("DashScope Base URL 必须是 HTTPS 地址")
    if base.endswith("/chat/completions"):
        return base
    if not base.endswith("/compatible-mode/v1"):
        base += "/compatible-mode/v1"
    return base + "/chat/completions"


def chat(api_key: str, messages: list[dict], *, temperature: float = 0.2,
         max_tokens: int = 1200, response_format: dict | None = None,
         timeout: tuple[int, int] = (5, 25)) -> str:
    if not isinstance(api_key, str) or not api_key.strip():
        raise QwenAPIError("尚未配置 DashScope API Key")
    body = {"model": MODEL, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "stream": False}
    if response_format:
        body["response_format"] = response_format
    try:
        response = requests.post(endpoint(), headers={"Authorization": f"Bearer {api_key.strip()}",
                                    "Content-Type": "application/json"},
                                 json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise QwenAPIError("DashScope 连接失败；检查网络和 Base URL") from exc
    if len(response.content) > 256_000:
        raise QwenAPIError("DashScope 响应超出允许大小")
    if not response.ok:
        try:
            error = response.json().get("error", {})
            detail = error.get("code") or error.get("message") or f"HTTP {response.status_code}"
        except (ValueError, AttributeError):
            detail = f"HTTP {response.status_code}"
        raise QwenAPIError(f"DashScope 请求失败：{str(detail)[:160]}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise QwenAPIError("DashScope 返回格式无效") from exc
    if not isinstance(content, str) or not content.strip():
        raise QwenAPIError("Qwen 没有返回文本")
    return content.strip()
