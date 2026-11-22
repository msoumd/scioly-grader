import { expect, type Page } from "@playwright/test";
import path from "node:path";

export const PIN = "2468";
export const asset = (name: string) => path.resolve(import.meta.dirname, ".assets", name);

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
    .filter({ hasText: `Team ${team}` });
}
