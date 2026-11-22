# Decisions

Short record of choices made while building. Newest first.

## 2026-11-22 — Budget hosting: photos deleted once a sheet is done

Budget is $35/month, so Supabase stays on the **free** plan and Render runs **Starter** ($7) except in tournament week (**Standard**, $25, billed by the second). Load numbers for both are in [`DEPLOY.md`](DEPLOY.md).

**Photos are deleted when a sheet is counted or discarded** (Yuvan's decision). That means the original upload, the straightened page, and the team and question crops (`app/services/photos.py`).
- Marks, score, corrections and history stay, so results, CSV, re-scoring and re-opening still work.
- A PDF's original is deleted only when all its pages are done.
- A failed delete is retried at the next startup sweep.

Storage then only holds sheets waiting for review, far under the free 1 GB.

This replaces phase 7's "original photo always viewable": once a sheet is done, the paper sheet is the record. `DELETE_PHOTOS_WHEN_DONE=false` turns it off.

**Supabase free caveats:**
- It pauses after a week idle; the nightly backup's daily read should prevent that, and DEPLOY.md says to check before the tournament.
- It has no built-in backups; the nightly encrypted backup covers the scores.

## 2026-11-22 — Hosting, deploys, backups and security (phase 9)

**Where it runs.** One Docker container on Render's **Standard** plan (1 CPU, 2 GB), serving the API and the phone app on one HTTPS address. Supabase Pro holds Postgres and the private `scans` bucket. Step-by-step setup and costs are in [`DEPLOY.md`](DEPLOY.md).

**One web process.** The login limiter and the reading queue live in memory, so two processes would double the allowed PIN guesses and could both retry a stuck scan. Reading uses a thread pool inside the one process.

**Safe by default in production** (`ENVIRONMENT=production`). The app refuses to start without:
- a 32+ character session secret;
- a 6+ character tournament PIN, and an 8+ character admin PIN that is different;
- HTTPS-only cookies;
- Postgres, and Supabase storage (local files are lost on redeploy).

Also in production: `/docs` is off, HSTS is sent over HTTPS, and Sentry reports errors if `SENTRY_DSN` is set (no personal data).

**Bugs found while preparing for real traffic:**
- **Upload overload.** 60 uploads at once exhausted the database connection pool and returned errors. Each upload held a connection while the phone was still sending the photo, and did blocking work on the server's main loop. Now the file arrives first, the work runs in a worker thread, and the connection is released before the photo goes to storage. The pool is also larger (10 + 20).
- **PIN guessing.** Behind the hosting proxy, the login limiter trusted the leftmost `X-Forwarded-For` address, which the caller writes, so a guesser could dodge the limit by inventing addresses. Now the address the proxy itself appended is used (`TRUSTED_PROXY_HOPS`). A site-wide limit of 100 wrong PINs per 5 minutes covers anyone who rotates real addresses.
- **Row-level security.** Supabase's REST API could see the migrations table. RLS is now on for every table, and a Postgres test checks it.

**Deploys.** After CI passes on `main`, `deploy.yml` asks Render to deploy that exact commit. `/health` reports the commit, so the workflow waits until it is live, then smoke-tests the site (health, app page, HSTS, login, events). CI also builds the container on every PR and:
- checks it refuses unsafe production settings;
- starts it and runs the smoke test;
- runs a 30-sheet load check;
- checks it runs as a non-root user and its health check passes.

**Backups.** Nightly: `pg_dump` of the app's tables, encrypted with AES-256 and a passphrase, kept 14 days as a workflow artifact, and restored into a scratch Postgres every night to prove it works. Photos are not included: the scores are already in the database, and a paper sheet can be scanned again.

**Load.** On a 1-CPU, 2 GB container, one sheet takes 0.5 s, and 60 uploaded at once all finish within 33 s (about 110 sheets a minute) with memory under 300 MB.

## 2026-11-21 — Free response, results and event setup (phase 8)

**Totals only when complete.** A team's total and rank appear only once both the counted scan and the free-response score are in, as the spec says. Until then the row shows "—" and what is missing. This replaces phase 5's behaviour, where a missing part counted as 0 and the team was still ranked; that could make a half-entered team look like it was losing.

**Ranks.** Total, highest first. Tied teams share a rank, shown as "T1, T1, 3". No tiebreakers (out of scope for v1).

**Free-response entry (Scores tab).**
- The team number and name are shown large. Values are typed on an on-screen keypad (whole or half points, up to the event's maximum) and checked before sending; the server checks again.
- Changing a saved value needs a second tap ("Change team 7 from 12 to 13?") and is in the audit log.
- After saving, the app goes to the next team without a score. This can be turned off, and the phone remembers the choice.
- Each team's history (entered, then each change) is shown under it.

**Results tab.**
- The missing-items line ("3 with no scan, 11 with no free response, 1 waiting for review") filters the table when tapped. It refreshes every few seconds.
- Tapping a row shows who entered each part and when, with links to the sheet (and its history) and to the free-response entry.
- **Print** uses a print stylesheet: just the table, with the event, tournament and time printed.

**CSV.**
- Same rows and order as the table, plus who entered each part and when.
- Times are in UTC (`2026-11-21T14:03:05Z`) so files from different laptops agree.
- It starts with a UTF-8 byte-order mark so Excel shows accented team names correctly, and uses Windows line endings.
- A golden-file test pins the exact bytes.

**Event setup (admin PIN).**
- Upload the event spreadsheet: the phase 1 report is shown first (a dry run), then **Import**.
- Same for the teams CSV: new and renamed teams are counted before saving.
- Each event links to its answer-sheet PDF.
- **Re-score** first says how many sheets would change, and only then asks to go ahead.

**Spec difference kept from phase 5:** the spec says the grader picks which duplicate scan counts. Here any grader can compare duplicates, but only a supervisor chooses.

## 2026-11-21 — Review screen (phase 7)

**What a grader sees.**
- Problems with the team number come first, with a crop of the team-number block and a number pad. A team number that was read cleanly is one line, with a Change button, below the flagged questions.
- Each flagged question shows the crop of its row, what the reader saw in plain words, and tap-to-toggle answer bubbles. The letters the reader detected are ringed.
- The other answers are folded away for a spot check.
- The live score uses the same rules as the server, with exact fractions, and is checked against 40 server-scored sheets. The server still re-scores on save, and its score is the one that counts.
- On a phone the flagged question, the score and **Confirm and count** fit on the first screen.

**Rules added on the server.**
- **Unknown team numbers** (not on the teams list) count only after the grader ticks "count it anyway". The acknowledgement is in the audit log.
- **Discard** takes an optional reason. **Retake** is a discard with reason "retake" that goes back to the camera.
- **Re-open** (supervisor only) turns a counted sheet back into a review item. It stops counting until confirmed again, and is audited.
- **History:** any logged-in grader can see a sheet's history (who changed what, when). The full audit log stays supervisor-only.
- **Team-number crop:** the reader saves a crop of the team-number block for every readable sheet.

**Duplicates.** Anyone can compare a team's sheets side by side: score, who scanned it, when, and the questions where the answers differ. Only a supervisor can choose which one counts, as decided in phase 5; the others are discarded but kept.

**Speed.** The next sheet in the queue (its data and crops) is loaded in the background, so after Confirm the next one opens at once.

**Addresses.** Screens have their own addresses (`#/review/12`), so the phone's Back button works.

**Screenshot check.** The review screen at 390 px is compared with a stored image per platform, since fonts differ between macOS and Linux. On CI it is recorded and attached to the run as `review-screenshots`.

## 2026-11-21 — Phone app and camera capture (phase 6)

**Stack.**
- Vite + React + TypeScript in `frontend/`.
- `vite-plugin-pwa` makes it installable (Add to Home Screen opens full-screen) and caches only the app itself; API calls and photos always go to the network.
- Plain CSS with a few design tokens: no UI kit, large tap targets, iPhone safe areas.
- Types for every API call are generated from the backend's OpenAPI schema (`openapi-typescript`), and CI fails if they drift.

**One origin.**
- In production the backend serves the built app at `/` (`app/web.py`), with a fallback to `index.html` for app paths. That means one HTTPS certificate, no CORS, and the login cookie just works.
- `/api/...` paths that don't exist stay JSON 404s.
- The app's page sends a Content-Security-Policy that only allows its own origin, plus https images for signed storage links.
- In development, Vite passes `/api` on to the backend.

**Corner markers in the browser.**
- A pure-JavaScript ArUco port (js-aruco2, vendored in `src/vendor/` because its old module format breaks modern bundlers). Its dictionaries were replaced by OpenCV's DICT_4X4_50, exported from the same library the server prints with.
- A unit test runs it on a fake phone photo made by the backend to prove the two agree.
- Frames are analysed about 8 times a second at 960 px on the long side. Full OpenCV.js was rejected as too big for phones.

**Auto-capture rule.**
- The picture is taken when all four corners are seen in every frame for 0.5 s, with none moving more than about 0.6% of the frame (around 6 px). The page must also cover at least 20% of the frame and be bright enough.
- After a capture it waits until a corner leaves the view (the next sheet goes down) and at least 1 s has passed, so one sheet is never captured twice.
- The shutter button always works.
- The still is a full-resolution JPEG at quality 0.9: `ImageCapture.takePhoto()` where the browser has it, otherwise the full video frame.

**Uploads survive Wi-Fi drops.**
- Every photo is saved on the phone (IndexedDB) before it is sent, and removed only when the server accepts it.
- Network trouble, timeouts, rate limits and server errors retry after 1, 2, 4 … up to 30 s, and at once when the phone comes back online.
- A logged-out session pauses the queue until the grader logs in again.
- Files the server refuses (wrong type, too big) stay listed with the reason until dismissed.
- Photos are stored as raw bytes, not Blobs, because Safari refuses Blobs in IndexedDB in private windows. If the phone refuses to store anything at all, the upload still goes from memory.

**Status list.** The Scan screen checks this event's scans every 2 s while the app is in view, and right after each upload.

**Bug fixed: PDFs read in parallel.** PDFium, the library that renders PDF pages, is not safe to use from two threads at once. The two background readers could get garbage pages and flag them `page_not_found`. Every PDFium call now goes through one lock. The new 3-page PDF browser test found it.

## 2026-11-21 — API, login, storage and counting rules (phase 5)

**Login.**
- A grader types the shared tournament PIN and their name; supervisors use a separate admin PIN.
- The session is a signed, HTTP-only, Secure, SameSite=Lax cookie that lasts one tournament day. There is no session table: the signature (`SESSION_SECRET`) is the proof.
- PINs are compared in constant time, and 10 wrong PINs from one IP in 5 minutes block that IP for a while, so the PIN can't be brute-forced.
- Admin-only actions: importing events and teams, choosing between duplicate scans, re-scoring, and reading the audit log.

**Uploads.**
- A photo (JPEG, PNG, HEIC) or PDF, up to 25 MB and 60 pages. The type is checked by the file's content, never by its name.
- The original is stored under a random key and never modified; the uploaded filename is never used.
- Each PDF page becomes its own scan, all pointing at the one original.
- Uploads return at once and are read in a small background thread pool. The phone checks back every second or so, which works reliably on phones.
- Scans left half-read by a server restart are retried on startup.

**Storage.**
- Local folder in development.
- In production, a **private** Supabase Storage bucket, reached with the service-role key from the server only. Viewers get 10-minute signed links, so the bucket is never public.
- Stored per scan: the original upload, the straightened page, and crops of the flagged questions.

**Counting.**
- A scan **counts automatically** only if nothing on it is flagged, its team number was read, it is on the teams list, and no other scan already counts for that team.
- Everything else waits for a grader.
- A second scan for a team that already counts is marked `duplicate_team`. It never replaces the first by itself: a supervisor picks one, and the rest are discarded. The database also enforces at most one counted scan per team.
- If the QR says a different event than the grader picked, the sheet's own event wins and the scan is flagged `event_mismatch`.

**Edits.**
- Corrections from the review screen re-score the scan.
- Changing the team on a counted scan un-counts it until it is confirmed again.
- Every change to an existing score (marks, team, status, counted, free response, re-score) is in the audit log with who, when, old and new value.

**Results.**
- Total = counted scan's multiple choice + free response, ranked by total; ties share a rank (1, 2, 2, 4).
- Teams with nothing yet are listed without a rank, and the "missing" column says what is still needed.
- The CSV has the same columns.

**Errors** are always `{"detail": "...", "code": "..."}`. Every reply carries an `X-Request-ID` and basic security headers. CI runs `pip-audit` on the locked dependencies.

## 2026-11-21 — Reading sheets: method and thresholds (phase 4)

**Method:** classic computer vision (OpenCV), no machine learning, so every decision can be explained and tested. The steps, in `backend/app/services/detection/`:

1. **Load.** JPEG, PNG and iPhone HEIC are accepted, with EXIF rotation applied; each page of a PDF is rendered at 200 dpi. Images are downscaled to 2500 px on the long edge.
2. **Find the page.** The four ArUco corner markers are located, trying several image enhancements. Three markers are enough (flagged `marker_missing`). With fewer, the reader asks the grader to **retake** the photo, so nothing on that page is guessed.
3. **Straighten.** The photo is warped onto the printed layout at 200 dpi. Marker IDs fix the orientation, so sideways and upside-down photos work.
4. **Identify the event** from the QR code. If it can't be read (`event_unknown`), the event the grader picked by hand is used.
5. **Even out the lighting.** Each pixel's darkness is measured against the paper around it, which removes shadows, gradients and colour casts.
6. **Line up each row.** Each row of bubbles is matched to its printed circle outlines, following the row above it down the column, which handles curled paper.
7. **Measure each bubble.** It gets the larger of two scores, both relative to this page's own solid pencil marks:
   - (a) mean darkness above that letter's blank level, since blank bubbles still hold a printed letter;
   - (b) the share of the bubble covered by real pencil.
   
   Score (b) separates partial and light marks from erasures: an erasure is faint everywhere, while a real mark has a patch of real pencil.
8. **Decide** marked, blank, or ask a human.

**Thresholds** (`detection/config.py`, chosen on 600 tuning sheets and checked on 600 different held-out sheets):

| Setting | Value | Why |
|---|---|---|
| Blank below | 0.15 of the page's solid level | Empty bubbles reach at most ~0.13; erasures sit around 0.05–0.17 |
| Marked at or above | 0.22 | The faintest real marks (light scribble, partial fill, tick, cross) start around 0.22 |
| Between the two | → `ambiguous`, human review | Only near-erasures and very faint marks land here |
| Two+ marks, one 2.5× fainter | → `multiple_marks`, review | Probably an erasure next to an answer |
| Equally dark double mark | read as given | On a one-answer question it scores 0 under `exact`, which is the rule |
| Row outline contrast < 70% of page | → `low_contrast`, review | Glare or a dim patch fades marks as much as outlines; boosting was tried and was unsafe |
| Row needed the whole alignment search | → `alignment_uncertain`, review | Better to ask than to read the wrong row |
| Printed-outline sharpness < 0.45 | page `image_blurry`: marked ≥ 0.60, blank < 0.06 | Blurry photos read conservatively, so more goes to review |
| Blank level per letter | lower quartile, capped at page blank + 0.06 | On short tests most teams may pick the same letter; a plain median then called real marks "empty" |
| Team digit | exactly one clear mark, else flagged | A team number is never guessed |

**Never silent:** an unreadable page is a retake, an uncertain bubble or row goes to review, and an unclear team number is flagged. The accuracy report counts *silent* errors (wrong and not flagged) as the main measure, and CI fails if they increase on a fixed 60-sheet set (`backend/tests/regression/`).

**Speed:** about 0.4 s per photo and 0.6 s for a 12-megapixel iPhone photo, on one CPU core.

**Known limits** (fake photos only so far; real phone photos are to be added in end-to-end testing):
- Heavy motion blur is usually a retake.
- Focus blur and glare send more questions to review.
- Strongly curled paper often flags the team number for a human.

## 2026-11-21 — Fake-sheet test harness (phase 3)

**Why fakes first.** The reader (phase 4) is judged against thousands of fake photos whose answers are known exactly. That lets us measure accuracy per condition before any real tournament, and catch regressions in CI.

**What a fake sheet is.** The real printed page (phase 2), with pencil marks painted at the exact bubble positions, then "photographed" under one of 20 conditions:
- clean;
- rotation: small, large, 90°, 180°;
- distance and framing: perspective tilt up to ~25°, far, near, one corner at the frame edge;
- blur: focus and motion;
- lighting: shadow band, glare, uneven light, low light with noise;
- image quality: heavy JPEG, warm colour cast;
- paper and surroundings: curl, desk clutter;
- a stacked "phone" mix of mild problems.

Photos are 1500×2000, a downscaled phone photo. Every sheet comes only from (seed, index), so datasets rebuild byte-for-byte.

**What counts as the right answer.** The truth is what the student *meant*:
- solid, light, partial, tick and cross marks all count as chosen;
- an erased smudge counts as blank;
- stray marks outside bubbles count for nothing;
- a team-number column left empty or with two digits has no correct number: the right behaviour is to flag it for a human, not guess.

**The key metric is the silent error rate:** questions read wrong *and* not flagged for review. A flagged mistake is fixed on the review screen; a silent one changes a team's score unnoticed. The report also gives:
- bubble, question and team accuracy;
- flag rate;
- QR read rate;
- score error;

all per condition and per fill style.

**Real photos.** These use the same label format under `backend/data/real_samples/`. Only staff-filled samples (`staff/`) can be committed; anything else there is git-ignored, so student sheets never reach the public repo.

## 2026-11-21 — Answer-sheet layout and libraries (phase 2)

**One layout, two users.** `app/services/layout.py` computes every position on the page (markers, QR, team grid, each bubble) from the event setup. The PDF renderer only draws that, and the reader (phase 4) will only read that, so the printed page and the reader cannot disagree. Positions are in PDF points from the top-left corner, rounded to 0.01 pt, and golden files catch any accidental change. `LAYOUT_VERSION` must go up whenever positions change.

**Look.** It follows the ZipGrade-style sheet supervisors already use: lettered bubbles in columns, a team-name box at the top left, a team-number grid at the bottom right (one column per digit, write-in boxes above, digits 0–9). Added on top are four corner markers and a QR code. Columns are balanced so they come out even.

**Fitting the page.** Bubble spacing starts at 0.25 in and shrinks in 0.01 in steps down to 0.21 in only if needed. 100 five-choice questions fit at full spacing. If an event cannot fit even at 0.21 in, the import report says so and names how many would fit; the app never prints a cramped sheet.

**Machine-readable parts.**
- Four ArUco markers (`DICT_4X4_50`, IDs 0–3 clockwise from top-left, 0.6 in) let the reader find the page and its orientation from any phone photo, even upside down.
- The QR code holds `{"e":"<event_id>","v":<sheet_version>}`, so a scan knows which event and key to use. The error correction is at least M; the library raises it to Q when that fits at the same size.

**Copier-safe.** Pure black on white, no grey. Bubble letters are printed in thin black, which the reader will account for. The header asks for printing at 100% (actual size).

**Libraries.**
- `reportlab` draws the PDF; it was chosen because it can produce byte-identical files, so the same event always gives the same PDF.
- `segno` makes the QR code (pure Python).
- `opencv-contrib-python-headless` makes the ArUco markers and will read sheets in phase 4.
- `pypdfium2` turns the PDF into an image for tests and the phase 3 fake-sheet generator.

## 2026-11-21 — The app is event-agnostic

Nothing is built or tuned for a specific test. A&P was only the first example. Each event's numbers (question count, numbering, options per question, points, total, free-response share) come from its setup spreadsheet. `event_setups/` holds examples; CI imports every one of them. The Forensics example copies a real sheet's *structure* (only 11 bubble questions, numbered with gaps, 3–5 options, half points, 286/300 free response), but its correct letters are made up because this repo is public.

## 2026-11-21 — Scoring rules (phase 1)

**Exact questions:** full points only if the marked bubbles are exactly the key, otherwise 0. Marking an extra bubble on a single-answer question gets 0.

**Partial questions:** `points × (correct picks ÷ number of correct answers) − penalty_per_wrong × wrong picks`, never below 0 and never above the question's points.
- *Over-marking:* with `penalty_per_wrong` = 0, extra wrong bubbles cost nothing. Marking every bubble then earns full points. This is what the template's formula says, so it is kept as written. Supervisors who use `partial` should set a penalty if over-marking should be punished.
- Worked example: key A,C worth 2 points, penalty 0.25. Marked A → 2 × ½ = **1**. Marked A,B → 1 − 0.25 = **0.75**. Marked A,B,C → 2 − 0.25 = **1.75**. Marked B,D → 0 − 0.5, floored to **0**.

**Rounding:** all arithmetic uses exact decimals. Each question's points are kept exact (⅓ stays ⅓), and only the sheet total is rounded, to 2 decimals, half-up (0.125 → 0.13). Three ⅓-point answers total 1.00, not 0.99.

## 2026-11-21 — Re-importing an event setup (phase 1)

- New `event_id` → saved.
- Same `event_id`, **no scans yet** → the event's settings and questions are replaced. Fixing mistakes while setting up is easy.
- Same `event_id`, **scans exist** → refused unless `sheet_version` on the Event tab is higher than the saved one. This stops the answer key silently changing under scores that already exist. With a higher version, the new key is saved and old scans keep their old version number; re-scoring them is a phase 5 feature.
- The import commands only check the file unless `--save` is given.
- The spreadsheet's formula rows (`mcq_points_total (auto)`, `check`) are ignored. The total is recomputed from the question rows, because formula values are often missing when a file is saved by tools other than Excel.

## 2026-11-21 — Database: Supabase (Postgres), accessed through SQLAlchemy

**Choice:** Supabase for production (hosted Postgres + Storage for scan images). SQLite for local dev and tests.

**Why not Firebase:** The data is relational: events → questions, teams, scans → per-question marks, free-response scores, and an audit log. The results table is a join of scans and free-response scores per (event, team), with uniqueness rules (one counting scan per team per event). That is natural in SQL and awkward in Firestore (no joins, no unique constraints, denormalised writes). The spec also already says "SQLite for dev, Postgres in production", which Supabase is.

**How we use it:** The FastAPI backend talks to the database only through SQLAlchemy and Alembic migrations, with `DATABASE_URL` choosing SQLite or Supabase Postgres. No Supabase client SDK in the backend, so the app is not locked in and tests run without network. Scan images go through a small storage interface: local folder in dev, Supabase Storage bucket in production (added in build step 4/7). Grader login is the app's own shared-PIN + grader name (spec), not Supabase Auth, to keep the iPhone flow to one screen.

## 2026-11-21 — Repo layout

- `backend/` — Python 3.12+ FastAPI app (`app/`), Alembic migrations, pytest tests. Managed with `uv`.
- `frontend/` — PWA, created at build step 5.
- `event_setups/` — supervisor spreadsheets (A&P is the first real event).
- `docs/` — spec (`STARTER_PROMPT.md`) and this file.
