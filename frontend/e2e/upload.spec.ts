import { expect, test } from "@playwright/test";
import { asset, scanRow, startScanning } from "./helpers";

const UPLOAD = "Upload photos or PDF";

test("a photo upload is read and counted for the right team", async ({ page }) => {
  await startScanning(page);
  await page.getByLabel(UPLOAD).setInputFiles(asset("sheet_team7.jpg"));
  const row = scanRow(page, 7);
  await expect(row).toContainText("Counted", { timeout: 30_000 });
  await expect(row).toContainText("60.00");
  await expect(page.getByRole("list", { name: "Uploads waiting" })).toHaveCount(0);
});

test("a 3-page PDF becomes three scans", async ({ page }) => {
  await startScanning(page);
  await page.getByLabel(UPLOAD).setInputFiles(asset("three_pages.pdf"));
  for (const team of [8, 9, 10]) {
    await expect(scanRow(page, team)).toContainText("Counted", { timeout: 45_000 });
  }
});

test("an upload made while offline is sent when the connection returns", async ({
  page,
  context,
}) => {
  await startScanning(page);
  await context.setOffline(true);
  await page.getByLabel(UPLOAD).setInputFiles(asset("sheet_team12.jpg"));
  const waiting = page.getByRole("list", { name: "Uploads waiting" });
  await expect(waiting).toContainText("Waiting to upload");

  await page.reload().catch(() => undefined); // offline reload: served by the app's offline cache
  await context.setOffline(false);
  await page.goto("/");
  await expect(scanRow(page, 12)).toContainText("Counted", { timeout: 45_000 });
  await expect(page.getByRole("list", { name: "Uploads waiting" })).toHaveCount(0);
});
