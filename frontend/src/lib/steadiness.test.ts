import { describe, expect, it } from "vitest";
import { SteadinessTracker, quadArea, type Frame, type Point } from "./steadiness";

const W = 960;
const H = 540;
const CORNERS: Point[] = [
  { x: 200, y: 50 },
  { x: 760, y: 50 },
  { x: 760, y: 490 },
  { x: 200, y: 490 },
];

function frame(t: number, opts: { shift?: number; ids?: number[]; brightness?: number; scale?: number } = {}): Frame {
  const { shift = 0, ids = [0, 1, 2, 3], brightness = 150, scale = 1 } = opts;
  const markers = new Map<number, Point>();
  for (const id of ids) {
    const c = CORNERS[id]!;
    markers.set(id, { x: W / 2 + (c.x - W / 2) * scale + shift, y: H / 2 + (c.y - H / 2) * scale });
  }
  return { t, markers, width: W, height: H, brightness };
}

/** Feed frames every `step` ms and return the guidance after each. */
function run(tracker: SteadinessTracker, frames: Frame[]): string[] {
  return frames.map((f) => tracker.push(f));
}

describe("steadiness", () => {
  it("is ready only after ~0.5 s of all four markers holding still", () => {
    const t = new SteadinessTracker();
    const out = run(t, [0, 125, 250, 375, 500].map((ms) => frame(ms)));
    expect(out).toEqual(["hold_still", "hold_still", "hold_still", "hold_still", "ready"]);
  });

  it("small hand tremor (a couple of pixels) still counts as steady", () => {
    const t = new SteadinessTracker();
    const out = run(t, [0, 125, 250, 375, 500].map((ms, i) => frame(ms, { shift: i % 2 ? 2 : -2 })));
    expect(out.at(-1)).toBe("ready");
  });

  it("movement restarts the wait", () => {
    const t = new SteadinessTracker();
    run(t, [0, 125, 250, 375].map((ms) => frame(ms)));
    expect(t.push(frame(500, { shift: 30 }))).toBe("hold_still"); // moved
    expect(t.push(frame(750, { shift: 30 }))).toBe("hold_still");
    expect(t.push(frame(1000, { shift: 30 }))).toBe("ready"); // 0.5 s after the move
  });

  it("losing a marker resets and asks for all four corners", () => {
    const t = new SteadinessTracker();
    run(t, [0, 125, 250, 375].map((ms) => frame(ms)));
    expect(t.push(frame(500, { ids: [0, 1, 2] }))).toBe("show_corners");
    expect(t.push(frame(625))).toBe("hold_still");
  });

  it("explains what's wrong", () => {
    const t = new SteadinessTracker();
    expect(t.push(frame(0, { ids: [] }))).toBe("no_sheet");
    expect(t.push(frame(0, { ids: [], brightness: 20 }))).toBe("too_dark");
    expect(t.push(frame(0, { ids: [3] }))).toBe("show_corners");
    expect(t.push(frame(0, { scale: 0.3 }))).toBe("move_closer");
  });

  it("needs a few frames, not just elapsed time", () => {
    const t = new SteadinessTracker();
    expect(run(t, [frame(0), frame(600)])).toEqual(["hold_still", "hold_still"]);
    expect(t.push(frame(700))).toBe("ready");
  });

  it("quad area", () => {
    expect(quadArea(frame(0).markers)).toBe(560 * 440);
    expect(quadArea(frame(0, { ids: [0, 1] }).markers)).toBe(0);
  });
});
