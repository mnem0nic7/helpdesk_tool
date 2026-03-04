import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  retries: 1,
  use: {
    baseURL: "http://localhost:3002",
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
  // Expect the app to already be running (docker compose up -d)
  // webServer: {
  //   command: "docker compose up -d",
  //   url: "http://localhost:3002",
  //   reuseExistingServer: true,
  // },
});
