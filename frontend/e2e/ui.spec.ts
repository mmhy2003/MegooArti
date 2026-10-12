import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

/**
 * The UI as a person meets it, from the first sign-in of a fresh installation on.
 * The tests follow each other: each starts where the one before it ended.
 */

const INITIAL_PASSWORD = process.env.MEGOOARTI_INITIAL_PASSWORD ?? "";
const PASSWORD = "chosen-in-the-browser-test";
const REPOSITORY = "browser-test-files";

test.describe.configure({ mode: "serial" });

let context: BrowserContext;
let page: Page;
// Everything the browser asked for, and everything it complained about, in every test.
const requested: string[] = [];
const complaints: string[] = [];

test.beforeAll(async ({ browser, baseURL }) => {
  expect(INITIAL_PASSWORD, "MEGOOARTI_INITIAL_PASSWORD is not set").not.toBe("");
  context = await browser.newContext({ baseURL, colorScheme: "dark" });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  context.on("request", (request) => requested.push(request.url()));
  page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") complaints.push(message.text());
  });
  page.on("pageerror", (error) => complaints.push(String(error)));
});

test.afterAll(async () => {
  await context.close();
});

const shownMode = () => page.evaluate(() => document.documentElement.dataset.theme);

/** No rule of WCAG 2.1 A or AA is broken on the page as it is now: contrast included. */
async function expectAccessible() {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const found = results.violations.map(
    (violation) => `${violation.id}: ${violation.nodes.map((node) => node.html).join(" | ")}`,
  );
  expect(found).toEqual([]);
}

/** The same check in each mode, leaving the page in the dark one. */
async function expectAccessibleInBothModes() {
  for (const mode of ["light", "dark"] as const) {
    await page.evaluate((chosen) => localStorage.setItem("megooarti-theme", chosen), mode);
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await shownMode()).toBe(mode);
    await expectAccessible();
  }
}

async function signIn(password: string) {
  await page.getByLabel("User name").fill("admin");
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("a visitor who is not signed in is asked to sign in", async () => {
  const response = await page.goto("/");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  await expect(page).toHaveTitle("Sign in · MegooArti");
  await expect(page.getByLabel("User name")).toBeFocused();

  const policy = response?.headers()["content-security-policy"] ?? "";
  expect(policy).toContain("default-src 'self'");
  expect(policy).toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'/);
  expect(policy).not.toContain("unsafe-eval");
  expect(response?.headers()["x-frame-options"]).toBe("DENY");
  expect(response?.headers()["x-content-type-options"]).toBe("nosniff");
});

test("the mode is set by the page's head, before any of the UI's code has run", async ({
  browser,
  baseURL,
}) => {
  for (const system of ["light", "dark"] as const) {
    const bare = await browser.newContext({ baseURL, colorScheme: system });
    const fresh = await bare.newPage();
    // With every script file refused, only what is written into the page can run.
    await fresh.route("**/*.js", (route) => route.abort());
    await fresh.goto("/login", { waitUntil: "domcontentloaded" });

    expect(await fresh.evaluate(() => document.documentElement.dataset.theme)).toBe(system);
    await bare.close();
  }
});

test("what the head set is not undone while the page starts", async ({ browser, baseURL }) => {
  // Every value `data-theme` takes through a whole load, the UI's own code included.
  const watch = () => {
    const seen: string[] = [];
    Object.assign(window, { seenModes: seen });
    new MutationObserver(() => {
      seen.push(document.documentElement.dataset.theme ?? "");
    }).observe(document, { attributes: true, subtree: true, attributeFilter: ["data-theme"] });
  };
  const cases = [
    { system: "light", stored: null },
    { system: "dark", stored: "light" },
  ] as const;
  for (const { system, stored } of cases) {
    const fresh = await browser.newContext({ baseURL, colorScheme: system });
    const visitor = await fresh.newPage();
    await visitor.addInitScript(watch);
    if (stored !== null) {
      await visitor.addInitScript(
        (choice) => localStorage.setItem("megooarti-theme", choice),
        stored,
      );
    }
    await visitor.goto("/login");
    await expect(visitor.getByLabel("User name")).toBeFocused(); // the page is alive
    await visitor.waitForTimeout(500);

    // Set once, to light, by the head: never dark again, not for a moment.
    const seen = await visitor.evaluate(
      () => (window as unknown as { seenModes: string[] }).seenModes,
    );
    expect(seen.filter((mode) => mode !== "light")).toEqual([]);
    expect(seen.length).toBeGreaterThan(0);
    await fresh.close();
  }
});

test("the sign-in screen meets WCAG 2.1 AA in both modes", async () => {
  await expectAccessibleInBothModes();
});

test("a wrong password is refused, and nothing typed is lost", async () => {
  await signIn("not-the-password");

  // Within the form: Next.js has an alert of its own, to announce a change of page.
  await expect(page.locator("form").getByRole("alert")).toContainText(
    "The user name or the password is not correct.",
  );
  await expect(page.getByLabel("User name")).toHaveValue("admin");
});

test("the first sign-in is done by keyboard alone, and leads to choosing a password", async () => {
  await page.reload();
  await expect(page.getByLabel("User name")).toBeFocused();
  await page.keyboard.type("admin");
  await page.keyboard.press("Tab");
  await page.keyboard.type(INITIAL_PASSWORD);
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/account\/password$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Choose a new password" }),
  ).toBeVisible();
  await expect(page).toHaveTitle("Change password · MegooArti");
  // Nothing else can be reached until it is done.
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await page.goto("/");
  await expect(page).toHaveURL(/\/account\/password$/);
});

test("the change-password screen meets WCAG 2.1 AA in both modes", async () => {
  await expectAccessibleInBothModes();
});

test("a password that is too short is refused at its field, without asking the server", async () => {
  await page.getByLabel("Current password").fill(INITIAL_PASSWORD);
  await page.getByLabel("New password", { exact: true }).fill("short");
  await page.getByLabel("New password, again").fill("short");
  await page.getByRole("button", { name: "Change password" }).click();

  await expect(page.getByLabel("New password", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  // The keyboard is at what is wrong, where a screen reader reads the field and why.
  await expect(page.getByLabel("New password", { exact: true })).toBeFocused();
  await expect(page.getByText("The password must be at least 8 characters long.")).toBeVisible();
});

test("choosing a password leads on to the repositories, of which there are none yet", async () => {
  await page.getByLabel("New password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("New password, again").fill(PASSWORD);
  await page.getByRole("button", { name: "Change password" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
  await expect(page).toHaveTitle("Repositories · MegooArti");
  await expect(page.getByRole("heading", { name: "No repositories" })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
  ).toHaveAttribute("aria-current", "page");
});

test("a repository made through the API is listed, and its address can be copied", async () => {
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const created = await page.request.post("/api/v1/repositories", {
    headers: { "X-CSRF-Token": session.csrf_token },
    data: { name: REPOSITORY, format: "raw", type: "hosted" },
  });
  expect(created.status()).toBe(201);

  await page.reload();
  const row = page.getByRole("row", { name: new RegExp(REPOSITORY) });

  await expect(row).toContainText("Hosted");
  await expect(row).toContainText("Online");
  const address = new URL(`/repository/${REPOSITORY}/`, page.url()).toString();
  await expect(row).toContainText(address);
  await row.getByRole("button", { name: `Copy ${address}` }).click();
  await expect(row.getByRole("status")).toHaveText("Copied");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(address);
});

test("the home screen meets WCAG 2.1 AA in both modes", async () => {
  await expectAccessibleInBothModes();
});

test("the mode that is chosen is shown at once, and kept after a reload", async () => {
  await page.getByRole("button", { name: /^Mode:/ }).click();
  await page.getByRole("menuitemradio", { name: "Light" }).click();

  expect(await shownMode()).toBe("light");
  await page.reload();
  await expect(page.getByRole("button", { name: "Mode: Light" })).toBeVisible();
  expect(await shownMode()).toBe("light"); // though the system is dark

  await page.getByRole("button", { name: "Mode: Light" }).click();
  await page.getByRole("menuitemradio", { name: "As the system" }).click();
  expect(await shownMode()).toBe("dark");
});

test("the skip link is the first stop of the keyboard, and leads past the navigation", async () => {
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
  await page.keyboard.press("Tab");

  const skip = page.getByRole("link", { name: "Skip to the content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
});

test("on a narrow screen the navigation is behind a button, and nothing overflows", async () => {
  await page.setViewportSize({ width: 375, height: 700 });
  const open = page.getByRole("button", { name: "Open the navigation" });

  await expect(open).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await open.click();
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close the navigation" }).click();

  // The table scrolls inside its panel: the page itself is never wider than the screen.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1280, height: 720 });
});

test("an address with nothing at it says so", async () => {
  const response = await page.goto("/no/such/screen");

  expect(response?.status()).toBe(404);
  await expect(page).toHaveTitle("There is nothing at this address · MegooArti");
  await expect(
    page.getByRole("heading", { name: "There is nothing at this address" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Go to the repositories" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("signing out ends the session, and signing in again returns to where one was going", async () => {
  await page.getByRole("button", { name: /^Account of/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();

  await expect(page).toHaveURL(/\/login$/);
  expect((await (await page.request.get("/api/v1/auth/session")).json()).authenticated).toBe(false);

  await page.goto("/account/password");
  await expect(page).toHaveURL(/\/login\?next=%2Faccount%2Fpassword$/);
  await signIn(PASSWORD);

  await expect(page).toHaveURL(/\/account\/password$/);
  await expect(page.getByRole("heading", { level: 1, name: "Change password" })).toBeVisible();
});

test("the sign-in screen cannot be made to send its visitor to another site", async () => {
  await page.getByRole("button", { name: /^Account of/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/login?next=https%3A%2F%2Fevil.example%2F");
  await signIn(PASSWORD);

  await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/");

  // Signed in, the sign-in screen goes on by itself. A browser drops a tab or a line
  // break from an address, so each of these is `//evil.example`: another site.
  for (const next of [
    "%2F%09%2Fevil.example%2F",
    "%2F%0A%2Fevil.example%2F",
    "%2F%0D%2Fevil.example",
  ]) {
    await page.goto(`/login?next=${next}`);
    await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
    expect(page.url()).toBe(new URL("/", page.url()).toString());
  }
});

test("through all of it, nothing was asked of another host, and the browser had no complaint", async ({
  baseURL,
}) => {
  const origin = new URL(baseURL ?? "").origin;
  const elsewhere = requested.filter(
    (address) => !address.startsWith(`${origin}/`) && !address.startsWith("data:"),
  );

  expect(requested.length).toBeGreaterThan(50);
  expect(elsewhere).toEqual([]);
  // The two complaints there should be: the browser itself logs the sign-in that was
  // refused (401) and the address that had nothing at it (404). Anything else, such as
  // something the content security policy stopped, fails this.
  const unexpected = complaints.filter((text) => !/status of 40[14]/.test(text));
  // In particular not of the site the return paths named. (Its name is in the query of
  // addresses that were asked for, which is as far as it got.)
  expect(requested.filter((address) => new URL(address).hostname.includes("evil"))).toEqual([]);
  expect(unexpected).toEqual([]);
});
