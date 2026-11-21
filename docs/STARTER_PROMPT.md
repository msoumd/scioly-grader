# Starter prompt for the AI coding tool

Paste everything below the line into your coding tool. Attach `PUSO_2026_AP_event_setup.xlsx` and one of your real answer-sheet PDFs (the A&P one) so it can see the layout you use today.

---

Build a web app that scores Science Olympiad multiple-choice bubble sheets from phone photos and combines them with a human-entered free-response total.

## Context
- One tournament (our own), ~20 events, up to ~63 teams per event. Several graders use their own iPhones (Safari). Wi-Fi is available. I am not a coder: explain decisions briefly, build in small testable steps, and stop for my review at each build-order step.
- Event supervisors set up each event by filling in the attached spreadsheet template (`Event`, `Questions` tabs). The app imports it. Do not require supervisors to write JSON.

## Stack
- Backend: Python, FastAPI, OpenCV (no AI/ML), SQLite for dev and Postgres in production.
- Frontend: mobile-first web app (installable PWA), served over HTTPS. Simple grader login or shared tournament PIN, so each scan and score records who entered it.

## Event setup (import from the spreadsheet)
- `Event` tab: event_id, event_name, tournament, date, sheet_version, team_number_digits, total_points, free_response_max. Validate that total_points = free_response_max + sum of question points, and show an error if not.
- `Questions` tab: one row per bubble question: q, points, options (number of bubbles, 2 to 9), correct (comma-separated letters, may be multi-select), scoring (`exact` or `partial`), penalty_per_wrong.
- Scoring per question:
  - `exact`: full points only if the marked set equals the correct set, else 0.
  - `partial`: points x (correct picks / number correct) - penalty_per_wrong x wrong picks, floored at 0, never below 0.
  - Unit-test this function thoroughly, including multi-select, blank, all-marked and floor-at-zero cases.
- Also import a one-time Teams CSV (team_number, team_name) for the tournament so results show names.
- Show a clear import report: rows read, problems found, per-question summary. Reject bad files with specific messages (for example, a correct letter beyond the options count).

## Scantron sheet generator
- Generate a printable PDF page for an event from its imported setup. Letter size, black-and-white friendly.
- Layout modeled on the attached A&P sheet: bubbles in columns, row length per question driven by `options`, a bubbled team-number grid (team_number_digits columns, digits 0-9), a Team name box (handwritten, not scanned).
- Four corner alignment markers (ArUco or solid squares) plus a QR code encoding {event_id, sheet_version}.
- Layout is deterministic from the setup so every bubble position is known exactly. Capacity: at least 100 questions per page.
- Supervisors can drop this page into their answer-sheet packet. Everything not on this page is graded by humans.

## Capture
- Live camera view with an overlay that detects the four markers and auto-captures when all are visible and the phone is steady (client-side guidance only). Also support plain photo upload and multi-page PDF upload from a scanner or copier.

## Detection (server-side)
- Detect markers, warp the page flat, read the QR to select the event setup, read team number digits, measure fill ratio per bubble with adaptive thresholding (pencil, shadows, erasures).
- Flags: blank question, ambiguous/low-confidence bubble, unreadable or invalid team number, team number already scanned for this event.
- Review screen: flagged questions and the team number are shown beside the cropped bubble images, so a human can correct them before saving. Always keep the original image.

## Human free-response entry
- No per-question scoring. For each event and team, a grader enters ONE number: the total free-response score (free response, identification and live-activity combined).
- The entry screen shows the event's free_response_max and rejects values above it or below 0 (0.5 steps allowed).
- A team's results row is: event, team number, mcq_score (from the scan), free_response_total (human), total = sum, who entered each, timestamps.
- Allow a grader to enter the free-response total before or after the scan; the total only shows once both exist. Show missing items per event ("12 teams have no scan, 5 have no free-response score").

## Results
- Per-event table: team, mcq, free response, total, rank. Overall standings are not required for v1.
- CSV export per event. Editing an existing score keeps an audit log (who, when, old and new value).
- Duplicate scans of the same team in the same event: show both and require the grader to pick which one counts.

## Data stored
- events, questions, teams, scans (image, detected marks per question, corrections, mcq_score, grader, timestamp), free_response_scores (event, team, value, grader, timestamp), audit_log.

## Testing (do this first)
- A script that generates fake filled sheets from an event setup with known answers, plus augmentations (rotation, perspective, blur, shadows, light pencil, erasures, double marks, partial team numbers), and reports detection accuracy per condition. Do not build the UI until accuracy is measured and I have approved it.
- Use the attached A&P setup (54 questions, mix of single-answer and multi-select) as the first real test event.

## Build order (stop for my review after each)
1. Spreadsheet import and validation, scoring function with unit tests
2. Scantron PDF generator and fake-sheet test harness
3. Detection and scoring, with accuracy report
4. API and database
5. Capture and review UI
6. Free-response entry, results table, CSV export
7. Deploy (small hosted service with HTTPS)

## Out of scope for v1
- Reading student names, tiebreaker handling, overall tournament standings, multi-tournament support, scanning anything other than the bubble page.
