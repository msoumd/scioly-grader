"""Every error response is ``{"detail": "...", "code": "..."}`` so the app can show the
sentence and act on the code."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra: Any) -> None:
        self.status, self.code, self.detail, self.extra = status, code, detail, extra
        super().__init__(detail)


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


_HTTP_CODES = {
    400: "bad_request",
    401: "not_logged_in",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "too_large",
    415: "unsupported_type",
    422: "validation_error",
    429: "too_many_requests",
}


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return "; ".join(parts) or "invalid request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code, **exc.extra}, status_code=exc.status
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": _validation_message(exc), "code": "validation_error"}, status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "error")
        return JSONResponse(
            {"detail": str(exc.detail), "code": code},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )
