"""TEXT 列 JSON 读写工具（契约 `C-BOOT@1` 第 3 条）。

仅用于 ``parse_sessions.draft`` 等需要手工读写的 TEXT 列；ORM 的 ``JSON`` 列
读回已自动反序列化，无需本模块。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def loads_json(value: str | None, default: Any) -> Any:
    """解析 JSON 字符串；空值或解析失败返回 ``default``。"""
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        logger.warning("loads_json: 非法 JSON 文本，已回退默认值")
        return default


def dumps_json(obj: Any) -> str:
    """序列化为 JSON 字符串（``ensure_ascii=False``，保留中文）。"""
    return json.dumps(obj, ensure_ascii=False)