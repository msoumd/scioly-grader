"""Load check: upload many fake sheet photos at once and time how long each takes to be
read (upload start -> no longer "processing"). Run against staging or a local container,
never against production during a tournament.

    LOAD_ADMIN_PIN=... uv run python scripts/load_check.py http://localhost:18000 --n 60 --setup

--setup imports the example A&P event and teams 1..n first (admin PIN needed).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.harness.samples import sheet_photo, team_digits  # noqa: E402
from app.services.event_import import import_event_workbook  # noqa: E402

AP_FILE = BACKEND.parent / "event_setups" / "PUSO_2026_AP_event_setup.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def photos(n: int) -> list[bytes]:
    setup = import_event_workbook(AP_FILE).setup
    assert setup is not None
    key = {q.q: list(q.correct) for q in setup.questions}
    d = setup.event.team_number_digits
    # "phone" = a realistic mix of mild problems, like real hand-held photos.
    return [
        sheet_photo(setup, key, team_digits(t, d), seed=1000 + t, condition="phone")
        for t in range(1, n + 1)
    ]


async def one(c: httpx.AsyncClient, jpeg: bytes, i: int) -> tuple[float, float, str]:
    start = time.perf_counter()
    r = await c.post(
        "/api/scans", data={"event_code": "AP"}, files={"file": (f"{i}.jpg", jpeg, "image/jpeg")}
    )
    r.raise_for_status()
    uploaded = time.perf_counter() - start
    scan_id = r.json()["scans"][0]["id"]
    while True:
        s = (await c.get(f"/api/scans/{scan_id}")).json()
        if s["status"] != "processing":
            return uploaded, time.perf_counter() - start, s["status"]
        await asyncio.sleep(0.5)


async def run(base: str, pin: str, n: int, setup: bool, max_p95: float | None) -> None:
    print(f"making {n} fake phone photos...")
    jpegs = photos(n)
    async with httpx.AsyncClient(base_url=base, timeout=300) as c:
        r = await c.post("/api/login", json={"pin": pin, "grader_name": "load-check"})
        r.raise_for_status()
        if setup:
            await c.post(
                "/api/events/import", files={"file": (AP_FILE.name, AP_FILE.read_bytes(), XLSX)}
            )
            teams = "team_number,team_name\n" + "".join(f"{t},Load {t}\n" for t in range(1, n + 1))
            await c.post("/api/teams/import", files={"file": ("t.csv", teams.encode(), "text/csv")})
        print(f"uploading {n} sheets at once...")
        t0 = time.perf_counter()
        results = await asyncio.gather(*(one(c, j, i) for i, j in enumerate(jpegs)))
        wall = time.perf_counter() - t0
    up = sorted(r[0] for r in results)
    done = sorted(r[1] for r in results)
    statuses = {s: sum(1 for r in results if r[2] == s) for s in {r[2] for r in results}}
    q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))]  # noqa: E731
    print(f"\n{n} sheets in {wall:.1f} s = {n / wall * 60:.0f} sheets/minute")
    print(f"upload accepted: median {statistics.median(up):.2f} s, slowest {up[-1]:.2f} s")
    print(
        f"read result ready (from upload start): median {statistics.median(done):.1f} s, "
        f"95% {q(done, 0.95):.1f} s, slowest {done[-1]:.1f} s"
    )
    print(f"per sheet of reading time: {wall / n:.2f} s")
    print(f"statuses: {statuses}")
    if "failed" in statuses:
        raise SystemExit("FAIL: some sheets failed to read")
    if max_p95 is not None and q(done, 0.95) > max_p95:
        raise SystemExit(f"FAIL: 95% of results took over {max_p95} s")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("base_url")
    p.add_argument("--n", type=int, default=60)
    p.add_argument("--setup", action="store_true")
    p.add_argument("--max-p95", type=float, help="fail if 95%% of results take longer (s)")
    a = p.parse_args()
    pin = os.environ.get("LOAD_ADMIN_PIN") or sys.exit("set LOAD_ADMIN_PIN")
    asyncio.run(run(a.base_url.rstrip("/"), pin, a.n, a.setup, a.max_p95))


if __name__ == "__main__":
    main()
