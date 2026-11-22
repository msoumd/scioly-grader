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
