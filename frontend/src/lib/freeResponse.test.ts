import { describe, expect, it } from "vitest";
import { keypadPress, parseFreeResponse, trim } from "./freeResponse";
import { rankLabels } from "./ranks";

describe("free-response input", () => {
  it("accepts whole and half points up to the maximum", () => {
    expect(parseFreeResponse("42", "140")).toEqual({ ok: true, value: "42" });
    expect(parseFreeResponse(" 42.5 ", "140")).toEqual({ ok: true, value: "42.5" });
    expect(parseFreeResponse("42,5", "140")).toEqual({ ok: true, value: "42.5" });
    expect(parseFreeResponse("140", "140.0")).toEqual({ ok: true, value: "140" });
    expect(parseFreeResponse("0", "140")).toEqual({ ok: true, value: "0" });
  });

  it("rejects blanks, over the max, quarter points, negatives and junk", () => {
    expect(parseFreeResponse("", "140")).toMatchObject({ ok: false });
    expect(parseFreeResponse("140.5", "140")).toEqual({ ok: false, error: "The most is 140." });
    expect(parseFreeResponse("10.25", "140")).toMatchObject({ ok: false, error: /half points/ });
    expect(parseFreeResponse("-3", "140")).toMatchObject({ ok: false });
    expect(parseFreeResponse("ten", "140")).toMatchObject({ ok: false });
  });

  it("keypad builds sensible numbers", () => {
    const type = (keys: string[]) => keys.reduce(keypadPress, "");
    expect(type(["4", "2", ".", "5"])).toBe("42.5");
    expect(type(["4", "2", ".", "5", "5"])).toBe("42.5"); // one decimal place
    expect(type([".", "5"])).toBe("0.5");
    expect(type(["0", "7"])).toBe("7");
    expect(type(["1", ".", "."])).toBe("1.");
    expect(type(["1", "2", "back"])).toBe("1");
  });

  it("trims numbers for display", () => {
    expect([trim("42.50"), trim("40.0"), trim("007"), trim("0")]).toEqual(["42.5", "40", "7", "0"]);
  });
});

describe("rank labels", () => {
  it("marks ties", () => {
    expect(rankLabels([1, 1, 3, 4, 4, null])).toEqual(["T1", "T1", "3", "T4", "T4", "—"]);
  });
});
