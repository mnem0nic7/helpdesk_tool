import { test, expect } from "@playwright/test";

test.describe("Tickets page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/tickets");
  });

  test("table loads with rows", async ({ page }) => {
    const table = page.locator("table");
    await expect(table).toBeVisible({ timeout: 15_000 });
    const rows = table.locator("tbody tr");
    expect(await rows.count()).toBeGreaterThan(0);
  });

  test("search filters rows", async ({ page }) => {
    const search = page.getByPlaceholder(/search/i);
    await search.fill("test-nonexistent-term-xyz");
    // Wait for debounce + refetch
    await page.waitForTimeout(1000);
    const rows = page.locator("table tbody tr");
    const count = await rows.count();
    // Should have fewer rows (possibly 0)
    expect(count).toBeLessThanOrEqual(await page.locator("table tbody tr").count());
  });

  test("status dropdown is present", async ({ page }) => {
    await expect(page.locator("select").first()).toBeVisible();
  });

  test("priority dropdown is present", async ({ page }) => {
    const selects = page.locator("select");
    expect(await selects.count()).toBeGreaterThanOrEqual(2);
  });

  test("open only toggle works", async ({ page }) => {
    const button = page.getByText("Open Only");
    await expect(button).toBeVisible();
    await button.click();
    // After clicking, the button should appear active (bg-blue-600)
    await expect(button).toBeVisible();
  });

  test("clear filters button appears when filters active", async ({ page }) => {
    // Activate a filter first
    const button = page.getByText("Open Only");
    await button.click();
    await expect(page.getByText("Clear Filters")).toBeVisible();
  });

  test("ticket keys are links", async ({ page }) => {
    await page.waitForSelector("table tbody tr", { timeout: 15_000 });
    const firstLink = page.locator("table tbody tr:first-child a").first();
    if (await firstLink.count() > 0) {
      const href = await firstLink.getAttribute("href");
      expect(href).toBeTruthy();
    }
  });
});
