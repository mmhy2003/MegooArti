import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

/**
 * The UI as a person meets it, from the first sign-in of a fresh installation on.
 * The tests follow each other: each starts where the one before it ended.
 */

const INITIAL_PASSWORD = process.env.MEGOOARTI_INITIAL_PASSWORD ?? "";
const PASSWORD = "chosen-in-the-browser-test";
const REPOSITORY = "browser-test-files";
const RELEASES = "browser-test-releases";
const GROUP = "browser-test-all";
const IMAGES = "browser-test-images";
// A name with what an address gives a meaning to: a space, a fragment, an escape.
const ODD = "a b#c%.txt";
const UPLOADS = "**/api/v1/content/*/upload";

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

/**
 * The same check in each mode, leaving the page in the dark one. `ready` waits for
 * what the screen fetches, so that it is the screen that is checked and not its loading.
 */
async function expectAccessibleInBothModes(ready: () => Promise<void> = async () => {}) {
  for (const mode of ["light", "dark"] as const) {
    await page.evaluate((chosen) => localStorage.setItem("megooarti-theme", chosen), mode);
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await ready();
    expect(await shownMode()).toBe(mode);
    await expectAccessible();
  }
}

/** What an administrator sets up through the API: its screens come with plan 10c. */
async function asAdministrator(method: "post" | "put", address: string, data: unknown) {
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const answer = await page.request[method](address, {
    headers: { "X-CSRF-Token": session.csrf_token },
    data,
  });
  expect(answer.ok(), `${method} ${address}: ${answer.status()}`).toBe(true);
}

const createRepository = (data: unknown) => asAdministrator("post", "/api/v1/repositories", data);
const setAnonymousAccess = (enabled: boolean) =>
  asAdministrator("put", "/api/v1/settings/anonymous-access", { enabled });

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
  await createRepository({ name: REPOSITORY, format: "raw", type: "hosted" });

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

test("a repository is entered from the list, and is empty to begin with", async () => {
  await page.getByRole("link", { name: REPOSITORY, exact: true }).click();

  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}$`));
  const title = page.getByRole("heading", { level: 1, name: REPOSITORY });
  await expect(title).toBeVisible();
  // A name tells capitals from small letters: it is not put in capitals as other titles are.
  await expect(title).toHaveCSS("text-transform", "none");
  await expect(page).toHaveTitle(`${REPOSITORY} · MegooArti`);
  await expect(page.getByRole("heading", { name: "Nothing here yet" })).toBeVisible();
  // Browsing a repository is being among the repositories.
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
  ).toHaveAttribute("aria-current", "page");
});

test("files are uploaded through the UI, which shows them going and says what was stored", async () => {
  await page.getByRole("link", { name: "Upload here" }).first().click();
  await expect(page).toHaveURL(new RegExp(`/upload/${REPOSITORY}$`));
  await expect(page).toHaveTitle(`Upload to ${REPOSITORY} · MegooArti`);
  const send = page.getByRole("button", { name: "Upload" });
  await expect(send).toBeDisabled(); // there is nothing to send yet

  await page.getByLabel("Directory").fill("docs/v1");
  await page.getByLabel("Files").setInputFiles([
    { name: "guide.md", mimeType: "text/markdown", buffer: Buffer.from("# Guide\n") },
    { name: ODD, mimeType: "text/plain", buffer: Buffer.from("odd name") },
  ]);
  // The answer is held back for a moment, so that what is shown meanwhile can be seen.
  await page.route(UPLOADS, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await route.continue();
  });
  // The list under the field says what is chosen. The browser's own words beside its
  // button ("No file chosen", always, as the field is emptied to take more) are not shown.
  await expect(
    page.getByRole("list", { name: "Chosen for Files" }).getByRole("listitem"),
  ).toHaveCount(2);
  await expect(page.getByLabel("Files", { exact: true })).toHaveCSS("color", "rgba(0, 0, 0, 0)");
  await send.click();

  await expect(page.getByRole("progressbar")).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  await expect(page.getByText("2 files stored")).toBeVisible();
  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
    `Stored 2 files in ${REPOSITORY}.`,
  );
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await page.unroute(UPLOADS);
});

test("a file with a name full of an address's own characters is found, and downloads as it was sent", async () => {
  await page.getByRole("link", { name: `docs/v1/${ODD}` }).click();
  const details = page.getByRole("region", { name: `Details of ${ODD}` });

  await expect(details.getByText("text/plain")).toBeVisible();
  await expect(details.getByText("8 B")).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`/browse/${REPOSITORY}/docs/v1`);
  expect(new URL(page.url()).searchParams.get("file")).toBe(ODD);
  // The folder is still there beside it, with the file marked.
  await expect(page.getByRole("link", { name: `File ${ODD}` })).toHaveAttribute(
    "aria-current",
    "true",
  );

  const address = await details.getByRole("link", { name: "Download" }).getAttribute("href");
  const downloaded = await page.request.get(address ?? "");
  expect(await downloaded.text()).toBe("odd name");

  await details.getByRole("button", { name: "Copy SHA-256" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^[0-9a-f]{64}$/);
});

test("a folder is reached through the ones above it by keyboard, and the path leads back", async () => {
  await page.goto(`/browse/${REPOSITORY}`);
  await page.getByRole("link", { name: "Folder docs" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}/docs$`));
  // The list the link was in is replaced. The keyboard is not dropped: it is at the
  // folder's place in the path, and the folder's entries follow from there.
  const path = page.getByRole("navigation", { name: "Path" });
  await expect(path.getByRole("link", { name: "docs", exact: true })).toBeFocused();
  await page.keyboard.press("Tab"); // Upload here
  await page.keyboard.press("Tab"); // Delete folder
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Folder v1" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(path.getByRole("link", { name: "v1", exact: true })).toBeFocused();

  await expect(
    page.getByRole("table", { name: "What is in docs/v1" }).getByRole("row"),
  ).toHaveCount(3);
  await page.getByRole("link", { name: "File guide.md" }).focus();
  await page.keyboard.press("Enter");
  const details = page.getByRole("region", { name: "Details of guide.md" });
  // The keyboard is taken to what was asked for.
  await expect(details.getByRole("heading", { name: "guide.md" })).toBeFocused();
  await expect(details.getByText("text/markdown")).toBeVisible();

  // The back button closes the details: the file that is chosen is in the address.
  await page.goBack();
  await expect(details).toHaveCount(0);
  // And the keyboard is back at the file whose details they were.
  await expect(page.getByRole("link", { name: "File guide.md" })).toBeFocused();
  await page.getByRole("navigation", { name: "Path" }).getByRole("link", { name: "docs" }).click();
  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}/docs$`));
  await expect(page.getByRole("link", { name: "Folder v1" })).toBeVisible();
});

test("the browse screen meets WCAG 2.1 AA in both modes", async () => {
  await page.goto(`/browse/${REPOSITORY}/docs/v1?file=guide.md`);
  await expectAccessibleInBothModes(async () => {
    await expect(page.getByText("text/markdown")).toBeVisible();
  });
});

test("the upload screen meets WCAG 2.1 AA in both modes", async () => {
  await createRepository({ name: RELEASES, format: "maven", type: "hosted" });
  await page.goto(`/upload/${RELEASES}`);
  await expectAccessibleInBothModes(async () => {
    await expect(page.getByLabel("Artifact", { exact: true })).toBeAttached();
  });
});

test("a Maven upload that is refused says why at its field, and goes through once it is put right", async () => {
  await page.getByLabel("Group", { exact: true }).fill("com.acme");
  await page.getByLabel("Artifact name").fill("app");
  await page.getByLabel("Version", { exact: true }).fill("2.0-SNAPSHOT");
  await page.getByLabel("Artifact", { exact: true }).setInputFiles({
    name: "build-output.jar",
    mimeType: "application/java-archive",
    buffer: Buffer.from("PK jar"),
  });
  await page.getByRole("button", { name: "Add another file" }).click();
  await page.getByLabel("Classifier").fill("sources");
  await page.getByLabel("File", { exact: true }).setInputFiles({
    name: "s.jar",
    mimeType: "application/java-archive",
    buffer: Buffer.from("PK sources"),
  });
  await page.getByRole("button", { name: "Upload" }).click();

  const version = page.getByLabel("Version", { exact: true });
  await expect(version).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByText("A snapshot is deployed by a build")).toBeVisible();
  // The keyboard is at what is wrong, where a screen reader reads the field and why.
  await expect(version).toBeFocused();

  // What was chosen is still chosen: only the version is typed again.
  await version.fill("1.0");
  await page.getByRole("button", { name: "Upload" }).click();

  await expect(page.getByText("3 files stored")).toBeVisible();
  for (const stored of ["app-1.0.jar", "app-1.0-sources.jar", "app-1.0.pom"]) {
    await expect(page.getByRole("link", { name: `com/acme/app/1.0/${stored}` })).toBeVisible();
  }
});

test("a component's page says what it is and how to use it, ready to copy", async () => {
  await page.getByRole("link", { name: "com/acme/app/1.0/app-1.0.jar" }).click();
  const details = page.getByRole("region", { name: "Details of app-1.0.jar" });
  await details.getByRole("link", { name: "com.acme : app : 1.0" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "app 1.0" })).toBeVisible();
  await expect(page).toHaveTitle(`${RELEASES} · MegooArti`);
  await expect(page.getByRole("table", { name: "Files" }).getByRole("row")).toHaveCount(4);
  await expect(page.getByText('implementation("com.acme:app:1.0")')).toBeVisible();

  await page.getByRole("button", { name: "Copy Maven" }).click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain("<groupId>com.acme</groupId>");
  expect(copied).toContain("<artifactId>app</artifactId>");
  expect(copied).toContain("<version>1.0</version>");
});

test("the component screen meets WCAG 2.1 AA in both modes", async () => {
  await expectAccessibleInBothModes(async () => {
    await expect(page.getByText('implementation("com.acme:app:1.0")')).toBeVisible();
  });
});

test("search is one key away on every screen, and finds by words and by a file's checksum", async () => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
  await page.keyboard.press("/");
  await expect(page.getByRole("searchbox", { name: "Search components" })).toBeFocused();
  await page.keyboard.type("app");
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/search\?q=app$/);
  await expect(page).toHaveTitle("Search · MegooArti");
  await expect(page.getByText("1 component found.")).toBeVisible();
  const results = page.getByRole("table", { name: "Results" });
  await expect(results.getByRole("row").nth(1)).toContainText("com.acme");

  // A checksum, of any of the four kinds, is one field: here the SHA-1 of the jar.
  const asset = await page.request.get(
    `/api/v1/content/${RELEASES}/asset?path=com/acme/app/1.0/app-1.0.jar`,
  );
  const { sha1 } = await asset.json();
  const form = page.getByRole("search", { name: "Search", exact: true });
  await form.getByLabel("Words").fill("");
  await form.getByLabel("Checksum of a file").fill(sha1);
  await form.getByRole("button", { name: "Search" }).click();
  await expect(page).toHaveURL(new RegExp(`/search\\?checksum=${sha1}$`));
  await expect(results.getByRole("link", { name: "app", exact: true })).toBeVisible();

  await form.getByLabel("Checksum of a file").fill("");
  await form.getByLabel("Words").fill("no-such-thing-anywhere");
  await form.getByLabel("Words").press("Enter");
  await expect(page.getByRole("heading", { name: "Nothing found" })).toBeVisible();

  // What was searched for is in the address: the back button returns to the search before.
  await page.goBack();
  await expect(form.getByLabel("Checksum of a file")).toHaveValue(sha1);
  await results.getByRole("link", { name: "app", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "app 1.0" })).toBeVisible();
});

test("the search screen meets WCAG 2.1 AA in both modes", async () => {
  await page.goto("/search?q=app");
  await expectAccessibleInBothModes(async () => {
    await expect(page.getByText("1 component found.")).toBeVisible();
  });
});

test("many results come a page at a time, and the keyboard follows to the next page", async () => {
  // More components than one page holds: each file of a raw repository is one.
  const session = await (await page.request.get("/api/v1/auth/session")).json();
  const headers = { "X-CSRF-Token": session.csrf_token };
  for (let number = 1; number <= 51; number += 1) {
    const stored = await page.request.post(`/api/v1/content/${REPOSITORY}/upload`, {
      headers,
      multipart: {
        directory: "many",
        file: { name: `n-${number}.txt`, mimeType: "text/plain", buffer: Buffer.from("x") },
      },
    });
    expect(stored.status()).toBe(201);
  }

  await page.goto(`/search?repository=${REPOSITORY}`);
  const pages = page.getByRole("navigation", { name: "Pages" });
  await expect(pages).toContainText("Page 1 of 2");
  await expect(page.getByRole("table", { name: "Results" }).getByRole("row")).toHaveCount(51);
  await pages.getByRole("link", { name: "Next" }).focus();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/[?&]page=2$/);
  await expect(pages).toContainText("Page 2 of 2");
  // The link that was followed went while the page loaded. The keyboard is at the line
  // that says what was found, and the results follow from there.
  await expect(page.getByText(/^\d+ components found\.$/)).toBeFocused();
  await expect(pages.getByRole("link", { name: "Next" })).toHaveCount(0);

  // Gone again, so that what follows finds the repository as it was.
  const removed = await page.request.delete(`/api/v1/content/${REPOSITORY}/tree?path=many`, {
    headers,
  });
  expect(removed.ok()).toBe(true);
  expect((await removed.json()).deleted).toBe(51);
});

test("on a narrow screen a file's details come under its folder, and nothing overflows", async () => {
  await page.setViewportSize({ width: 375, height: 700 });
  await page.goto(`/browse/${RELEASES}/com/acme/app/1.0?file=app-1.0-sources.jar`);
  const details = page.getByRole("region", { name: "Details of app-1.0-sources.jar" });
  await expect(details.getByText("application/java-archive")).toBeVisible();

  const table = page.getByRole("table", { name: "What is in com/acme/app/1.0" });
  const [above, below] = [await table.boundingBox(), await details.boundingBox()];
  expect(below?.y ?? 0).toBeGreaterThan((above?.y ?? 0) + (above?.height ?? 0) - 1);
  // A checksum is 128 characters without a space in it: it breaks, and widens nothing.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);

  // The search box is in the navigation, where there is room for it.
  await expect(page.getByRole("searchbox", { name: "Search components" })).toHaveCount(0);
  await page.getByRole("button", { name: "Open the navigation" }).click();
  await expect(page.getByRole("searchbox", { name: "Search components" })).toBeVisible();
  await page.getByRole("button", { name: "Close the navigation" }).click();
  await page.setViewportSize({ width: 1280, height: 720 });
});

test("a visitor who may only look is offered a download, and nothing that changes anything", async ({
  browser,
  baseURL,
}) => {
  await setAnonymousAccess(true);
  const fresh = await browser.newContext({ baseURL, colorScheme: "dark" });
  const visitor = await fresh.newPage();
  await visitor.goto(`/browse/${REPOSITORY}/docs/v1?file=guide.md`);
  const details = visitor.getByRole("region", { name: "Details of guide.md" });

  await expect(details.getByText("text/markdown")).toBeVisible();
  await expect(details.getByRole("link", { name: "Download" })).toBeVisible();
  await expect(details.getByRole("button", { name: "Delete" })).toHaveCount(0);
  await expect(visitor.getByRole("button", { name: "Delete folder" })).toHaveCount(0);
  await expect(visitor.getByRole("link", { name: "Upload here" })).toHaveCount(0);
  await expect(visitor.getByRole("link", { name: "Sign in" })).toBeVisible();
  const navigation = visitor.getByRole("navigation", { name: "Main" });
  await expect(navigation.getByRole("link", { name: "Search" })).toBeVisible();
  await expect(navigation.getByRole("link", { name: "Upload" })).toHaveCount(0);

  // The address of the form can be typed all the same. The screen says no, as the API would.
  await visitor.goto(`/upload/${REPOSITORY}`);
  await expect(
    visitor.getByText("You do not have permission to add to this repository."),
  ).toBeVisible();
  await expect(visitor.getByRole("button", { name: "Upload" })).toHaveCount(0);
  await visitor.goto("/upload");
  await expect(visitor.getByRole("heading", { name: "Nowhere to upload to" })).toBeVisible();

  await setAnonymousAccess(false);
  await visitor.goto(`/browse/${REPOSITORY}`);
  await expect(visitor).toHaveURL(/\/login\?next=/);
  await fresh.close();
});

test("a group shows who is behind it, and takes no upload", async () => {
  await createRepository({
    name: GROUP,
    format: "raw",
    type: "group",
    group: { members: [REPOSITORY] },
  });
  await page.goto(`/browse/${GROUP}`);

  await expect(page.getByRole("heading", { name: "Members" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Upload here" })).toHaveCount(0);
  // Nor a search in it: search looks in what holds components, and a group holds none.
  await expect(page.getByRole("link", { name: "Search this repository" })).toHaveCount(0);
  await page.goto(`/upload/${GROUP}`);
  await expect(page.getByText("Only a hosted repository takes an upload.")).toBeVisible();

  await page.goto(`/browse/${GROUP}`);
  await page.getByRole("main").getByRole("link", { name: REPOSITORY, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}$`));
  await expect(page.getByRole("link", { name: "Folder docs" })).toBeVisible();
});

test("a Docker repository says how an image gets there, and has no form", async () => {
  await createRepository({ name: IMAGES, format: "docker", type: "hosted" });
  await page.goto(`/upload/${IMAGES}`);

  await expect(page.getByRole("heading", { level: 1, name: `Upload to ${IMAGES}` })).toBeVisible();
  await expect(page.getByText("An image is pushed with a container client")).toBeVisible();
  await expect(page.getByRole("button", { name: "Upload" })).toHaveCount(0);
  // Every text on the page is one: a text that is missing shows as its own key.
  await expect(page.getByRole("main")).not.toContainText("upload.");
  await page.goto("/upload");
  await expect(page.getByRole("main").getByRole("link", { name: IMAGES })).toHaveCount(0);
});

test("a file is deleted only after asking, and the screen says that it is gone", async () => {
  await page.goto(`/browse/${REPOSITORY}/docs/v1?file=guide.md`);
  const details = page.getByRole("region", { name: "Details of guide.md" });
  const opener = details.getByRole("button", { name: "Delete" });
  await opener.click();
  const dialog = page.getByRole("alertdialog", { name: "Delete guide.md?" });

  // Asked, and answered no: nothing happens, and the keyboard is back where it was.
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await expect(page.getByRole("link", { name: "File guide.md" })).toBeVisible();

  await opener.click();
  await dialog.getByRole("button", { name: "Delete" }).click();

  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
    "Deleted guide.md.",
  );
  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}/docs/v1$`));
  await expect(page.getByRole("link", { name: "File guide.md" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: `File ${ODD}` })).toBeVisible();
  // The button that was pressed went with the file: the keyboard is at the folder.
  await expect(
    page.getByRole("navigation", { name: "Path" }).getByRole("link", { name: "v1", exact: true }),
  ).toBeFocused();
});

test("a folder is deleted only by whoever types its name", async () => {
  await page.getByRole("button", { name: "Delete folder" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Delete the folder v1?" });
  const confirm = dialog.getByRole("button", { name: "Delete folder" });

  await expect(dialog).toContainText("Every file under docs/v1 is deleted.");
  await expect(confirm).toBeDisabled();
  // What is to be typed is shown as it is to be typed.
  await expect(dialog.getByText("Type v1 to go on")).toHaveCSS("text-transform", "none");
  await expect(dialog.getByRole("heading")).toHaveCSS("text-transform", "none");
  await dialog.getByLabel("Type v1 to go on").fill("V1");
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("Type v1 to go on").fill("v1");
  await confirm.click();

  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
    "Deleted 1 file under v1.",
  );
  // The folder above held nothing else, so it went too: the screen says so, and leads on.
  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}/docs$`));
  await expect(page.getByRole("heading", { name: "No such folder" })).toBeVisible();
  await page.getByRole("link", { name: `Go to the top of ${REPOSITORY}` }).click();
  await expect(page.getByRole("heading", { name: "Nothing here yet" })).toBeVisible();
});

test("a version is deleted from its page, and is then not found", async () => {
  await page.goto("/search?q=app");
  await page
    .getByRole("table", { name: "Results" })
    .getByRole("link", { name: "app", exact: true })
    .click();
  await page.getByRole("button", { name: "Delete this version" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Delete app 1.0?" });
  await expect(dialog).toContainText("Its 3 files are deleted");
  await dialog.getByRole("button", { name: "Delete this version" }).click();

  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
    "Deleted app 1.0.",
  );
  await expect(page).toHaveURL(new RegExp(`/browse/${RELEASES}$`));
  await page.goto("/search?q=app");
  await expect(page.getByRole("heading", { name: "Nothing found" })).toBeVisible();
});

test("an upload refused because the session was replaced in another tab goes through at the next try", async () => {
  await page.goto(`/upload/${REPOSITORY}`);
  await page.getByLabel("Files", { exact: true }).setInputFiles({
    name: "later.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("later"),
  });

  // In another tab: signed out, and in again. The session, and its token, are new.
  const other = await context.newPage();
  await other.goto("/");
  await other.getByRole("button", { name: /^Account of/ }).click();
  await other.getByRole("menuitem", { name: "Sign out" }).click();
  await other.getByLabel("User name").fill("admin");
  await other.getByLabel("Password").fill(PASSWORD);
  await other.getByRole("button", { name: "Sign in" }).click();
  await expect(other.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
  await other.close();

  // This page still has the old token: the server refuses the upload, and says why.
  const send = page.getByRole("button", { name: "Upload" });
  const said = page.waitForResponse("**/api/v1/auth/session");
  await send.click();
  await expect(page.locator("form").getByRole("alert")).toBeVisible();
  // The refusal made the page ask who is signed in. With that answer, the same press works.
  await said;
  await send.click();
  await expect(page.getByText("1 file stored")).toBeVisible();
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
  // The complaints there should be: the browser itself logs the sign-in that was refused
  // (401), the upload with the token of a session that had been replaced (403), the
  // address and the folder that had nothing at them (404), and the upload of a snapshot
  // (422). Anything else, such as something the content security policy stopped, fails this.
  const unexpected = complaints.filter((text) => !/status of (401|403|404|422)/.test(text));
  // In particular not of the site the return paths named. (Its name is in the query of
  // addresses that were asked for, which is as far as it got.)
  expect(requested.filter((address) => new URL(address).hostname.includes("evil"))).toEqual([]);
  expect(unexpected).toEqual([]);
});
