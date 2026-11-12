"""MaaS（OpenAI 兼容）调用封装（契约 `C-AGENT@3`，owner = T3）。

设计约束（plan `2.2.7` / T3 实现要点 2~3、7）：

* ``is_mock_mode()`` 是全仓唯一 Mock 判定来源（`2.3.1`），mock 为真时
  **不得**构造 ``OpenAI(...)``（此时 ``MAAS_API_KEY`` 可能根本不存在）。
* 单次请求 ``timeout=30.0``（含连接超时）、``max_retries=0``；
  仅在"输出不合法"时做第二次尝试（temperature 0.3 → 0.1）。
* 所有异常都转成 :class:`LLMError`（5001/5002/5003），禁止把 ``openai``
  异常直接冒泡成 HTTP 500；上层 agent 模块再转 ``ApiError``。

`C-AGENT@3` B0：DeepSeek 现役模型默认开启"思考模式"，会先输出
``reasoning_content`` 再输出正文，导致 ``content`` 为空且耗时翻倍。因此
**每次** ``chat.completions.create`` 统一追加
``extra_body={"thinking": {"type": "disabled"}}``；若服务端以 400 明确拒绝该
参数（提示中涉及 thinking / extra_body / 未知字段），则去掉 ``extra_body``
重试一次并记录 warning，同时对后续请求保持降级（避免每次白跑一次失败请求）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from openai import OpenAI

logger = logging.getLogger(__name__)

# 超时时间（秒）：连接 + 读取合计计入 30s
REQUEST_TIMEOUT_SECONDS = 30.0

# 两次尝试的温度：第二次更"保守"，提高输出合法性概率
RETRY_TEMPERATURES: tuple[float, ...] = (0.3, 0.1)

# 错误码（5001 其他异常 / 5002 请求超时 / 5003 输出不合法）
CODE_API_ERROR = 5001
CODE_TIMEOUT = 5002
CODE_INVALID_OUTPUT = 5003

# 关闭思考模式的请求参数（B0）：该模型默认思考，不关闭会先输出 reasoning_content
THINKING_DISABLED_EXTRA_BODY: dict[str, Any] = {"thinking": {"type": "disabled"}}

# 服务端 400 拒绝 thinking 参数时的识别关键词（小写匹配错误消息）
UNSUPPORTED_THINKING_HINTS: tuple[str, ...] = (
    "thinking",
    "extra_body",
    "unrecognized",
    "unknown field",
    "unknown parameter",
    "unexpected keyword",
)

# 服务端是否明确拒绝 thinking 参数（进程内缓存，避免每次请求都先失败一次）
_thinking_disabled_supported = True


class LLMError(Exception):
    """LLM 调用统一异常。

    ``code`` 与 ``ApiError`` 的错误码空间一致（500x），由 ``extractor`` /
    ``reviewer`` 转成 ``ApiError`` 后按统一响应体返回。
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def is_mock_mode() -> bool:
    """Mock 判定唯一来源（`2.3.1`）。

    为真当且仅当 ``MAAS_MOCK == "1"`` 或 ``MAAS_API_KEY`` 为空/未设置。
    """
    if _env("MAAS_MOCK") == "1":
        return True
    return not _env("MAAS_API_KEY")


def _build_client() -> OpenAI:
    """构造 OpenAI 客户端（仅在非 mock 模式下调用）。"""
    if is_mock_mode():  # 防御性断言：mock 模式绝不允许联网
        raise LLMError(CODE_API_ERROR, "mock 模式下禁止构造真实 LLM 客户端")

    api_key = _env("MAAS_API_KEY")
    if not api_key:
        raise LLMError(CODE_API_ERROR, "未配置 MAAS_API_KEY，无法调用 LLM")

    base_url = _env("MAAS_BASE_URL")
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": REQUEST_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _model_name() -> str:
    model = _env("MAAS_MODEL")
    if not model:
        raise LLMError(CODE_API_ERROR, "未配置 MAAS_MODEL，无法调用 LLM")
    return model


def _strip_code_fence(text: str) -> str:
    """去掉模型偶发的 markdown 代码块包裹（不改变 JSON 内容）。"""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _is_timeout(exc: BaseException) -> bool:
    """判断是否超时类异常（SDK 的 APITimeoutError / 内置 TimeoutError）。"""
    timeout_type = getattr(__import__("openai"), "APITimeoutError", None)
    if timeout_type is not None and isinstance(exc, timeout_type):
        return True
    return isinstance(exc, TimeoutError)


def _is_unsupported_thinking(exc: BaseException) -> bool:
    """服务端是否以 400 明确拒绝 ``extra_body`` 里的 thinking 参数（B0 降级判定）。"""
    if getattr(exc, "status_code", None) != 400:
        return False
    text = str(exc).lower()
    return any(hint in text for hint in UNSUPPORTED_THINKING_HINTS)


def _create_completion(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_payload: str,
    temperature: float,
    *,
    disable_thinking: bool,
) -> Any:
    """构造并执行一次 ``chat.completions.create``（B0：默认关闭思考模式）。"""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if disable_thinking:
        kwargs["extra_body"] = THINKING_DISABLED_EXTRA_BODY
    return client.chat.completions.create(**kwargs)


def _attempt_once(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_payload: str,
    temperature: float,
) -> str:
    """执行一次 chat 调用，返回原始文本内容；异常已映射为 ``LLMError``。

    思考模式关闭（B0）：先带 ``extra_body``；若服务端 400 拒绝该参数，则去掉
    ``extra_body`` 重试一次并记 warning（同时降级后续请求）。
    """
    global _thinking_disabled_supported

    try:
        try:
            response = _create_completion(
                client,
                model,
                system_prompt,
                user_payload,
                temperature,
                disable_thinking=_thinking_disabled_supported,
            )
        except Exception as exc:  # noqa: BLE001 - 仅识别 thinking 参数降级，其余原样上抛
            if not _thinking_disabled_supported or not _is_unsupported_thinking(exc):
                raise
            _thinking_disabled_supported = False
            logger.warning(
                "服务端拒绝 thinking 参数（400），已降级为不传 extra_body 并重试一次: %s", exc
            )
            response = _create_completion(
                client,
                model,
                system_prompt,
                user_payload,
                temperature,
                disable_thinking=False,
            )
    except Exception as exc:  # noqa: BLE001 - 统一转换为 LLMError
        if _is_timeout(exc):
            logger.warning("LLM 请求超时（%.0fs）: %s", REQUEST_TIMEOUT_SECONDS, exc)
            raise LLMError(CODE_TIMEOUT, "LLM 请求超时，请稍后重试") from exc
        logger.warning("LLM 请求失败: %s", exc)
        raise LLMError(CODE_API_ERROR, "LLM 调用失败，请稍后重试") from exc

    choices = getattr(response, "choices", None) or []
    if not choices:
        raise LLMError(CODE_INVALID_OUTPUT, "LLM 未返回任何候选结果")
    content = getattr(getattr(choices[0], "message", None), "content", None)
    if not isinstance(content, str) or not content.strip():
        raise LLMError(CODE_INVALID_OUTPUT, "LLM 返回内容为空")
    return content


def _parse_and_validate(
    content: str,
    validate: Callable[[dict], Any] | None,
) -> Any:
    """解析 JSON 并做 Pydantic 校验；任何不合法都抛 ``LLMError``。"""
    try:
        payload = json.loads(_strip_code_fence(content))
    except (TypeError, ValueError) as exc:
        raise LLMError(CODE_INVALID_OUTPUT, "LLM 输出不是合法 JSON") from exc

    if not isinstance(payload, dict):
        raise LLMError(CODE_INVALID_OUTPUT, "LLM 输出必须是 JSON 对象")

    if validate is None:
        return payload

    try:
        return validate(payload)
    except Exception as exc:  # noqa: BLE001 - Pydantic 校验失败统一按"输出不合法"处理
        logger.warning("LLM 输出未通过校验: %s", exc)
        raise LLMError(CODE_INVALID_OUTPUT, "LLM 输出不符合约定 Schema") from exc


def chat_json(
    system_prompt: str,
    user_payload: str,
    validate: Callable[[dict], Any] | None = None,
) -> Any:
    """调用 MaaS 并返回 JSON（可选 Pydantic 校验）。

    :param system_prompt: System Prompt（已填充占位符）
    :param user_payload: User 消息（JSON 字符串）
    :param validate: ``dict -> 校验后的对象``；为 ``None`` 时仅做 JSON 解析
    :returns: ``validate`` 的返回值（未提供时为 ``dict``）

    语义：
    * 最多 2 次尝试（temperature 0.3 → 0.1），**只在输出不合法时重试**；
    * 请求超时 ⇒ ``LLMError(5002)``；其他 SDK/网络异常 ⇒ ``LLMError(5001)``；
    * 两次输出仍不合法 ⇒ ``LLMError(5003)``。
    """
    if is_mock_mode():
        raise LLMError(CODE_API_ERROR, "mock 模式下不允许调用真实 LLM")

    client = _build_client()
    model = _model_name()

    last_error: LLMError | None = None
    for temperature in RETRY_TEMPERATURES:
        content = _attempt_once(client, model, system_prompt, user_payload, temperature)
        try:
            return _parse_and_validate(content, validate)
        except LLMError as exc:
            if exc.code != CODE_INVALID_OUTPUT:
                raise
            last_error = exc
            logger.info("LLM 输出不合法，temperature=%.1f 后重试一次", temperature)

    raise last_error or LLMError(CODE_INVALID_OUTPUT, "LLM 输出不符合约定 Schema")


__all__ = [
    "LLMError",
    "REQUEST_TIMEOUT_SECONDS",
    "RETRY_TEMPERATURES",
    "CODE_API_ERROR",
    "CODE_TIMEOUT",
    "CODE_INVALID_OUTPUT",
    "THINKING_DISABLED_EXTRA_BODY",
    "UNSUPPORTED_THINKING_HINTS",
    "chat_json",
    "is_mock_mode",
]