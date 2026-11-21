# Phase 10 — Tournament readiness

**Starter-prompt step:** — (after the 7 build steps)
**Branch:** `phase-10-readiness` (mostly docs, fixes found in rehearsal)
**Depends on:** phase 9 live

## Goal

Prove the whole system with real people, real phones and real paper before tournament day, fix what breaks, and give supervisors and graders simple instructions.

## Tasks

1. **All events set up** — every supervisor fills the template; import each one (dry run first) and fix reported problems with them. Print each event's bubble sheet and get it into the answer packets. Import the final Teams CSV.
2. **Dress rehearsal** — 3–5 volunteers with their own iPhones, at least two events, ~30 hand-filled sheets each with deliberately messy marks (light pencil, erasures, double marks, missing team digits), scanned in a room similar to the venue (lighting, tables). Enter free-response totals. Compare app results with a hand-graded key for every sheet.
3. **Measure** — scans per minute per grader, flag rate, time to clear flags, any wrong-but-unflagged results (target: none). Feed real photos back into the phase 4 regression set.
4. **Fix list** — anything found becomes small PRs following the normal rules; re-run the rehearsal subset after fixes.
5. **Docs**
   - `docs/guides/supervisor.md`: fill the template, print at 100%, what the import errors mean, how to read results and export CSV.
   - `docs/guides/grader.md` (one page, phone screenshots): log in, pick event, scan, fix flags, enter free response.
   - `docs/runbook.md` for tournament day: URLs, PINs location (not in the repo), who to call, what to do if Wi-Fi drops (upload queue, hotspot), if the server is down (paper fallback: grade by hand, scan later), how to restore from backup, how to rotate the PIN.
6. **Tournament-day settings** — set new `TOURNAMENT_PIN` and `ADMIN_PIN`, switch hosting to always-on, check Supabase storage headroom, freeze deploys (no merges to `main` on the day).
7. **After the tournament** — export all CSVs, take a final backup, write a short retrospective in `docs/retro.md`, downgrade paid plans.

## By the end of this phase

- [ ] Every event imported and its sheet printed
- [ ] Rehearsal completed with zero wrong-but-unflagged results, or every one fixed and re-tested
- [ ] Supervisor guide, grader guide and runbook written
- [ ] Tournament-day checklist completed (PINs rotated, always-on, deploy freeze)
- [ ] Yuvan signs off that the app is ready to use

## Review checkpoint for Yuvan

- Run the rehearsal, read the comparison against hand grading, and decide go / no-go for tournament day.
