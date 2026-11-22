/** Plain-language names for the reader's flags (backend detection + counting rules). */

const QUESTION: Record<string, string> = {
  ambiguous: "faint or partial mark",
  multiple_marks: "two marks (one may be erased)",
  low_contrast: "hard to see",
  alignment_uncertain: "row may be misaligned",
};

const SCAN: Record<string, string> = {
  team_digit_missing: "team number not filled in",
  team_digit_unclear: "team number unclear",
  team_digit_ambiguous: "team number has two marks",
  team_alignment_uncertain: "team number hard to read",
  team_low_contrast: "team number hard to see",
  team_unknown: "team not on the list",
  duplicate_team: "team already has a counted sheet",
  retake: "photo needs retaking",
  page_not_found: "page not found in photo",
  page_warp_uncertain: "page shape unclear",
  event_mismatch: "sheet is for another event",
  reopened: "re-opened by a supervisor",
};

export function questionFlagText(flag: string): string {
  return QUESTION[flag] ?? flag.replaceAll("_", " ");
}

/** Short chips for the review queue, e.g. ["2 unclear answers", "team number"]. */
export function reasonChips(flags: readonly string[]): string[] {
  const chips: string[] = [];
  const questions = new Set(flags.filter((f) => /^q\d+:/.test(f)).map((f) => f.split(":")[0]));
  if (questions.size)
    chips.push(questions.size === 1 ? "1 unclear answer" : `${questions.size} unclear answers`);
  if (flags.some((f) => f.startsWith("team_") && f !== "team_unknown")) chips.push("team number");
  if (flags.includes("team_unknown")) chips.push("unknown team");
  if (flags.includes("duplicate_team")) chips.push("duplicate");
  if (flags.includes("retake") || flags.includes("page_not_found")) chips.push("retake");
  if (flags.includes("event_mismatch")) chips.push("other event");
  if (flags.includes("reopened")) chips.push("re-opened");
  const known = (f: string) => /^q\d+:/.test(f) || f.startsWith("team_") || f in SCAN;
  for (const f of flags) if (!known(f)) chips.push(f.replaceAll("_", " "));
  return chips;
}

/** Sentences for the scan-level problems (not per question). */
export function scanFlagTexts(flags: readonly string[]): string[] {
  return flags.filter((f) => !/^q\d+:/.test(f)).map((f) => SCAN[f] ?? f.replaceAll("_", " "));
}
