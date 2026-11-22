// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { findCornerMarkers, meanBrightness, type FrameImage } from "./markers";

/** The fixture is a tilted fake phone photo of a real printed sheet layout, made by the
 * backend (scripts/e2e_assets.py --pgm), so this checks the browser detector agrees with
 * the markers the server prints. */
function fixture(): FrameImage {
  const raw = gunzipSync(readFileSync(fileURLToPath(new URL("./__fixtures__/sheet_frame.pgm.gz", import.meta.url))));
  const header = raw.subarray(0, 32).toString("latin1");
  const m = /^P5\s+(\d+)\s+(\d+)\s+255\s/.exec(header);
  if (!m) throw new Error("bad PGM");
  const [width, height] = [Number(m[1]), Number(m[2])];
  const grey = raw.subarray(m[0].length);
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    data[i * 4] = data[i * 4 + 1] = data[i * 4 + 2] = grey[i]!;
    data[i * 4 + 3] = 255;
  }
  return { width, height, data };
}

describe("corner markers", () => {
  it("finds all four printed markers in a tilted photo, in the right corners", () => {
    const img = fixture();
    const m = findCornerMarkers(img);
    expect([...m.keys()].sort()).toEqual([0, 1, 2, 3]);
    const [tl, tr, br, bl] = [0, 1, 2, 3].map((id) => m.get(id)!);
    expect(tl!.x).toBeLessThan(tr!.x);
    expect(bl!.x).toBeLessThan(br!.x);
    expect(tl!.y).toBeLessThan(bl!.y);
    expect(tr!.y).toBeLessThan(br!.y);
  });

  it("finds nothing in a blank frame", () => {
    const blank = { width: 320, height: 240, data: new Uint8ClampedArray(320 * 240 * 4).fill(200) };
    expect(findCornerMarkers(blank).size).toBe(0);
    expect(meanBrightness(blank)).toBeCloseTo(200, 0);
  });
});
