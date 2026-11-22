"""Helpers for API tests: an app around the test database, logins, fake sheet photos."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import Settings
from app.harness.samples import sheet_photo
from app.harness.truth import FillStyle
from app.schemas.event_setup import EventSetup
from app.services.event_import import import_event_workbook

EXAMPLES = Path(__file__).resolve().parents[2] / "event_setups"
AP_FILE = EXAMPLES / "PUSO_2026_AP_event_setup.xlsx"
PIN, ADMIN_PIN = "2468", "13579"


def settings_for(tmp: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "sqlite://",  # unused: the engine is passed in
        "tournament_pin": PIN,
        "admin_pin": ADMIN_PIN,
        "session_secret": "test-secret-" + "x" * 40,
        "reader_sync": True,
        "upload_dir": str(tmp / "uploads"),
        "cookie_secure": True,
        "frontend_dist": "off",
    }
    values.update(overrides)
    return Settings(**values)


def login(client: TestClient, name: str = "Alice", admin: bool = False) -> dict[str, Any]:
    r = client.post("/api/login", json={"pin": ADMIN_PIN if admin else PIN, "grader_name": name})
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


@cache
def ap_setup() -> EventSetup:
    setup = import_event_workbook(AP_FILE).setup
    assert setup is not None
    return setup


def sheet_jpeg(
    marks: dict[int, list[str]],
    team: list[list[int]],
    *,
    seed: int = 0,
    condition: str = "clean",
    styles: dict[str, FillStyle] | None = None,
) -> bytes:
    """A fake phone photo of an A&P sheet with exactly these marks and team digits."""
    return sheet_photo(ap_setup(), marks, team, seed=seed, condition=condition, styles=styles)


def all_correct() -> dict[int, list[str]]:
    return {q.q: list(q.correct) for q in ap_setup().questions}


def png_bytes(img: np.ndarray) -> bytes:
    ok, data = cv2.imencode(".png", img)
    assert ok
    return data.tobytes()


TEAMS_CSV = b"team_number,team_name\n1,Alpha HS\n2,Beta MS\n3,Gamma Acad\n4,Delta HS\n5,Epsilon\n"
