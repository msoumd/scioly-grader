"""Login, sessions, roles, rate limiting, cookie safety, error format, security headers."""

from fastapi.testclient import TestClient

from tests.api_support import ADMIN_PIN, PIN, login


def test_login_sets_safe_cookie_and_me(api: TestClient) -> None:
    r = api.post("/api/login", json={"pin": PIN, "grader_name": "  Alice   Smith "})
    assert r.status_code == 200
    assert r.json()["name"] == "Alice Smith" and r.json()["role"] == "grader"
    cookie = r.headers["set-cookie"].lower()
    assert "sg_session=" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert api.get("/api/me").json() == r.json()


def test_same_name_same_grader(api: TestClient) -> None:
    first = login(api, "Bob")
    api.post("/api/logout")
    assert login(api, "Bob")["id"] == first["id"]
    assert login(api, "Carol")["id"] != first["id"]


def test_admin_pin_gives_admin_role(api: TestClient) -> None:
    assert login(api, "Supervisor", admin=True)["role"] == "admin"


def test_wrong_pin(api: TestClient) -> None:
    r = api.post("/api/login", json={"pin": "0000", "grader_name": "Eve"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Wrong PIN", "code": "wrong_pin"}
    assert "set-cookie" not in r.headers


def test_wrong_pins_are_rate_limited(api: TestClient) -> None:
    for _ in range(10):
        assert api.post("/api/login", json={"pin": "bad", "grader_name": "Eve"}).status_code == 401
    r = api.post("/api/login", json={"pin": PIN, "grader_name": "Eve"})
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"


def test_login_validation(api: TestClient) -> None:
    r = api.post("/api/login", json={"pin": PIN, "grader_name": "   "})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert "grader_name" in r.json()["detail"]


def test_routes_need_login(api: TestClient) -> None:
    for method, path in [("get", "/api/me"), ("get", "/api/events"), ("get", "/api/teams"),
                         ("get", "/api/scans/1"), ("get", "/api/events/AP/results")]:  # fmt: skip
        r = getattr(api, method)(path)
        assert r.status_code == 401 and r.json()["code"] == "not_logged_in", path


def test_admin_only_routes(api: TestClient) -> None:
    login(api, "Grader")
    files = {"file": ("x.csv", b"team_number,team_name\n1,A\n", "text/csv")}
    for r in [
        api.post("/api/teams/import", files=files),
        api.post(
            "/api/events/import", files={"file": ("x.xlsx", b"x", "application/octet-stream")}
        ),
        api.get("/api/audit"),
        api.post("/api/events/AP/rescore"),
        api.post("/api/events/AP/teams/1/counted-scan", json={"scan_id": 1}),
    ]:
        assert r.status_code == 403 and r.json()["code"] == "admin_only", r.request.url


def test_tampered_or_expired_cookie(api: TestClient) -> None:
    login(api)
    good = api.cookies.get("sg_session")
    assert good
    api.cookies.clear()
    api.cookies.set("sg_session", good[:-3] + "abc")
    assert api.get("/api/me").status_code == 401
    api.cookies.clear()
    api.cookies.set("sg_session", "not-a-session")
    assert api.get("/api/me").json()["code"] == "not_logged_in"


def test_logout(api: TestClient) -> None:
    login(api)
    assert api.post("/api/logout").status_code == 204
    api.cookies.clear()
    assert api.get("/api/me").status_code == 401


def test_cookie_not_sent_over_plain_http(api: TestClient) -> None:
    """The cookie is Secure: a browser never sends it over plain http."""
    login(api)
    insecure = TestClient(api.app, base_url="http://testserver")
    insecure.cookies = api.cookies
    assert insecure.get("/api/me").status_code == 401


def test_security_headers_and_request_id(api: TestClient) -> None:
    r = api.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert len(api.get("/health").headers["x-request-id"]) == 12


def test_unknown_route_error_shape(api: TestClient) -> None:
    r = api.get("/api/nope")
    assert r.status_code == 404 and r.json()["code"] == "not_found"


def test_openapi_lists_routes(api: TestClient) -> None:
    paths = api.get("/openapi.json").json()["paths"]
    for p in ["/api/login", "/api/events/import", "/api/scans", "/api/scans/{scan_id}",
              "/api/events/{code}/results.csv", "/api/events/{code}/duplicates",
              "/api/events/{code}/teams/{team_number}/free-response", "/api/audit"]:  # fmt: skip
        assert p in paths, p
    assert ADMIN_PIN not in api.get("/openapi.json").text
