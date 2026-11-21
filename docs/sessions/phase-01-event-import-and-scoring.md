# Phase 1 — Event import and scoring

**Starter-prompt step:** 1 (spreadsheet import and validation, scoring function with unit tests)
**Branch:** `phase-01-import-scoring`
**Depends on:** phase 0 merged

## Goal

A supervisor's filled-in spreadsheet becomes a validated event in the database, with a clear import report. The scoring function that turns marked bubbles into points is complete and thoroughly tested. No UI, no images yet.

## Why this comes first

Everything downstream (sheet generator, detection, results) reads the imported event. Scoring is the one piece where a bug silently changes a team's rank, so it is pinned down with tests before anything depends on it.

## Scope

### In
- Reading the `.xlsx` template (`Event` tab as setting/value rows, `Questions` tab as a table).
- Teams CSV import (`team_number,team_name`).
- Import report: rows read, problems with row numbers, per-question summary.
- Scoring function for `exact` and `partial`.
- A small command-line tool so this can be used and checked before the API exists.

### Out
- HTTP routes (phase 5), the sheet PDF (phase 2), anything with images.

## Tasks

1. **Spreadsheet reader** — `app/services/event_import.py`
   - Open with `openpyxl` (`data_only=True` so formula cells read as values; ignore the `(auto)` and `check` rows).
   - `Event` tab: read column A as keys, column B as values; required keys: `event_id, event_name, tournament, date, sheet_version, team_number_digits, total_points, free_response_max`. Unknown keys are reported as warnings, not errors.
   - `Questions` tab: header row must contain `q, points, options, correct, scoring`; `penalty_per_wrong` and `notes` optional. Skip fully blank rows. Blank `scoring` → `exact`; blank penalty → 0.
   - Ignore other tabs (e.g. `Instructions`, `Unassigned 55-66`) but list them in the report as "not imported".
   - Build `EventSetup` (from phase 0). Convert every Pydantic error into a plain message with the tab and spreadsheet row number, e.g. `Questions row 12 (q 11): correct answer F is beyond the 5 options (A-E)`.
   - Collect **all** problems in one pass, not just the first.
2. **Import report** — a `ImportReport` dataclass/model: `ok`, `event` summary, `question_count`, `mcq_points_total`, counts by scoring mode, counts of single vs multi-select, list of `errors`, list of `warnings`, tabs ignored. Has a `to_text()` for the CLI.
3. **Save to database** — `save_event(session, setup, source_filename)`:
   - New `event_id` → insert event + questions.
   - Existing `event_id` with **no scans yet** → replace questions (re-import allowed while setting up).
   - Existing `event_id` **with scans** → refuse unless `sheet_version` is higher; never silently change the key under existing scores. (Re-scoring existing scans after a key change is a phase 5 feature; note it.)
   - All in one transaction.
4. **Teams CSV** — `app/services/teams_import.py`: UTF-8 with or without BOM, header required, trims whitespace, rejects duplicate team numbers and non-integer numbers with line numbers; upsert by `team_number`. Validates number fits in the largest `team_number_digits` of any event (warning only).
5. **Scoring** — `app/services/scoring.py`
   - `score_question(marked: set[str], q: QuestionSetup) -> Decimal`
     - `exact`: `points` if `marked == correct` else 0.
     - `partial`: `points × (correct picks / len(correct)) − penalty_per_wrong × wrong picks`, floored at 0, capped at `points`.
   - `score_sheet(marks: dict[int, set[str]], setup) -> SheetScore` with per-question points and total. Unanswered question = empty set.
   - Use `Decimal` throughout and round the total to 2 decimals (half-up), so totals match a hand calculation.
6. **CLI** — `uv run python -m app.cli import-event path.xlsx [--save]` prints the report; `import-teams path.csv`; `score-demo event_id "1=A,2=B,C"` for quick manual checks.
7. **A&P verification** — import `event_setups/PUSO_2026_AP_event_setup.xlsx`. Expect 54 questions, 60 MCQ points. With `total_points=200` it needs `free_response_max=140`; check the sheet and report what it holds.
8. Record in `docs/DECISIONS.md`: re-import rules, rounding rule, how partial credit treats over-marking.

## Tests (must all exist and pass)

- **Scoring (table-driven, aim for 30+ cases):** single correct, single wrong, blank, multi-select exact match, multi-select missing one, multi-select with an extra, all bubbles marked, partial with 0 penalty, partial with penalty floored at 0, partial never above `points`, fractional points (0.5), Decimal rounding.
- **Property test** with `hypothesis` (add as dev dependency): for any marks, score is between 0 and `points`; `exact` is only ever 0 or `points`; marking exactly the correct set always gives `points`.
- **Import:** the real A&P file imports with 0 errors; a set of small broken fixture files under `tests/fixtures/event_setup/` each produce the expected message (missing tab, missing column, letter beyond options, options = 10, duplicate q, totals mismatch, non-numeric points, blank required setting).
- **Save:** insert, re-import before scans replaces questions, re-import with scans and same version is refused (SQLite + Postgres).
- **Teams CSV:** BOM, duplicates, bad numbers, upsert.

## CI changes

- Add `hypothesis` to dev deps. No workflow changes expected.

## By the end of this phase

- [ ] `import-event` on the A&P file prints a clean report: 54 questions, 60 MCQ points, total check passes (or a clear message if the 200/210 question is unresolved)
- [ ] Every broken fixture file gives a specific, row-numbered message, and all problems are listed at once
- [ ] Events, questions and teams can be saved and re-imported following the rules above
- [ ] Scoring function covers `exact` and `partial` with table tests and property tests
- [ ] CI green on SQLite and Postgres
- [ ] Summary posted for Yuvan with the A&P import report pasted in

## Review checkpoint for Yuvan

- Read the A&P import report and spot-check 5–10 answers against the key.
- Confirm the partial-credit formula on two worked examples included in the summary.
- Answer: 200 vs 210 total; what rows 55–66 are.

## Risks

- Formula cells in the template read as `None` if the file was saved by a tool that doesn't cache values. The reader must not rely on formula cells; it recomputes the total itself.
- Supervisors may type `A,C` as `AC` or `A C`; the phase 0 schema already normalises these, keep that covered by tests.
