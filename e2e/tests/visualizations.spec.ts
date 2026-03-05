import { test, expect } from "@playwright/test";

test.describe("Visualizations page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/visualizations");
  });

  test("page loads with title", async ({ page }) => {
    await expect(page.getByText("Visualizations")).toBeVisible();
  });

  test("all 7 presets are visible", async ({ page }) => {
    await expect(page.getByText("Tickets by Status")).toBeVisible();
    await expect(page.getByText("Tickets by Priority")).toBeVisible();
    await expect(page.getByText("Assignee Workload")).toBeVisible();
    await expect(page.getByText("Resolution Times")).toBeVisible();
    await expect(page.getByText("Age by Status")).toBeVisible();
    await expect(page.getByText("Weekly Trend")).toBeVisible();
    await expect(page.getByText("Monthly Trend")).toBeVisible();
  });

  test("preset click renders chart", async ({ page }) => {
    await page.getByText("Tickets by Status").click();
    await page.waitForSelector("svg", { timeout: 15_000 });
    expect(await page.locator("#chart-container svg").count()).toBeGreaterThan(0);
  });

  test("mode toggle switches to timeseries", async ({ page }) => {
    await page.getByText("Time Series").click();
    await expect(page.getByText("Time bucket")).toBeVisible();
  });

  test("chart type buttons are present", async ({ page }) => {
    await expect(page.getByText("Bar")).toBeVisible();
    await expect(page.getByText("Pie")).toBeVisible();
  });

  test("group-by dropdown updates chart", async ({ page }) => {
    // Select a preset first to ensure grouped mode
    await page.getByText("Tickets by Status").click();
    const groupBySelect = page.locator("select").first();
    await groupBySelect.selectOption("priority");
    // Wait for chart to update
    await page.waitForTimeout(1500);
    await page.waitForSelector("#chart-container svg", { timeout: 10_000 });
  });

  test("download PNG button exists", async ({ page }) => {
    await expect(page.getByText("Download as PNG")).toBeVisible();
  });

  test("weekly trend preset loads timeseries chart", async ({ page }) => {
    await page.getByText("Weekly Trend").click();
    await page.waitForSelector("svg", { timeout: 15_000 });
    expect(await page.locator("#chart-container svg").count()).toBeGreaterThan(0);
  });
});
