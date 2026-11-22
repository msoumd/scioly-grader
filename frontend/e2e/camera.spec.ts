import { expect, test } from "@playwright/test";
import { scanRow, startScanning } from "./helpers";

// Chromium's fake camera plays a still video of a filled-in sheet (team 11). WebKit has no
// fake camera, so this runs on Chromium only.
test("auto-capture fires once on a steady sheet and the scan is created", async ({
  page,
  browserName,
}) => {
  test.skip(browserName !== "chromium", "fake camera is Chromium-only");
  await startScanning(page);
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.getByText("1 captured this session")).toBeVisible({ timeout: 20_000 });
  await expect(scanRow(page, 11)).toContainText("Counted", { timeout: 30_000 });
  await expect(page.getByRole("status").filter({ hasText: "next sheet" })).toBeVisible();

  // The same sheet staying in view is not captured again.
  await page.waitForTimeout(2500);
  await expect(page.getByText("1 captured this session")).toBeVisible();
  await expect(scanRow(page, 11)).toHaveCount(1);
});
