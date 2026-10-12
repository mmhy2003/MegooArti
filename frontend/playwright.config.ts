import { defineConfig, devices } from "@playwright/test";

/**
 * Tests in a real browser, against a running installation reached through its gateway.
 *
 * They are run by the backend's `docker` suite (backend/tests/test_ui_client.py), which
 * starts a fresh stack and passes its address and the generated administrator password.
 * To run them by hand against a stack of your own:
 *
 *   MEGOOARTI_UI_URL=http://localhost:8000 MEGOOARTI_INITIAL_PASSWORD=... pnpm e2e
 */
export default defineConfig({
  testDir: "./e2e",
  // One installation and one administrator: the flows follow each other.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"]],
  timeout: 60_000,
  // The stack is often busy with other tests beside these.
  expect: { timeout: 15_000 },
  use: {
    // `localhost`: a browser keeps a Secure cookie over plain HTTP only at a loopback
    // address, and every browser agrees on this one.
    baseURL: process.env.MEGOOARTI_UI_URL ?? "http://localhost:8000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
