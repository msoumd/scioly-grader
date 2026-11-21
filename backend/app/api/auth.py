"""Grader login: the shared tournament PIN plus the grader's name.

The session is a signed, HTTP-only cookie (no server-side session table). The admin PIN,
if configured, logs in with the ``admin`` role for supervisor-only actions. Failed logins
are rate-limited per IP so the PIN cannot be guessed by brute force.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_settings_dep
from app.api.errors import ApiError
from app.config import Settings
from app.db.models import Grader

COOKIE = "sg_session"
Role = Literal["grader", "admin"]

router = APIRouter(prefix="/api", tags=["auth"])


@dataclass(frozen=True)
class CurrentGrader:
    id: int
    name: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class LoginRequest(BaseModel):
    pin: str = Field(min_length=1, max_length=100)
    grader_name: str = Field(min_length=1, max_length=100)

    @field_validator("grader_name")
    @classmethod
    def _tidy(cls, v: str) -> str:
        name = " ".join(v.split())
        if not name:
            raise ValueError("grader_name is blank")
        return name


class Me(BaseModel):
    id: int
    name: str
    role: Role


class LoginLimiter:
    """Failed attempts per IP in a sliding window (in memory: one web process)."""

    def __init__(self, attempts: int, window_s: int) -> None:
        self.attempts, self.window = attempts, window_s
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, ip: str, now: float) -> deque[float]:
        q = self._failures.setdefault(ip, deque())
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._recent(ip, time.monotonic())) >= self.attempts

    def fail(self, ip: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._recent(ip, now).append(now)


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="sg-session")


def _same(given: str, expected: str | None) -> bool:
    return bool(expected) and hmac.compare_digest(given.encode(), str(expected).encode())


def current_grader(
    request: Request, settings: Annotated[Settings, Depends(get_settings_dep)]
) -> CurrentGrader:
    token = request.cookies.get(COOKIE)
    if not token:
        raise ApiError(401, "not_logged_in", "Log in with the tournament PIN first")
    try:
        data = _serializer(settings).loads(token, max_age=settings.session_hours * 3600)
        return CurrentGrader(id=int(data["g"]), name=str(data["n"]), role=data["r"])
    except (BadSignature, KeyError, TypeError, ValueError) as exc:
        raise ApiError(401, "not_logged_in", "Session expired; log in again") from exc


def admin_grader(grader: Annotated[CurrentGrader, Depends(current_grader)]) -> CurrentGrader:
    if not grader.is_admin:
        raise ApiError(403, "admin_only", "Only a supervisor (admin PIN) can do this")
    return grader


GraderDep = Annotated[CurrentGrader, Depends(current_grader)]
AdminDep = Annotated[CurrentGrader, Depends(admin_grader)]


@router.post("/login", response_model=Me)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> Me:
    limiter: LoginLimiter = request.app.state.login_limiter
    ip = request.client.host if request.client else "unknown"
    if limiter.blocked(ip):
        raise ApiError(429, "too_many_attempts", "Too many wrong PINs; wait a few minutes")
    if _same(body.pin, settings.admin_pin):
        role: Role = "admin"
    elif _same(body.pin, settings.tournament_pin):
        role = "grader"
    else:
        limiter.fail(ip)
        raise ApiError(401, "wrong_pin", "Wrong PIN")

    grader = db.scalars(select(Grader).where(Grader.name == body.grader_name)).one_or_none()
    if grader is None:
        grader = Grader(name=body.grader_name)
        db.add(grader)
        db.commit()
    token = _serializer(settings).dumps({"g": grader.id, "n": grader.name, "r": role})
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return Me(id=grader.id, name=grader.name, role=role)


@router.get("/me", response_model=Me)
def me(grader: GraderDep) -> Me:
    return Me(id=grader.id, name=grader.name, role=grader.role)


@router.post("/logout", status_code=204)
def logout(response: Response, settings: Annotated[Settings, Depends(get_settings_dep)]) -> None:
    response.delete_cookie(
        COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
    )
