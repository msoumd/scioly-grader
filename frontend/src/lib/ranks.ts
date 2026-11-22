/** Rank labels: tied teams show "T1" (both first), others just the number. */
export function rankLabels(ranks: readonly (number | null | undefined)[]): string[] {
  const counts = new Map<number, number>();
  for (const r of ranks) if (r != null) counts.set(r, (counts.get(r) ?? 0) + 1);
  return ranks.map((r) => (r == null ? "—" : (counts.get(r) ?? 0) > 1 ? `T${r}` : String(r)));
}
