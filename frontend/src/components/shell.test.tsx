import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

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

  test("shows no area that has nothing in it", () => {
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    // Plan 9 has no administration screen yet, so the area is not there to be empty.
    expect(screen.queryByText("Administration")).toBeNull();
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
    expect(screen.queryByRole("button", { name: "Open the navigation" })).toBeNull();
    expect(screen.getByRole("button", { name: "Account of Ada Admin" })).toBeVisible();
  });
});

describe("the user menu", () => {
  test("says who is signed in, and leads to changing the password", async () => {
    const user = userEvent.setup();
    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    const menu = screen.getByRole("menu");

    expect(menu).toHaveTextContent("Signed in as");
    expect(menu).toHaveTextContent("admin");
    await expectAccessible();

    await user.click(within(menu).getByRole("menuitem", { name: "Change password" }));

    expect(navigation.router.push).toHaveBeenCalledWith("/account/password");
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

  test("stays signed in, and says nothing false, when signing out failed", async () => {
    const user = userEvent.setup();
    mockApi({ "POST /auth/logout": "network-failure" });
    const { client } = renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(leaveTo).not.toHaveBeenCalled();
    expect(client.getQueryData(["session"])).toEqual(ADMIN);
  });

  test("is a way to sign in for a visitor", () => {
    renderUi(<AppShell session={VISITOR}>Content</AppShell>, { session: VISITOR });

    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button", { name: /Account of/ })).toBeNull();
  });

  test("offers no change of password to whoever is already made to change it", async () => {
    const user = userEvent.setup();
    const pending: SessionInfo = { ...ADMIN, must_change_password: true };
    renderUi(
      <AppShell session={pending} bare>
        Content
      </AppShell>,
      { session: pending },
    );

    await user.click(screen.getByRole("button", { name: "Account of Ada Admin" }));

    expect(screen.queryByRole("menuitem", { name: "Change password" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
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
