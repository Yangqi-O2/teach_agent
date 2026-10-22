"""统一错误模型：前端拿到的永远是 {code, message, detail?}。"""
from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, message: str, code: str = "error", status: int = 400, detail=None):
        self.message = message
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(message)


def error_body(code: str, message: str, detail=None) -> dict:
    body = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return body


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=error_body(exc.code, exc.message, exc.detail))


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body("validation_error", "请求参数不合法", exc.errors()),
    )
