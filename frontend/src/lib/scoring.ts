/**
 * The backend's scoring rules (backend/app/services/scoring.py), for the live score on
 * the review screen. Exact fractions with BigInt so totals match the server to the cent;
 * the server still re-scores when corrections are saved and its score is the one that
 * counts.
 *
 * - exact: full points only if the marked set equals the key, else 0.
 * - partial: points x (correct picks / correct answers) - penalty x wrong picks,
 *   floored at 0 and capped at points.
 * Total rounded half-up to 2 decimals.
 */

export interface ScoredQuestion {
  q: number;
  points: string; // decimal string from the API
  correct: string[];
  scoring: string; // "exact" | "partial"
  penalty_per_wrong: string;
}

type Frac = { n: bigint; d: bigint };

function frac(decimal: string): Frac {
  const s = decimal.trim();
  const neg = s.startsWith("-");
  const [whole = "0", part = ""] = s.replace(/^[-+]/, "").split(".");
  const d = 10n ** BigInt(part.length);
  const n = BigInt(whole || "0") * d + BigInt(part || "0");
  return { n: neg ? -n : n, d };
}

const add = (a: Frac, b: Frac): Frac => ({ n: a.n * b.d + b.n * a.d, d: a.d * b.d });
const sub = (a: Frac, b: Frac): Frac => add(a, { n: -b.n, d: b.d });
const mulInt = (a: Frac, k: number): Frac => ({ n: a.n * BigInt(k), d: a.d });
const divInt = (a: Frac, k: number): Frac => ({ n: a.n, d: a.d * BigInt(k) });
const cmp = (a: Frac, b: Frac): number => {
  const x = a.n * b.d - b.n * a.d;
  return x < 0n ? -1 : x > 0n ? 1 : 0;
};
const ZERO: Frac = { n: 0n, d: 1n };

function questionPoints(marked: Iterable<string>, q: ScoredQuestion): Frac {
  const picks = new Set([...marked].map((m) => m.trim().toUpperCase()).filter(Boolean));
  const key = new Set(q.correct);
  const points = frac(q.points);
  if (q.scoring !== "partial") {
    const same = picks.size === key.size && [...picks].every((p) => key.has(p));
    return same ? points : ZERO;
  }
  let hits = 0;
  let wrong = 0;
  for (const p of picks) {
    if (key.has(p)) hits++;
    else wrong++;
  }
  const raw = sub(divInt(mulInt(points, hits), key.size), mulInt(frac(q.penalty_per_wrong), wrong));
  if (cmp(raw, ZERO) < 0) return ZERO;
  return cmp(raw, points) > 0 ? points : raw;
}

/** Round half-up to 2 decimals and format like the API ("60.00"). */
function toCents(x: Frac): string {
  // x >= 0 here: every question is floored at 0.
  const cents = (x.n * 200n + x.d) / (2n * x.d); // floor(x*100 + 0.5)
  const s = cents.toString().padStart(3, "0");
  return `${s.slice(0, -2)}.${s.slice(-2)}`;
}

/** Sheet total for these marks (question -> letters); unlisted questions are blank. */
export function scoreSheet(
  marks: Readonly<Record<number, readonly string[]>>,
  questions: readonly ScoredQuestion[],
): string {
  let total = ZERO;
  for (const q of questions) total = add(total, questionPoints(marks[q.q] ?? [], q));
  return toCents(total);
}
