"""Post-deploy smoke test against a running app (live site, staging, or a container).

    SMOKE_PIN=... uv run python scripts/smoke.py https://grader.example.org [--commit SHA]

Checks: /health is ok (and reports ``--commit`` if given, waiting up to --wait seconds
for the new version to come up), the phone app is served, login with the tournament PIN
works, and events can be listed. Uses the grader name "smoke-test". Exit 0 = all good.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx


def wait_for_commit(c: httpx.Client, commit: str | None, wait_s: int) -> dict[str, str]:
    deadline = time.monotonic() + wait_s
    while True:
        try:
            r = c.get("/health")
            if r.status_code == 200:
                body: dict[str, str] = r.json()
                if not commit or commit.startswith(body.get("commit") or "\0"):
                    return body
                print(f"  live commit {body.get('commit')!r}, waiting for {commit[:12]}...")
        except httpx.HTTPError as exc:
            print(f"  not up yet ({type(exc).__name__})")
        if time.monotonic() > deadline:
            raise SystemExit(f"FAIL: {commit or 'app'} not live after {wait_s}s")
        time.sleep(15)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("base_url")
    p.add_argument("--commit", help="wait until /health reports this git commit")
    p.add_argument("--wait", type=int, default=900, help="seconds to wait for it")
    a = p.parse_args()
    pin = os.environ.get("SMOKE_PIN")
    if not pin:
        raise SystemExit("set SMOKE_PIN to the tournament PIN")

    with httpx.Client(base_url=a.base_url.rstrip("/"), timeout=30, follow_redirects=True) as c:
        health = wait_for_commit(c, a.commit, a.wait)
        print(f"ok   /health {health}")
        page = c.get("/")
        assert page.status_code == 200 and '<div id="root">' in page.text, "app page missing"
        print("ok   phone app served")
        if a.base_url.startswith("https://"):
            assert "strict-transport-security" in page.headers, "HSTS header missing"
            print("ok   HTTPS with HSTS")
        r = c.post("/api/login", json={"pin": pin, "grader_name": "smoke-test"})
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
        print("ok   login")
        events = c.get("/api/events")
        assert events.status_code == 200, f"events failed: {events.status_code}"
        print(f"ok   {len(events.json())} event(s)")
        c.post("/api/logout")
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
