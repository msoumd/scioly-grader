/**
 * What a grader changes on the review screen, before it is saved: marks per question and
 * the team number. A pure reducer so the rules are unit-tested.
 */

export const LETTERS = "ABCDEFGHI";

export interface ReviewState {
  original: Record<number, string[]>; // marks as the server has them now
  marks: Record<number, string[]>; // marks as the grader has set them
  originalTeam: number | null;
  teamText: string; // what the grader typed (digits only)
}

export type ReviewAction =
  | { type: "toggle"; q: number; letter: string; options: number }
  | { type: "clear"; q: number }
  | { type: "teamDigit"; digit: string; maxDigits: number }
  | { type: "teamBackspace" }
  | { type: "teamSet"; text: string; maxDigits: number }
  | { type: "reset" };

export function initReview(
  marks: Record<number, readonly string[]>,
  team: number | null,
): ReviewState {
  const original = Object.fromEntries(
    Object.entries(marks).map(([q, v]) => [Number(q), [...v].sort()]),
  );
  return {
    original,
    marks: structuredClone(original),
    originalTeam: team,
    teamText: team == null ? "" : String(team),
  };
}

export function reviewReducer(s: ReviewState, a: ReviewAction): ReviewState {
  switch (a.type) {
    case "toggle": {
      if (!LETTERS.slice(0, a.options).includes(a.letter)) return s;
      const cur = new Set(s.marks[a.q] ?? []);
      if (cur.has(a.letter)) cur.delete(a.letter);
      else cur.add(a.letter);
      return { ...s, marks: { ...s.marks, [a.q]: [...cur].sort() } };
    }
    case "clear":
      return { ...s, marks: { ...s.marks, [a.q]: [] } };
    case "teamDigit":
      if (!/^\d$/.test(a.digit) || s.teamText.length >= a.maxDigits) return s;
      return { ...s, teamText: s.teamText + a.digit };
    case "teamBackspace":
      return { ...s, teamText: s.teamText.slice(0, -1) };
    case "teamSet":
      return { ...s, teamText: a.text.replace(/\D/g, "").slice(0, a.maxDigits) };
    case "reset":
      return {
        ...s,
        marks: structuredClone(s.original),
        teamText: s.originalTeam == null ? "" : String(s.originalTeam),
      };
  }
}

const same = (a: readonly string[] = [], b: readonly string[] = []) =>
  a.length === b.length && a.every((x, i) => x === b[i]);

/** Questions whose marks the grader changed, for PATCH /api/scans/{id}. */
export function changedMarks(s: ReviewState): Record<number, string[]> {
  const out: Record<number, string[]> = {};
  for (const [q, v] of Object.entries(s.marks)) {
    if (!same(v, s.original[Number(q)])) out[Number(q)] = v;
  }
  return out;
}

/** The team number typed, or null if empty. Leading zeros don't matter ("07" = 7). */
export function typedTeam(s: ReviewState): number | null {
  return s.teamText === "" ? null : Number(s.teamText);
}

export function teamChanged(s: ReviewState): boolean {
  return typedTeam(s) !== s.originalTeam;
}

export type TeamCheck =
  | { state: "missing" }
  | { state: "unknown"; number: number }
  | { state: "ok"; number: number; name: string };

/** Is the typed team number on the teams list? (An empty list means "no list": any is ok.) */
export function checkTeam(s: ReviewState, teams: ReadonlyMap<number, string>): TeamCheck {
  const n = typedTeam(s);
  if (n === null) return { state: "missing" };
  const name = teams.get(n);
  if (name !== undefined) return { state: "ok", number: n, name };
  return teams.size === 0 ? { state: "ok", number: n, name: "" } : { state: "unknown", number: n };
}
