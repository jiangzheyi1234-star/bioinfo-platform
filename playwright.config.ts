import { defineConfig, devices } from "@playwright/test";

const API_BASE = process.env.E2E_API_BASE || "http://127.0.0.1:8765";
const WEB_BASE = process.env.E2E_WEB_BASE || "http://127.0.0.1:3765";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  timeout: 120_000,
  expect: {
    timeout: 15_000,
  },
  use: {
    baseURL: WEB_BASE,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    extraHTTPHeaders: {
      "Accept-Language": "zh-CN",
    },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});

export { API_BASE, WEB_BASE };
