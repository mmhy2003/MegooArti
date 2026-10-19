import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { useQuery } from "@tanstack/react-query";

import { api, setCsrfToken } from "@/lib/api/client";
import type { SessionInfo } from "@/lib/api/types";
import { leaveTo } from "@/lib/browser";
import { STORAGE_KEY } from "@/lib/theme";
import { failure, mockApi } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, NOBODY, renderUi, VISITOR } from "@/test/render";
import { setSystemMode } from "@/test/setup";

import { AppShell } from "./app-shell";
import { SessionGate } from "./session-gate";
import { ThemeSwitch } from "./theme-switch";

const shownMode = () => document.documentElement.getAttribute("data-theme");

describe("the shell", () => {
  test("has a way past the navigation as the first thing focus reaches (UI-6)", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    await user.tab();

    const skip = screen.getByRole("link", { name: "Skip to the content" });
    expect(skip).toHaveFocus();
    expect(skip).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("main")).toHaveTextContent("Content");
  });

  test("names its parts, and marks where the visitor is", async () => {
    navigation.at("/");
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    const [wide] = screen.getAllByRole("navigation", { name: "Main" });
    const current = within(wide as HTMLElement).getByRole("link", { name: "Repositories" });

    expect(current).toHaveAttribute("aria-current", "page");
    expect(within(wide as HTMLElement).getByText("Browse")).toBeVisible();
    expect(screen.getByRole("banner")).toBeVisible();
    await expectAccessible();
  });

  test("leads to the repositories, to search and to upload", () => {
    navigation.at("/browse/releases/com");
    const uploader: SessionInfo = { ...ADMIN, permissions: ["repository:*:*:*"] };
    renderUi(<AppShell session={uploader}>Content</AppShell>, { session: uploader });
    const [wide] = screen.getAllByRole("navigation", { name: "Main" });
    const links = within(wide as HTMLElement).getAllByRole("link");

    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Repositories", "/"],
      ["Search", "/search"],
      ["Upload", "/upload"],
    ]);
    // Browsing a repository is being among the repositories.
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null, null]);
  });

  test("leads an administrator to everything there is to administer", () => {
    navigation.at("/admin/users/0190-aa");
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
    const [wide] = screen.getAllByRole("navigation", { name: "Main" });
    const links = within(wide as HTMLElement)
      .getAllByRole("link")
      .slice(3);

    expect(within(wide as HTMLElement).getByText("Administration")).toBeVisible();
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Users", "/admin/users"],
      ["Roles", "/admin/roles"],
      ["Anonymous access", "/admin/anonymous-access"],
      ["Authentication", "/admin/authentication"],
      // Not "Repositories": that is the list for browsing, in the same navigation (R14).
      ["Manage repositories", "/admin/repositories"],
      ["Blob stores", "/admin/blob-stores"],
      ["System", "/admin/system"],
    ]);
    // One user's page is among the users.
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([
      "page",
      null,
      null,
      null,
      null,
      null,
      null,
    ]);
  });

  test("has the navigation in a row of its own, which wraps where it does not fit", () => {
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
    const [wide] = screen.getAllByRole("navigation", { name: "Main" });

    // Not beside the search box, where an administrator's items ran under it.
    expect(wide?.querySelector('[role="search"]')).toBeNull();
    expect(wide?.closest("header > div")).toBeNull();
    expect(within(wide as HTMLElement).getAllByRole("list")[0]).toHaveClass("lg:flex-wrap");
  });

  test("has the search box in its header, and in the navigation of a narrow window", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
    const boxes = within(screen.getByRole("banner")).getAllByRole("search", {
      name: "Search components",
      hidden: true,
    });

    expect(boxes).toHaveLength(2); // one is shown, by the width of the window
    expect(boxes[0]).toHaveClass("hidden", "md:block");
    expect(boxes[1]).toHaveClass("md:hidden");
    expect(boxes[1]?.closest("#narrow-navigation")).not.toBeNull();

    await user.type(within(boxes[0] as HTMLElement).getByRole("searchbox"), "guava{Enter}");
    expect(navigation.router.push).toHaveBeenCalledWith("/search?q=guava");
  });

  test("shows no area that has nothing in it", () => {
    renderUi(<AppShell session={VISITOR}>Content</AppShell>, { session: VISITOR });

    // A visitor administers nothing, so the area is not there to be empty.
    expect(screen.queryByText("Administration")).toBeNull();
    expect(screen.getAllByText("Browse")[0]).toBeVisible();
  });

  test("opens its navigation from a button where the window is narrow (UI-3)", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
    const button = screen.getByRole("button", { name: "Open the navigation" });
    const narrow = document.getElementById("narrow-navigation");

    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(narrow).not.toBeVisible();

    await user.click(button);

    expect(screen.getByRole("button", { name: "Close the navigation" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(narrow).toBeVisible();

    await user.click(within(narrow as HTMLElement).getByRole("link", { name: "Repositories" }));

    expect(narrow).not.toBeVisible(); // following a link closes it
  });

  test("has no navigation for whoever must change their password first", () => {
    const pending: SessionInfo = { ...ADMIN, must_change_password: true };
    renderUi(
      <AppShell session={pending} bare>
        Content
      </AppShell>,
      { session: pending },
    );

    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("search")).toBeNull(); // nothing can be searched for yet
    expect(screen.queryByRole("button", { name: "Open the navigation" })).toBeNull();
    expect(screen.getByRole("button", { name: "Account of Ada Admin" })).toBeVisible();
  });
});

describe("the user menu", () => {
  test("says who is signed in, and leads to their account", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    const menu = screen.getByRole("menu");

    expect(menu).toHaveTextContent("Signed in as");
    expect(menu).toHaveTextContent("admin");
    await expectAccessible();

    await user.click(within(menu).getByRole("menuitem", { name: "Account" }));

    expect(navigation.router.push).toHaveBeenCalledWith("/account/tokens");
  });

  test("signs out, forgets what was fetched for that person, and starts afresh at home", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi({ "POST /auth/logout": { status: 204 } });
    const { client } = renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
    client.setQueryData(["content", "repositories"], { items: [{ name: "secret" }] });

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(leaveTo).toHaveBeenCalledWith("/"));
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual(["POST /auth/logout"]);
    expect(client.getQueryData(["content", "repositories"])).toBeUndefined();
  });

  test("says so when signing out failed: nobody should think they are signed out", async () => {
    const user = userEvent.setup();
    mockApi({ "POST /auth/logout": "network-failure" });
    const { client } = renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You are still signed in");
    expect(alert).toHaveTextContent("The server could not be reached.");
    expect(leaveTo).not.toHaveBeenCalled();
    expect(client.getQueryData(["session"])).toEqual(ADMIN);
  });

  test("signs out at the second try when the session was replaced in another tab", async () => {
    const user = userEvent.setup();
    // The token this page holds is that of a session that is gone. Asking for the
    // session again brings the new one's.
    const renewed = { ...ADMIN, csrf_token: "token-of-the-new-session" };
    const { calls } = mockApi({
      "GET /auth/session": { json: renewed },
      "POST /auth/logout": (call) =>
        call.headers["X-CSRF-Token"] === "token-of-the-new-session"
          ? { status: 204 }
          : failure(403, "csrf_failed", "The CSRF token is missing or wrong."),
    });
    renderUi(
      <SessionGate shell>
        <p>The screen</p>
      </SessionGate>,
      { session: ADMIN },
    );
    setCsrfToken("token-of-the-old-session");

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You are still signed in");
    await waitFor(() => expect(calls.some((call) => call.path === "/auth/session")).toBe(true));
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(leaveTo).toHaveBeenCalledWith("/"));
  });

  test("is a way to sign in for a visitor", () => {
    renderUi(<AppShell session={VISITOR}>Content</AppShell>, { session: VISITOR });

    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button", { name: /Account of/ })).toBeNull();
  });

  test("offers no way to the account to whoever must choose a password first", async () => {
    const user = userEvent.setup();
    const pending: SessionInfo = { ...ADMIN, must_change_password: true };
    renderUi(
      <AppShell session={pending} bare>
        Content
      </AppShell>,
      { session: pending },
    );

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));

    expect(screen.queryByRole("menuitem", { name: "Account" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
    // Nor to the preferences, from the mode menu: no other screen can be reached.
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: /^Mode:/ }));
    expect(screen.getByRole("menuitemradio", { name: "Dark" })).toBeVisible();
    expect(screen.queryByRole("menuitem", { name: "More preferences" })).toBeNull();
  });
});

describe("the mode menu", () => {
  test("leads to the other preferences, for a visitor as for anybody (A11)", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={VISITOR}>Content</AppShell>, { session: VISITOR });

    await user.click(screen.getByRole("button", { name: /^Mode:/ }));
    await user.click(screen.getByRole("menuitem", { name: "More preferences" }));

    expect(navigation.router.push).toHaveBeenCalledWith("/account/preferences");
  });
});

describe("the mode switch (UI-10)", () => {
  test("follows the system until a choice is made", async () => {
    setSystemMode("light");
    renderUi(<ThemeSwitch />);

    await waitFor(() => expect(shownMode()).toBe("light"));
    expect(screen.getByRole("button", { name: "Mode: As the system" })).toBeVisible();
  });

  test("shows the choice at once and keeps it in this browser", async () => {
    const user = userEvent.setup();
    setSystemMode("dark");
    renderUi(<ThemeSwitch />);

    await user.click(screen.getByRole("button", { name: "Mode: As the system" }));
    expect(screen.getByRole("menuitemradio", { name: "As the system" })).toBeChecked();
    await user.click(screen.getByRole("menuitemradio", { name: "Light" }));

    expect(shownMode()).toBe("light");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("button", { name: "Mode: Light" })).toBeVisible();
  });

  test("starts from what was chosen before", async () => {
    window.localStorage.setItem(STORAGE_KEY, "light");
    setSystemMode("dark");
    renderUi(<ThemeSwitch />);

    await waitFor(() => expect(shownMode()).toBe("light"));
    expect(screen.getByRole("button", { name: "Mode: Light" })).toBeVisible();
  });
});

describe("the gate before every screen", () => {
  const gated = (shell: boolean) => (
    <SessionGate shell={shell}>
      <p>The screen</p>
    </SessionGate>
  );

  test("says it is loading until the session is known, then shows the screen in the shell", async () => {
    mockApi({ "GET /auth/session": { json: ADMIN } });
    renderUi(gated(true));

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(screen.queryByText("The screen")).toBeNull();

    expect(await screen.findByText("The screen")).toBeVisible();
    expect(screen.getByRole("banner")).toBeVisible();
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  test("sends whoever is not signed in to sign in, and remembers where they were going", async () => {
    mockApi({ "GET /auth/session": { json: NOBODY } });
    navigation.at("/search?q=commons");
    renderUi(gated(true));

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/login?next=%2Fsearch%3Fq%3Dcommons"),
    );
    expect(screen.queryByText("The screen")).toBeNull();
  });

  test("lets a visitor browse where anonymous access is on", async () => {
    mockApi({ "GET /auth/session": { json: VISITOR } });
    renderUi(gated(true));

    expect(await screen.findByText("The screen")).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeVisible();
  });

  test("sends whoever must change their password there, from anywhere", async () => {
    mockApi({ "GET /auth/session": { json: { ...ADMIN, must_change_password: true } } });
    navigation.at("/");
    renderUi(gated(true));

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/account/password"),
    );
    expect(screen.queryByText("The screen")).toBeNull();
  });

  test("sends whoever is signed in on from the sign-in screen, to one of our own screens only", async () => {
    mockApi({ "GET /auth/session": { json: ADMIN } });
    navigation.at("/login?next=https%3A%2F%2Fevil.example%2F");
    renderUi(gated(false));

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/"));
    expect(screen.queryByText("The screen")).toBeNull();
  });

  test("shows the sign-in screen without the shell", async () => {
    mockApi({ "GET /auth/session": { json: NOBODY } });
    navigation.at("/login");
    renderUi(gated(false));

    expect(await screen.findByText("The screen")).toBeVisible();
    expect(screen.queryByRole("banner")).toBeNull();
  });

  test("says so when the session cannot be asked for, and tries again when asked", async () => {
    const user = userEvent.setup();
    let working = false;
    mockApi({
      "GET /auth/session": () =>
        working ? { json: ADMIN } : failure(503, "not_ready", "The database is not reachable."),
    });
    renderUi(gated(true));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The database is not reachable.");
    expect(alert).toHaveTextContent("Request req-123");
    working = true;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("The screen")).toBeVisible();
  });

  test("keeps the session's CSRF token for what comes after", async () => {
    const { calls } = mockApi({
      "GET /auth/session": { json: ADMIN },
      "POST /auth/logout": { status: 204 },
    });
    const user = userEvent.setup();
    renderUi(gated(true));

    await user.click(await screen.findByRole("button", { name: "Account of Ada Admin" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const signOut = calls.find((call) => call.method === "POST");
    expect(signOut?.headers["X-CSRF-Token"]).toBe("csrf-of-this-session");
  });
});

describe("a session that changed under the page", () => {
  /** A screen that asks the API for something, as every screen of plan 10 will. */
  function Asking() {
    const things = useQuery({ queryKey: ["things"], queryFn: () => api.get("/things") });
    return <p>{things.isError ? "Refused" : "The screen"}</p>;
  }

  const gated = (
    <SessionGate shell>
      <Asking />
    </SessionGate>
  );

  test("a request refused with 401 means it ended: the visitor is asked to sign in again", async () => {
    let ended = false;
    mockApi({
      "GET /auth/session": () => ({ json: ended ? NOBODY : ADMIN }),
      "GET /things": () => {
        ended = true;
        return failure(401, "unauthorized", "Authentication is required.");
      },
    });
    navigation.at("/things");
    renderUi(gated);

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/login?next=%2Fthings"),
    );
  });

  test("a request refused because the password must be changed leads there", async () => {
    let told = false;
    mockApi({
      "GET /auth/session": () => ({ json: { ...ADMIN, must_change_password: told } }),
      "GET /things": () => {
        told = true;
        return failure(403, "password_change_required", "Change your password first.");
      },
    });
    renderUi(gated);

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/account/password"),
    );
  });

  test("a refusal that says nothing of the session leaves it alone", async () => {
    const { calls } = mockApi({
      "GET /auth/session": { json: ADMIN },
      "GET /things": failure(403, "forbidden", "You do not have permission to do this."),
    });
    renderUi(gated);

    expect(await screen.findByText("Refused")).toBeVisible();
    expect(calls.filter((call) => call.path === "/auth/session")).toHaveLength(1);
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  test("a 401 for the session itself is said once, and not asked for again and again", async () => {
    // What a proxy with a sign-in of its own answers, once its own session has ended.
    const { calls } = mockApi({
      "GET /auth/session": failure(401, "unauthorized", "Sign in at the proxy."),
    });
    renderUi(gated);

    expect(await screen.findByRole("alert")).toHaveTextContent("You are not signed in");
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(calls).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});
