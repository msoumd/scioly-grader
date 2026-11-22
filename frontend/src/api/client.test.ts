import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, errorMessage, request, toApiError } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("API errors", () => {
  it("reads the backend's {detail, code}", async () => {
    const res = new Response(JSON.stringify({ detail: "Wrong PIN", code: "wrong_pin" }), {
      status: 401,
    });
    const err = await toApiError(res);
    expect([err.status, err.code, err.message]).toEqual([401, "wrong_pin", "Wrong PIN"]);
    expect(errorMessage(err)).toMatch(/Wrong PIN/);
  });

  it("copes with a non-JSON error page", async () => {
    const err = await toApiError(new Response("<html>Bad gateway</html>", { status: 502 }));
    expect(err.code).toBe("http_502");
    expect(err.retryable).toBe(true);
    expect(errorMessage(err)).toMatch(/server had a problem/);
  });

  it("maps codes to plain sentences", () => {
    expect(errorMessage(new ApiError(429, "too_many_attempts", "x"))).toMatch(
      /wait a few minutes/i,
    );
    expect(errorMessage(new ApiError(0, "network", "x"))).toMatch(/No connection/);
    expect(errorMessage(new ApiError(413, "too_large", "x"))).toMatch(/too big/);
    expect(errorMessage(new ApiError(422, "something_new", "Team 99 is not on the list"))).toBe(
      "Team 99 is not on the list",
    );
    expect(errorMessage(new Error("boom"))).toBe("Something went wrong.");
  });

  it("says which failures are worth retrying", () => {
    const r = (s: number) => new ApiError(s, "x", "x").retryable;
    expect([0, 408, 429, 500, 503].map(r)).toEqual([true, true, true, true, true]);
    expect([400, 401, 403, 404, 413, 415, 422].map(r)).toEqual(Array(7).fill(false));
  });

  it("turns a failed fetch into a network ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(request("/api/me")).rejects.toMatchObject({ status: 0, code: "network" });
  });

  it("returns JSON on success and nothing on 204", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response(JSON.stringify({ id: 1 }), { status: 200 }))
        .mockResolvedValueOnce(new Response(null, { status: 204 })),
    );
    expect(await request("/api/me")).toEqual({ id: 1 });
    expect(await request("/api/logout", { method: "POST" })).toBeUndefined();
  });
});
