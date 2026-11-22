import { expect, type Page } from "@playwright/test";
import path from "node:path";

export const PIN = "2468";
export const asset = (name: string) => path.resolve(import.meta.dirname, ".assets", name);

export const ADMIN_PIN = "13579";

export async function login(page: Page, name = "Pat Grader", pin = PIN) {
  await page.goto("/");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Tournament PIN").fill(pin);
  await page.getByRole("button", { name: "Log in" }).click();
}

/** Log in and choose the A&P event; ends on the Scan screen. */
export async function startScanning(page: Page, name = "Pat Grader") {
  await login(page, name);
  await page.getByRole("button", { name: /Anatomy/ }).click();
  await expect(page.getByRole("list", { name: "Recent scans" })).toBeVisible();
}

export function scanRow(page: Page, team: number) {
  return page
    .getByRole("list", { name: "Recent scans" })
    .getByRole("listitem")
    .filter({ hasText: new RegExp(`Team ${team}(?!\\d)`) });
}

/** Upload a sheet on the Scan screen and open it on the review screen; returns its id. */
export async function uploadAndReview(page: Page, file: string): Promise<number> {
  await page.goto("/#/scan");
  const before = await scanIds(page);
  await page.getByLabel("Upload photos or PDF").setInputFiles(asset(file));
  let id = 0;
  await expect
    .poll(
      async () => {
        const res = await page.request.get("/api/events/AP/scans");
        const scans = (await res.json()) as { id: number; status: string }[];
        const fresh = scans.find((s) => !before.has(s.id));
        id = fresh?.id ?? 0;
        return fresh?.status;
      },
      { timeout: 30_000 },
    )
    .toBe("needs_review");
  await page.goto(`/#/review/${id}`);
  await expect(page.getByRole("heading", { name: new RegExp(`Sheet #${id}`) })).toBeVisible();
  return id;
}

export async function results(page: Page): Promise<Record<number, { mcq: string | null }>> {
  const res = await page.request.get("/api/events/AP/results");
  const body = (await res.json()) as { rows: { team_number: number; mcq: string | null }[] };
  return Object.fromEntries(body.rows.map((r) => [r.team_number, r]));
}

async function scanIds(page: Page): Promise<Set<number>> {
  const res = await page.request.get("/api/events/AP/scans");
  return new Set(((await res.json()) as { id: number }[]).map((s) => s.id));
}
