/**
 * Find the sheet's four corner markers (ArUco DICT_4X4_50, ids 0-3) in a downscaled video
 * frame, using a small pure-JavaScript ArUco port (full OpenCV.js is too big for phones).
 */
import { AR } from "../vendor/js-aruco2/aruco.js";
import type { Point } from "./steadiness";

export interface FrameImage {
  width: number;
  height: number;
  data: Uint8ClampedArray; // RGBA
}

let detector: InstanceType<typeof AR.Detector> | undefined;

/** Centres of corner markers 0-3 found in the frame (others are ignored). */
export function findCornerMarkers(img: FrameImage): Map<number, Point> {
  detector ??= new AR.Detector({ dictionaryName: "ARUCO_4X4_50", maxHammingDistance: 2 });
  const found = new Map<number, Point>();
  const best = new Map<number, number>();
  for (const m of detector.detect(img)) {
    if (m.id < 0 || m.id > 3) continue;
    const prev = best.get(m.id);
    if (prev !== undefined && prev <= m.hammingDistance) continue;
    best.set(m.id, m.hammingDistance);
    const x = m.corners.reduce((s, c) => s + c.x, 0) / m.corners.length;
    const y = m.corners.reduce((s, c) => s + c.y, 0) / m.corners.length;
    found.set(m.id, { x, y });
  }
  return found;
}

/** Mean brightness (0-255), sampling every 16th pixel. */
export function meanBrightness(img: FrameImage): number {
  const d = img.data;
  let sum = 0;
  let n = 0;
  for (let i = 0; i < d.length; i += 64) {
    sum += 0.299 * d[i]! + 0.587 * d[i + 1]! + 0.114 * d[i + 2]!;
    n++;
  }
  return n ? sum / n : 0;
}
