import { describe, expect, it } from "vitest";
import { scoreSheet, type ScoredQuestion } from "./scoring";

const q = (n: number, o: Partial<ScoredQuestion> = {}): ScoredQuestion => ({
  q: n,
  points: "1",
  correct: ["A"],
  scoring: "exact",
  penalty_per_wrong: "0",
  ...o,
});

describe("scoring (same rules as the server)", () => {
  it("exact: full points only for exactly the key", () => {
    const qs = [q(1), q(2, { points: "2", correct: ["B", "D"] })];
    expect(scoreSheet({ 1: ["A"], 2: ["B", "D"] }, qs)).toBe("3.00");
    expect(scoreSheet({ 1: ["A", "B"], 2: ["B"] }, qs)).toBe("0.00");
    expect(scoreSheet({}, qs)).toBe("0.00");
  });

  it("partial: share of correct picks minus penalties, floored and capped", () => {
    const p = q(1, {
      points: "3",
      correct: ["A", "B", "C"],
      scoring: "partial",
      penalty_per_wrong: "0.5",
    });
    expect(scoreSheet({ 1: ["A"] }, [p])).toBe("1.00");
    expect(scoreSheet({ 1: ["A", "B", "D"] }, [p])).toBe("1.50");
    expect(scoreSheet({ 1: ["D", "E"] }, [p])).toBe("0.00");
    expect(scoreSheet({ 1: ["A", "B", "C"] }, [p])).toBe("3.00");
  });

  it("thirds are summed exactly before rounding half-up", () => {
    const third = q(1, { points: "1", correct: ["A", "B", "C"], scoring: "partial" });
    const qs = [third, { ...third, q: 2 }, { ...third, q: 3 }];
    // 1/3 + 1/3 + 1/3 = exactly 1 (floats would give 0.9999...)
    expect(scoreSheet({ 1: ["A"], 2: ["A"], 3: ["A"] }, qs)).toBe("1.00");
    // 2 x 1/3 = 0.666... -> 0.67
    expect(scoreSheet({ 1: ["A"], 2: ["B"] }, qs)).toBe("0.67");
  });

  it("rounds .xx5 up", () => {
    const qs = [q(1, { points: "0.125" }), q(2, { points: "0.0" })];
    expect(scoreSheet({ 1: ["A"] }, qs)).toBe("0.13");
  });

  it("ignores case and spaces in marks", () => {
    expect(scoreSheet({ 1: [" a "] }, [q(1)])).toBe("1.00");
  });
});

describe("agrees with the server", () => {
  it("on 40 random answer sheets scored by backend/app/services/scoring.py", async () => {
    const { default: data } = await import("./__fixtures__/scoring.json");
    for (const c of data.cases) {
      expect(scoreSheet(c.marks as unknown as Record<number, string[]>, data.questions)).toBe(
        c.total,
      );
    }
  });
});
