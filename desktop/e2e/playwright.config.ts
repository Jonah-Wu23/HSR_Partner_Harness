import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const desktopRoot = resolve(import.meta.dirname, "..");
const mobileRoot = resolve(desktopRoot, "mobile");
const ci = Boolean(process.env.CI);

export default defineConfig({
  testDir: ".",
  testMatch: "conversation-list.spec.ts",
  timeout: 60_000,
  fullyParallel: true,
  reporter: ci ? "github" : "list",
  outputDir: resolve(desktopRoot, "..", "output", "playwright", "test-results"),
  retries: ci ? 1 : 0,
  use: {
    ...devices["Desktop Chrome"],
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : undefined,
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "npm run dev -- --host 127.0.0.1 --port 1422 --strictPort",
      cwd: desktopRoot,
      url: "http://127.0.0.1:1422/e2e/desktop-list.html",
      reuseExistingServer: !ci,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 1423 --strictPort",
      cwd: mobileRoot,
      url: "http://127.0.0.1:1423/e2e/mobile-list.html",
      reuseExistingServer: !ci,
      timeout: 120_000,
    },
  ],
});
