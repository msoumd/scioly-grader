import { describe, expect, it } from "vitest";
import {
  changedMarks,
  checkTeam,
  initReview,
  reviewReducer as r,
  teamChanged,
  typedTeam,
} from "./review";

const start = () => initReview({ 1: ["B"], 2: ["A", "C"], 3: [] }, null);

describe("review corrections", () => {
  it("toggles letters on and off, kept in order", () => {
    let s = start();
    s = r(s, { type: "toggle", q: 1, letter: "D", options: 4 });
    expect(s.marks[1]).toEqual(["B", "D"]);
    s = r(s, { type: "toggle", q: 1, letter: "B", options: 4 });
    expect(s.marks[1]).toEqual(["D"]);
    expect(changedMarks(s)).toEqual({ 1: ["D"] });
  });

  it("ignores letters beyond the question's options", () => {
    const s = start();
    expect(r(s, { type: "toggle", q: 1, letter: "E", options: 4 })).toBe(s);
  });

  it("clearing makes a question blank; toggling back to the original is no change", () => {
    let s = r(start(), { type: "clear", q: 2 });
    expect(changedMarks(s)).toEqual({ 2: [] });
    s = r(s, { type: "toggle", q: 2, letter: "C", options: 5 });
    s = r(s, { type: "toggle", q: 2, letter: "A", options: 5 });
    expect(changedMarks(s)).toEqual({});
  });

  it("does not touch the original", () => {
    const s0 = start();
    r(s0, { type: "toggle", q: 1, letter: "A", options: 4 });
    expect(s0.marks[1]).toEqual(["B"]);
  });

  it("reset undoes everything", () => {
    let s = r(start(), { type: "toggle", q: 3, letter: "A", options: 4 });
    s = r(s, { type: "teamSet", text: "12", maxDigits: 2 });
    s = r(s, { type: "reset" });
    expect(changedMarks(s)).toEqual({});
    expect(typedTeam(s)).toBeNull();
  });
});

describe("team number", () => {
  const teams = new Map([
    [7, "Alpha HS"],
    [12, "Beta MS"],
  ]);

  it("number pad: digits only, up to the sheet's digit count", () => {
    let s = start();
    for (const d of ["1", "x", "2", "3"]) s = r(s, { type: "teamDigit", digit: d, maxDigits: 2 });
    expect(s.teamText).toBe("12");
    s = r(s, { type: "teamBackspace" });
    expect(s.teamText).toBe("1");
    s = r(s, { type: "teamSet", text: "a0 7z9", maxDigits: 2 });
    expect(s.teamText).toBe("07");
    expect(typedTeam(s)).toBe(7);
  });

  it("says whether the team is on the list", () => {
    let s = start();
    expect(checkTeam(s, teams)).toEqual({ state: "missing" });
    s = r(s, { type: "teamSet", text: "12", maxDigits: 2 });
    expect(checkTeam(s, teams)).toEqual({ state: "ok", number: 12, name: "Beta MS" });
    s = r(s, { type: "teamSet", text: "99", maxDigits: 2 });
    expect(checkTeam(s, teams)).toEqual({ state: "unknown", number: 99 });
    expect(checkTeam(s, new Map())).toMatchObject({ state: "ok", number: 99 });
  });

  it("knows when the team was changed", () => {
    const s = initReview({}, 7);
    expect(teamChanged(s)).toBe(false);
    expect(teamChanged(r(s, { type: "teamSet", text: "007", maxDigits: 3 }))).toBe(false);
    expect(teamChanged(r(s, { type: "teamBackspace" }))).toBe(true);
  });
});
