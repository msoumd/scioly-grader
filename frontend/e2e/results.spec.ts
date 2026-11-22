import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { ADMIN_PIN, asset, login, startScanning } from "./helpers";

/** Type a free-response total for a team on the Scores tab and save it. */
async function enterFreeResponse(page: Page, team: number, value: string) {
  await page.goto(`/#/scores/${team}`);
  await expect(page.getByText(`Team ${team}`, { exact: true })).toBeVisible();
  const pad = page.getByRole("group", { name: "Number keypad" });
  for (const ch of value) {
    await pad.getByRole("button", { name: ch === "." ? "Decimal point" : ch, exact: true }).click();
  }
  await page.getByRole("button", { name: "Save" }).click();
  // Saving moves on to the next team by itself; wait for it before going anywhere else.
  await expect(
    page.getByRole("status").filter({ hasText: /saved/ }).or(page.getByRole("alertdialog")),
  ).toBeVisible();
}

async function upload(page: Page, file: string) {
  await page.goto("/#/scan");
  await page.getByLabel("Upload photos or PDF").setInputFiles(asset(file));
}

function resultRow(page: Page, team: number) {
  return page.locator(`table.results tr[data-team="${team}"]`);
}

test("free response first, then the scan: the total appears once both are in", async ({ page }) => {
  await startScanning(page);
  await page.getByRole("button", { name: "Results" }).click();
  const noFr = page.getByRole("button", { name: /with no free response/ });
  const before = Number((await noFr.textContent())?.match(/\d+/)?.[0]);

  await enterFreeResponse(page, 1, "100");
  await expect(
    page.getByRole("status").filter({ hasText: "Team 1: free response 100 saved" }),
  ).toBeVisible();

  await page.goto("/#/results");
  await expect(resultRow(page, 1).locator("td").nth(3)).toHaveText("100");
  await expect(resultRow(page, 1).locator("td").nth(4)).toHaveText("—"); // no scan yet: no total
  await expect(page.getByRole("button", { name: /with no free response/ })).toHaveText(
    `${before - 1} with no free response`,
  ); // the missing count updated

  await upload(page, "results_team1.jpg");
  await page.goto("/#/results");
  await expect(resultRow(page, 1).locator("td").nth(4)).toHaveText("160", { timeout: 30_000 });
});

test("scan first, then free response; ranks and CSV match a hand calculation", async ({ page }) => {
  await startScanning(page);
  await upload(page, "results_team3.jpg");
  await page.goto("/#/results");
  await expect(resultRow(page, 3).locator("td").nth(2)).toHaveText("10", { timeout: 30_000 });
  await expect(resultRow(page, 3).locator("td").nth(4)).toHaveText("—");

  await enterFreeResponse(page, 3, "50.5");
  await page.goto("/#/results");
  // Hand calculation: team 1 = 60 + 100 = 160, team 3 = 10 + 50.5 = 60.5; only these two
  // teams have both parts, so they are ranked 1 and 2 and everyone else has no rank.
  await expect(resultRow(page, 1).locator("td")).toHaveText(["1", /^1 /, "60", "100", "160"]);
  await expect(resultRow(page, 3).locator("td")).toHaveText(["2", /^3 /, "10", "50.5", "60.5"]);
  await expect(resultRow(page, 7).locator("td").first()).toHaveText("—");

  // Row detail: who entered what, with links.
  await resultRow(page, 3).getByRole("button").click();
  await expect(page.getByText(/50\.5 entered by Pat Grader/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Open the sheet and its history" })).toBeVisible();

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download CSV" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("AP_results.csv");
  const file = path.join(test.info().outputDir, "results.csv");
  await download.saveAs(file);
  const text = readFileSync(file, "utf-8");
  expect(text.startsWith("﻿")).toBe(true);
  const lines = text.slice(1).trim().split("\r\n");
  expect(lines[0]).toMatch(
    /^rank,team_number,team_name,multiple_choice,free_response,total,missing/,
  );
  expect(lines[1]).toMatch(/^1,1,E2E Team 1,60,100,160,,/);
  expect(lines[2]).toMatch(/^2,3,E2E Team 3,10,50\.5,60\.5,,Pat Grader,.*,Pat Grader,/);
});

test("out-of-range and quarter-point totals are refused", async ({ page }) => {
  await startScanning(page);
  await page.goto("/#/scores/2");
  const value = page.getByLabel(/Free-response total, out of 140/);
  const cases: [string, string][] = [
    ["140.5", "The most is 140."],
    ["10.25", "Use whole or half points"],
    ["", "Type the team's free-response total."],
  ];
  for (const [typed, message] of cases) {
    await value.fill(typed);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("alert")).toContainText(message);
  }
  await expect(page.getByText("Saved:")).toHaveCount(0); // nothing was saved
});

test("changing a saved total asks first and shows in the history", async ({ page }) => {
  await startScanning(page);
  await enterFreeResponse(page, 3, "52");
  const confirm = page.getByRole("alertdialog", { name: "Confirm change" });
  await expect(confirm).toContainText("from 50.5 to 52");
  await confirm.getByRole("button", { name: "Change it" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Team 3: free response 52 saved" }),
  ).toBeVisible();
  await page.goto("/#/scores/3");
  await page.getByText(/^History/).click();
  await expect(page.getByText("Pat Grader changed it from 50.5 to 52")).toBeVisible();
});

test("a supervisor sets up an event and teams from the app and gets the sheet PDF", async ({
  page,
}) => {
  await login(page, "Sam Supervisor", ADMIN_PIN);
  await page.goto("/#/setup");
  await page
    .getByLabel("Choose event spreadsheet (.xlsx)")
    .setInputFiles(
      path.resolve(import.meta.dirname, "../../event_setups/EXAMPLE_forensics_event_setup.xlsx"),
    );
  const report = page.getByRole("region", { name: "Event import report" });
  await expect(report).toContainText("looks good");
  await page.getByRole("button", { name: "Import event" }).click();
  await expect(page.getByRole("status").filter({ hasText: /imported/ })).toBeVisible();

  await page.getByLabel("Choose teams list (.csv)").setInputFiles({
    name: "teams.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("team_number,team_name\n1,E2E Team 1\n13,Late Entry HS\n"),
  });
  await expect(page.getByRole("region", { name: "Teams import report" })).toContainText(
    "1 new teams, 0 renamed",
  );
  await page.getByRole("button", { name: "Import teams" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Teams saved: 1 new" })).toBeVisible();

  const events = page.getByRole("list", { name: "Events" });
  await expect(events).toContainText("Forensics");
  const pdfHref = await events
    .getByRole("listitem")
    .filter({ hasText: "Forensics" })
    .getByRole("link", { name: "Answer sheet PDF" })
    .getAttribute("href");
  const pdf = await page.request.get(pdfHref!);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");

  // Re-score shows how many sheets would change before doing anything.
  await events
    .getByRole("listitem")
    .filter({ hasText: "Anatomy" })
    .getByRole("button", { name: "Re-score" })
    .click();
  await expect(page.getByRole("alertdialog", { name: "Confirm re-score" })).toContainText(
    "Nothing to change",
  );
});

test("a grader can't open event setup", async ({ page }) => {
  await login(page);
  await page.goto("/#/setup");
  await expect(page.getByText("Log in with the admin PIN")).toBeVisible();
});
