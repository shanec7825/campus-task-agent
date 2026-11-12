"""统一响应与业务异常定义（契约 `C-BOOT@1`）。

约定：业务错误一律 HTTP 200 + ``code != 0``；认证失败用 HTTP 401（code=4010）；
未捕获异常用 HTTP 500（code=5000）。响应体统一为 ``{"code","msg","data"}``。
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """业务异常。由 ``main.py`` 中的全局异常处理器转换为统一响应体。"""

    def __init__(self, code: int, message: str, http_status: int = 200) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def to_payload(self) -> dict[str, Any]:
        return {"code": self.code, "msg": self.message, "data": None}


def ok(data: Any = None) -> dict[str, Any]:
    """成功响应体：``{"code":0,"msg":"ok","data":data}``。"""
    return {"code": 0, "msg": "ok", "data": data}