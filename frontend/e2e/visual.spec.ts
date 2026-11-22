import { expect, test } from "@playwright/test";
import { startScanning, uploadAndReview } from "./helpers";

// Screenshot of the review screen as first seen on an iPhone (390 px wide). Fonts differ between macOS and
// Linux, so the reference image is per platform: on a Mac it is compared with the committed
// one; on CI (Linux) it is recorded and uploaded with the test report.
test("review screen at 390 px", async ({ page, browserName }, info) => {
  test.skip(browserName !== "webkit", "iPhone layout check runs on WebKit");
  await startScanning(page);
  await uploadAndReview(page, "review_erased_team4.jpg");
  await expect(page.getByRole("region", { name: "Question 5" }).getByRole("img")).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  expect(page.viewportSize()?.width).toBe(390);
  const shot = await page.screenshot();
  await info.attach("review-screen-390px", { body: shot, contentType: "image/png" });
  await expect(page).toHaveScreenshot("review-390.png", {
    mask: [page.getByRole("heading", { level: 1 })], // sheet number differs run to run
    maxDiffPixelRatio: 0.02,
  });
});

// Results and free-response entry as seen on an iPhone. Recorded for the report (their
// contents depend on what the other tests entered, so they are not compared).
test("results and score entry at 390 px", async ({ page, browserName }, info) => {
  test.skip(browserName !== "webkit", "iPhone layout check runs on WebKit");
  await startScanning(page);
  await page.goto("/#/results");
  await expect(page.locator("table.results tbody tr").first()).toBeVisible();
  await info.attach("results-390px", { body: await page.screenshot(), contentType: "image/png" });
  await page.screenshot({ path: "e2e/__screenshots__/results-390-webkit-iphone.png" });
  await page.goto("/#/scores/3");
  await expect(page.getByText("E2E Team 3")).toBeVisible();
  await page.screenshot({ path: "e2e/__screenshots__/scores-390-webkit-iphone.png" });
  // Save must be reachable without scrolling.
  const save = await page.getByRole("button", { name: "Save" }).boundingBox();
  const tabbar = await page.getByRole("navigation", { name: "Sections" }).boundingBox();
  expect(save!.y + save!.height).toBeLessThanOrEqual(tabbar!.y);
});
