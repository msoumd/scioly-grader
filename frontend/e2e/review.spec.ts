import { expect, test } from "@playwright/test";
import { ADMIN_PIN, login, results, startScanning, uploadAndReview } from "./helpers";

test("a rubbed-out second mark: fix it, confirm, and it counts with the right score", async ({
  page,
}) => {
  await startScanning(page);
  const id = await uploadAndReview(page, "review_erased_team4.jpg");

  const q5 = page.getByRole("region", { name: "Question 5" });
  await expect(q5).toContainText("Reader saw");
  await expect(q5.getByRole("img")).toBeVisible(); // crop of the row
  // The real answer is C; make sure only C is marked.
  for (const letter of ["A", "B", "D"]) {
    const b = q5.getByRole("button", { name: `Question 5 ${letter}` });
    if ((await b.getAttribute("aria-pressed")) === "true") await b.click();
  }
  const c = q5.getByRole("button", { name: "Question 5 C" });
  if ((await c.getAttribute("aria-pressed")) !== "true") await c.click();
  await expect(page.getByLabel("Score")).toHaveText("60.00");

  await page.getByRole("button", { name: "Confirm and count" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Team 4 counted: 60.00" })).toBeVisible();
  expect((await results(page))[4]?.mcq).toBe("60.00");

  await page.goto(`/#/review/${id}`);
  await expect(page.getByText(/This sheet counts for team 4/)).toBeVisible();
  // Its photos are gone once counted; the answers stay.
  await expect(page.getByText(/photos were deleted once it was counted/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Show original photo" })).toHaveCount(0);
});

test("missing team number: type it on the keypad, confirm, and the change is in the history", async ({
  page,
}) => {
  await startScanning(page);
  const id = await uploadAndReview(page, "review_noteam_a.jpg");
  const team = page.getByRole("region", { name: "Team number" });
  await expect(team).toContainText("Type the team number");
  await expect(page.getByRole("button", { name: "Type the team number" })).toBeDisabled();

  const pad = team.getByRole("group", { name: "Team number keypad" });
  await pad.getByRole("button", { name: "5" }).click();
  await expect(team).toContainText("E2E Team 5");
  await page.getByRole("button", { name: "Confirm and count" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Team 5 counted" })).toBeVisible();

  await page.goto(`/#/review/${id}`);
  await expect(page.getByText(/Pat Grader changed team number from blank to 5/)).toBeVisible();
});

test("unknown team number: warned, and counts only after ticking the acknowledgement", async ({
  page,
}) => {
  await startScanning(page);
  await uploadAndReview(page, "review_team99.jpg");
  await expect(page.getByText("Team 99 isn't on the teams list.")).toBeVisible();
  const confirm = page.getByRole("button", { name: "Confirm and count" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel(/Count it for team 99 anyway/).check();
  await confirm.click();
  await expect(page.getByRole("status").filter({ hasText: "Team 99 counted" })).toBeVisible();
});

test("retake discards the sheet and goes back to the camera", async ({ page }) => {
  await startScanning(page);
  const id = await uploadAndReview(page, "review_noteam_b.jpg");
  await page.getByRole("button", { name: "Retake" }).click();
  await expect(page.getByRole("button", { name: "Start camera" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Take a new photo" })).toBeVisible();
  const row = page.locator(`[data-scan-id="${id}"]`);
  await expect(row).toHaveAttribute("data-status", "discarded");
});

test("discard with a reason", async ({ page }) => {
  await startScanning(page);
  const id = await uploadAndReview(page, "review_noteam_b.jpg");
  await page.getByRole("button", { name: "Discard", exact: true }).click();
  await page.getByLabel("Why? (optional)").fill("photo of the wrong sheet");
  await page.getByRole("button", { name: "Discard sheet" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Sheet discarded" })).toBeVisible();
  await page.goto(`/#/review/${id}`);
  await expect(page.getByText("Discarded: photo of the wrong sheet")).toBeVisible();
});

test("duplicate sheets: a supervisor compares and picks the second; results use it", async ({
  page,
}) => {
  await startScanning(page);
  await page
    .getByLabel("Upload photos or PDF")
    .setInputFiles((await import("./helpers")).asset("review_dup_team6_a.jpg"));
  await expect.poll(async () => (await results(page))[6]?.mcq, { timeout: 30_000 }).toBe("60.00");
  const second = await uploadAndReview(page, "review_dup_team6_b.jpg");
  await expect(page.getByText("Team 6 already has a counted sheet.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm and count" })).toBeDisabled();

  // Graders can compare but not choose.
  await page.getByRole("link", { name: "Compare the sheets" }).click();
  await expect(page.getByText("Only a supervisor")).toBeVisible();
  await expect(page.getByText(/Answers differ on 1 question: Q1: D \/ –/)).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await login(page, "Sam Supervisor", ADMIN_PIN);
  await page.goto("/#/duplicates");
  await page.getByRole("button", { name: `Count sheet #${second}` }).click();
  await expect(
    page.getByRole("status").filter({ hasText: `sheet #${second} now counts` }),
  ).toBeVisible();
  expect((await results(page))[6]?.mcq).toBe("59.00");
});

test("a supervisor can re-open a counted sheet", async ({ page }) => {
  await login(page, "Sam Supervisor", ADMIN_PIN);
  await page.getByRole("button", { name: /Anatomy/ }).click();
  const id = await uploadAndReview(page, "review_noteam_a.jpg");
  await page
    .getByRole("group", { name: "Team number keypad" })
    .getByRole("button", { name: "2" })
    .click();
  await page.getByRole("button", { name: "Confirm and count" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Team 2 counted" })).toBeVisible();
  await page.goto(`/#/review/${id}`);
  await page.getByRole("button", { name: "Re-open for correction" }).click();
  await expect(page.getByRole("button", { name: "Confirm and count" })).toBeVisible();
});

test("review tab shows a count badge and the queue with reasons", async ({ page }) => {
  await startScanning(page);
  await page
    .getByLabel("Upload photos or PDF")
    .setInputFiles((await import("./helpers")).asset("review_noteam_b.jpg"));
  await expect(page.getByLabel(/\d+ to review/)).toBeVisible({ timeout: 30_000 });
  await page
    .getByRole("button", { name: /Review/ })
    .first()
    .click();
  const queue = page.getByRole("list", { name: "Sheets to review" });
  await expect(queue.getByText("team number").first()).toBeVisible();
});
