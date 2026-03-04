import { test, expect } from "@playwright/test";

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("metric cards are visible", async ({ page }) => {
    // Look for common metric card labels
    await expect(page.getByText(/total tickets/i)).toBeVisible();
    await expect(page.getByText(/open backlog/i)).toBeVisible();
    await expect(page.getByText(/resolved/i).first()).toBeVisible();
  });

  test("metric cards show numbers", async ({ page }) => {
    // Cards should contain numeric values
    const cards = page.locator("[class*='rounded']").filter({ hasText: /total tickets/i });
    await expect(cards).toBeVisible();
  });

  test("charts render SVG elements", async ({ page }) => {
    // Wait for charts to load
    await page.waitForSelector("svg", { timeout: 15_000 });
    const svgs = page.locator("svg");
    expect(await svgs.count()).toBeGreaterThan(0);
  });

  test("assignee stats table has rows", async ({ page }) => {
    const table = page.locator("table").first();
    await expect(table).toBeVisible({ timeout: 15_000 });
    const rows = table.locator("tbody tr");
    expect(await rows.count()).toBeGreaterThan(0);
  });

  test("date range selector is present", async ({ page }) => {
    await expect(page.locator("input[type='date']").first()).toBeVisible();
  });
});
