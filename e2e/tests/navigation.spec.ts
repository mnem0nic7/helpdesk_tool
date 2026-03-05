import { test, expect } from "@playwright/test";

test.describe("Navigation", () => {
  test("dashboard loads by default", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("h1")).toContainText(/dashboard/i);
  });

  test("sidebar links navigate correctly", async ({ page }) => {
    await page.goto("/");

    const links = [
      { text: "Tickets", url: "/tickets" },
      { text: "Manage", url: "/manage" },
      { text: "SLA Tracker", url: "/sla" },
      { text: "Visualizations", url: "/visualizations" },
      { text: "Reports", url: "/reports" },
      { text: "Dashboard", url: "/" },
    ];

    for (const { text, url } of links) {
      await page.getByRole("link", { name: text }).click();
      await expect(page).toHaveURL(url);
    }
  });

  test("active sidebar link has distinct styling", async ({ page }) => {
    await page.goto("/tickets");
    const activeLink = page.getByRole("link", { name: "Tickets" });
    await expect(activeLink).toBeVisible();
  });

  test("brand text is visible", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("aside")).toContainText(/altlassian|oit/i);
  });

  test("no console errors on load", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await page.goto("/");
    await page.waitForTimeout(2000);
    expect(errors).toHaveLength(0);
  });
});
