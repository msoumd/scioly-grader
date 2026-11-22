# Phase 8 — Free response, results and export

**Starter-prompt step:** 6 (free-response entry, results table, CSV export)
**Branch:** `phase-08-results`
**Depends on:** phase 7 merged
**Status:** built on branch `phase-08-results`, awaiting review. The hands-on mini event is deferred to the end-of-build testing pass.

## Goal

Graders enter one free-response total per team, at any time before or after the scan. Supervisors see a per-event results table with MCQ, free response, total and rank, see what's missing, edit with an audit trail, and export CSV.

## Scope

### In
- Free-response entry screen, results table, missing-items summary, edits with audit, CSV export, supervisor event setup screens (import event, import teams, download sheet PDF).

### Out
- Overall tournament standings, tiebreakers, multi-tournament (out of scope for v1).

## Tasks

1. **Scores tab — free-response entry**
   - Team list for the event (number + name), each row showing current free-response total or "—", and whether a scan exists.
   - Tap a team → numeric keypad entry; shows `free_response_max`; rejects < 0, > max, and non-0.5 steps with an inline message; Save.
   - Fast mode: after saving, jump to the next team without a score.
   - Editing an existing value asks for confirmation and writes an audit entry (old → new).
   - Search by team number.
2. **Results tab**
   - Table: rank, team number, team name, MCQ, free response, total; "—" where missing; totals only shown when both parts exist.
   - Missing-items banner: "12 teams have no scan, 5 have no free-response score", each tappable to filter.
   - Ties share a rank.
   - Row detail: who entered each part and when; links to the scan and its history.
   - Download CSV (same columns plus grader names and timestamps; UTF-8 with BOM so Excel opens it cleanly).
3. **Admin: event setup screens**
   - Upload event spreadsheet → shows the phase 1 import report (dry run first, then "Import").
   - Upload Teams CSV → report.
   - Download the bubble sheet PDF for an event.
   - Re-score event after key change (phase 5 route) with a confirmation showing how many scans change.
4. **Print-friendly results** — a print stylesheet so supervisors can print the results table.

## Tests

- **Backend:** results with ties, missing parts, edits; CSV content matches the table exactly (golden file).
- **Unit (frontend):** score input validation, rank display with ties.
- **E2E (Playwright):**
  - Enter free response before scan → total appears after scan confirmed (and the reverse order).
  - Out-of-range and 0.25 values rejected.
  - Edit a value → audit history shows it.
  - Results table ranks match a hand-calculated fixture; CSV download matches.
  - Admin imports the A&P spreadsheet and Teams CSV from the UI, sees the report, downloads the sheet PDF.
  - Missing-items counts update live.

## CI changes

- Extend e2e. No new jobs.

## By the end of this phase

- [x] Every feature in the starter prompt's "Human free-response entry" and "Results" sections works on a phone
- [x] Supervisors can set up an event from the app without the CLI
- [x] CSV export matches the on-screen table
- [x] All edits are audited
- [x] E2E covers entry, results, CSV, admin import; CI green
- [x] **Feature-complete v1** — summary lists anything from the spec not done

## Review checkpoint for Yuvan

- Run a mini event end-to-end on your phone: import A&P, import a 10-team list, scan 10 sheets, enter 10 free-response totals, check the results and CSV in Excel.

## Risks

- Graders entering the free-response total for the wrong team: show the team name large on the entry screen and require confirmation when overwriting.
