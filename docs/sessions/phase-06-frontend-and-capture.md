# Phase 6 — Frontend shell and capture

**Starter-prompt step:** 5, first half (capture UI)
**Branch:** `phase-06-capture`
**Depends on:** phase 5 merged

## Goal

An installable, mobile-first web app that a grader opens in iPhone Safari, logs into, picks an event, and captures a sheet: live camera with auto-capture when the page is in view and steady, or photo / PDF upload. The upload goes to the phase 5 API and the grader sees the result status.

## Stack decision (record in `DECISIONS.md`)

- **Vite + React + TypeScript** in `frontend/`, `vite-plugin-pwa` for install + offline shell, plain CSS modules (no heavy UI kit; large tap targets).
- Typed API client generated from the backend OpenAPI schema (`openapi-typescript` + a small fetch wrapper).
- In production the backend serves the built frontend from the same origin (no CORS, one HTTPS certificate). In dev, Vite proxies `/api` to FastAPI.
- Marker detection in the browser with a small ArUco library (`js-aruco2`) on a downscaled video frame, not full OpenCV.js (too large for phones).

## Scope

### In
- App shell, login, event picker, capture (camera + upload), upload progress and status, Playwright e2e setup.

### Out
- Review screen (phase 7), free-response and results screens (phase 8).

## Tasks

1. **Scaffold** `frontend/` with Vite React TS, ESLint + Prettier, Vitest, Playwright. Scripts: `dev`, `build`, `lint`, `typecheck`, `test`, `e2e`.
2. **App shell** — top bar with event name and grader name, bottom tab bar: Scan, Review, Scores, Results (later tabs disabled until their phase). Works at 320–430 px widths; respects iPhone safe areas.
3. **Login** — PIN + grader name; remembers the name on the device; handles wrong PIN and rate-limit messages.
4. **Event picker** — list of events; selection remembered per device.
5. **Camera capture** — `getUserMedia({video: {facingMode: "environment", width: 1920}})`:
   - Overlay showing the four corner targets; each turns green when its marker is detected.
   - Steadiness check: marker positions move < a few px across ~0.5 s.
   - Auto-capture when all 4 markers are seen and steady; also a manual shutter button.
   - Capture a full-resolution still (`ImageCapture.takePhoto` where available, otherwise draw the video frame to a canvas at full size) and upload as JPEG (quality 0.9).
   - Clear messages: "Move closer", "Hold still", "Too dark", "Camera blocked — allow camera in Settings > Safari".
   - Short haptic/sound + flash on capture; ready for the next sheet within ~1 s (graders scan stacks).
6. **Upload path** — file input accepting images (incl. HEIC) and PDF; multiple files; progress bar; queue that retries on network failure (Wi-Fi drops) and keeps items until the server accepts them (IndexedDB).
7. **Status list** — recent scans for this event with status (`processing`, `confirmed`, `needs review`, `failed`), team number and score; polls the API.
8. **Serve from backend** — FastAPI mounts `frontend/dist` at `/` with SPA fallback; build step documented in README.
9. **Accessibility** — labelled buttons, focus states, contrast; the app is usable one-handed.

## Tests

- **Unit (Vitest):** marker-steadiness logic, upload queue retry logic, API client error mapping.
- **E2E (Playwright, Chromium + WebKit with iPhone 13 emulation):**
  - Login success/failure; event picker remembered.
  - Upload a generated fake sheet image → status becomes `confirmed` with the right team number.
  - Upload a 3-page PDF → three scans appear.
  - Camera flow using Chromium's fake camera: `--use-fake-device-for-media-stream --use-file-for-fake-video-capture=sheet.y4m` with a video made from a phase 3 fake sheet → auto-capture fires and the scan is created.
  - Offline/retry: block the network, queue an upload, restore network → upload completes.
- E2E runs against the real backend started on SQLite with a seeded A&P event (fixture script `backend/scripts/seed_e2e.py`).

## CI changes

- New `frontend` job: install, lint, typecheck, unit tests, build.
- New `e2e` job: build frontend, start backend with seeded SQLite, run Playwright (`--trace off`, traces only on retry); upload the Playwright report on failure.

## By the end of this phase

- [ ] On a real iPhone in Safari: log in, pick A&P, point at a printed sheet, auto-capture fires, the scan appears as confirmed or needs-review
- [ ] Photo and multi-page PDF upload work, including HEIC from the iPhone photo library
- [ ] Uploads survive a Wi-Fi drop
- [ ] App can be added to the home screen and opens full-screen
- [ ] Playwright e2e suite covers login, upload, PDF, fake-camera capture and retry; CI green
- [ ] Short screen recording or screenshots attached to the summary

## Review checkpoint for Yuvan

- Try it on your own iPhone over local Wi-Fi (summary will include how to open the dev server on the phone, which needs HTTPS for the camera: use `vite --https` with a local certificate or a temporary tunnel).
- Is auto-capture too eager or too slow?

## Risks

- iOS Safari only allows the camera over HTTPS and after a user tap; the flow starts from a button tap.
- iOS PWAs have quirks with camera in home-screen mode on some versions; keep upload as a fallback that always works.
