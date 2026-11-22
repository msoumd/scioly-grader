import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("wrong PIN is refused with a clear message", async ({ page }) => {
  await login(page, "Pat Grader", "0000");
  await expect(page.getByRole("alert")).toContainText("Wrong PIN");
  await expect(page.getByLabel("Tournament PIN")).toHaveValue("");
});

test("log in, pick the event, and the phone remembers both", async ({ page }) => {
  await login(page, "Robin Volunteer");
  await expect(page.getByRole("heading", { name: "Which event are you grading?" })).toBeVisible();
  await page.getByRole("button", { name: /Anatomy/ }).click();

  const event = page.getByRole("button", { name: /Event: .*Change event/ });
  await expect(event).toContainText("Robin Volunteer");
  await expect(page.getByRole("button", { name: "Scan" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "Results" })).toBeEnabled();

  await page.reload(); // still logged in, same event, no picker
  await expect(event).toContainText("Robin Volunteer");

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByLabel("Your name")).toHaveValue("Robin Volunteer"); // name remembered
});
