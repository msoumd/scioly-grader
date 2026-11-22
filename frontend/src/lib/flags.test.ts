import { describe, expect, it } from "vitest";
import { questionFlagText, reasonChips, scanFlagTexts } from "./flags";

describe("flag wording", () => {
  it("summarises a scan's flags as short chips", () => {
    expect(
      reasonChips(["q3:ambiguous", "q3:low_contrast", "q9:multiple_marks", "team_digit_missing"]),
    ).toEqual(["2 unclear answers", "team number"]);
    expect(reasonChips(["q1:ambiguous"])).toEqual(["1 unclear answer"]);
    expect(reasonChips(["duplicate_team", "team_unknown", "retake", "page_not_found"])).toEqual([
      "unknown team",
      "duplicate",
      "retake",
    ]);
    expect(reasonChips(["something_new"])).toEqual(["something new"]);
  });

  it("explains each flag in plain words", () => {
    expect(questionFlagText("multiple_marks")).toMatch(/two marks/);
    expect(scanFlagTexts(["q1:ambiguous", "team_unknown", "duplicate_team"])).toEqual([
      "team not on the list",
      "team already has a counted sheet",
    ]);
  });
});
