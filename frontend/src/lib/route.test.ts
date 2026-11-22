import { describe, expect, it } from "vitest";
import { href, parseRoute } from "./route";

describe("routes", () => {
  it("parses and builds addresses", () => {
    expect(parseRoute("")).toEqual({ tab: "scan" });
    expect(parseRoute("#/review")).toEqual({ tab: "review" });
    expect(parseRoute("#/review/42")).toEqual({ tab: "review", scanId: 42 });
    expect(parseRoute("#/review/abc")).toEqual({ tab: "review" });
    expect(parseRoute("#/duplicates")).toEqual({ tab: "duplicates" });
    expect(parseRoute("#/scores")).toEqual({ tab: "scores" });
    expect(parseRoute("#/scores/0")).toEqual({ tab: "scores", team: 0 });
    expect(parseRoute("#/scores/x")).toEqual({ tab: "scores" });
    expect(parseRoute("#/results")).toEqual({ tab: "results" });
    expect(parseRoute("#/setup")).toEqual({ tab: "setup" });
    expect(parseRoute("#/nonsense")).toEqual({ tab: "scan" });
    expect(href({ tab: "review", scanId: 7 })).toBe("#/review/7");
    expect(href({ tab: "scores", team: 12 })).toBe("#/scores/12");
  });
});
