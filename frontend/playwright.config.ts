import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 20000,
  use: { ...devices["Desktop Chrome"], trace: "retain-on-failure" },
});
