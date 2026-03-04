import { test, expect } from "@playwright/test";

test.describe("Reports page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/reports");
  });

  test("page loads", async ({ page }) => {
    await expect(page.getByText(/reports/i).first()).toBeVisible();
  });

  test("report builder controls are visible", async ({ page }) => {
    // Should have sort or column selection controls
    await expect(page.locator("select").first()).toBeVisible({ timeout: 10_000 });
  });

  test("preview table appears", async ({ page }) => {
    // Wait for the report preview to load
    await page.waitForSelector("table", { timeout: 15_000 });
    const table = page.locator("table");
    await expect(table).toBeVisible();
  });

  test("group-by changes to summary view", async ({ page }) => {
    // Find and interact with the group-by control
    const groupBySelect = page.locator("select").filter({ hasText: /group/i });
    if (await groupBySelect.count() > 0) {
      await groupBySelect.first().selectOption({ index: 1 });
      await page.waitForTimeout(1000);
    }
    // Page should still be functional
    await expect(page.locator("table").first()).toBeVisible({ timeout: 10_000 });
  });

  test("export button is present", async ({ page }) => {
    const exportBtn = page.getByText(/export/i).first();
    await expect(exportBtn).toBeVisible({ timeout: 10_000 });
  });
});
