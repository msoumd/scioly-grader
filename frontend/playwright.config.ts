/**
 * Browser tests against the real backend (SQLite, seeded with the example A&P event) serving
 * the built app. Each browser gets its own server and database so they never share scans.
 * Run `npm run build` first; fixtures are made by backend/scripts/e2e_assets.py.
 */
import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const ASSETS = path.resolve(import.meta.dirname, "e2e/.assets");
export const PIN = "2468";

function server(name: string, port: number) {
  const db = `sqlite:///./data/e2e/${name}.db`;
  return {
    command: `uv run python scripts/seed_e2e.py ${db} && uv run uvicorn app.main:app --port ${port}`,
    cwd: path.resolve(import.meta.dirname, "../backend"),
    url: `http://localhost:${port}/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "ignore" as const,
    stderr: "pipe" as const,
    env: {
      DATABASE_URL: db,
      TOURNAMENT_PIN: PIN,
      ADMIN_PIN: "13579",
      SESSION_SECRET: `e2e-only-secret-${"x".repeat(40)}`,
      COOKIE_SECURE: "false",
      UPLOAD_DIR: `./data/e2e/uploads-${name}`,
      FRONTEND_DIST: path.resolve(import.meta.dirname, "dist"),
      STORAGE_BACKEND: "local",
    },
  };
}

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { trace: "on-first-retry", screenshot: "only-on-failure" },
  webServer: [server("chromium", 8765), server("webkit", 8766)],
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Pixel 7"],
        baseURL: "http://localhost:8765",
        permissions: ["camera"],
        launchOptions: {
          args: [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            `--use-file-for-fake-video-capture=${path.join(ASSETS, "camera_team11.y4m")}`,
          ],
        },
      },
    },
    {
      name: "webkit-iphone",
      use: { ...devices["iPhone 13"], baseURL: "http://localhost:8766" },
    },
  ],
});
