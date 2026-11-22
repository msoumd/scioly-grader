/**
 * Decide when the camera view is good enough to take the picture by itself: all four
 * corner markers seen in every frame for ~0.5 s, none moving more than a few pixels, the
 * page big enough in the frame, and enough light. Pure logic, so it is unit-tested.
 */

export interface Point {
  x: number;
  y: number;
}

/** Marker id (0 top-left, 1 top-right, 2 bottom-right, 3 bottom-left) -> centre. */
export type MarkerMap = ReadonlyMap<number, Point>;

export interface Frame {
  t: number; // ms
  markers: MarkerMap;
  width: number; // of the analysed (downscaled) frame
  height: number;
  brightness: number; // mean luma 0-255
}

export type Guidance =
  "too_dark" | "no_sheet" | "show_corners" | "move_closer" | "hold_still" | "ready";

export const GUIDANCE_TEXT: Record<Guidance, string> = {
  too_dark: "Too dark — find more light",
  no_sheet: "Point the camera at the answer sheet",
  show_corners: "Fit all four black corner squares in view",
  move_closer: "Move closer",
  hold_still: "Hold still…",
  ready: "Capturing…",
};

export interface SteadyOptions {
  windowMs: number; // how long it must stay steady
  tolerance: number; // max movement, as a fraction of the frame's long side
  minFrames: number; // at least this many frames in the window
  minArea: number; // page quad area as a fraction of the frame
  minBrightness: number;
}

export const DEFAULTS: SteadyOptions = {
  windowMs: 500,
  tolerance: 0.006, // ~6 px at 960 px
  minFrames: 3,
  minArea: 0.2,
  minBrightness: 45,
};

const IDS = [0, 1, 2, 3] as const;

/** Area of the quad through the four marker centres (shoelace), or 0 if any is missing. */
export function quadArea(m: MarkerMap): number {
  const pts = IDS.map((id) => m.get(id));
  if (pts.some((p) => !p)) return 0;
  let a = 0;
  for (let i = 0; i < 4; i++) {
    const p = pts[i]!;
    const q = pts[(i + 1) % 4]!;
    a += p.x * q.y - q.x * p.y;
  }
  return Math.abs(a) / 2;
}

export class SteadinessTracker {
  private frames: Frame[] = [];
  private readonly opts: SteadyOptions;

  constructor(opts: Partial<SteadyOptions> = {}) {
    this.opts = { ...DEFAULTS, ...opts };
  }

  reset(): void {
    this.frames = [];
  }

  /** Add a frame and say what the grader should do next. */
  push(frame: Frame): Guidance {
    const { windowMs, tolerance, minFrames, minArea, minBrightness } = this.opts;
    const complete = frame.markers.size >= 4 && IDS.every((id) => frame.markers.has(id));
    if (!complete) {
      this.frames = [];
      if (frame.brightness < minBrightness) return "too_dark";
      return frame.markers.size === 0 ? "no_sheet" : "show_corners";
    }
    if (quadArea(frame.markers) < minArea * frame.width * frame.height) {
      this.frames = [];
      return "move_closer";
    }

    this.frames.push(frame);
    // Keep only what the window needs (plus the frame that starts it).
    while (this.frames.length > 1 && frame.t - this.frames[1]!.t >= windowMs) {
      this.frames.shift();
    }
    const first = this.frames[0]!;
    if (frame.t - first.t < windowMs || this.frames.length < minFrames) return "hold_still";

    const limit = tolerance * Math.max(frame.width, frame.height);
    for (const id of IDS) {
      const ref = first.markers.get(id)!;
      for (const f of this.frames) {
        const p = f.markers.get(id)!;
        if (Math.hypot(p.x - ref.x, p.y - ref.y) > limit) {
          this.frames = this.frames.slice(this.frames.indexOf(f)); // restart from movement
          return "hold_still";
        }
      }
    }
    return frame.brightness < minBrightness ? "too_dark" : "ready";
  }
}
