import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { SearchBox } from "@/components/search-box";
import type { SessionInfo } from "@/lib/api/types";
import { SEARCH_KEY_STORAGE } from "@/lib/preferences";
import { STORAGE_KEY } from "@/lib/theme";
import { failure, mockApi, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi, VISITOR } from "@/test/render";

import { ChangePasswordScreen } from "./change-password";
import { PreferencesScreen } from "./preferences";
import { TokensScreen } from "./tokens";

const SECRET = "mga_Uw7SaBb3NAxy_RJ9arOrPGIK0LuZuSXGygzK9TKvMf4";
const token = (name: string, more: Record<string, unknown> = {}) => ({
  id: `id-of-${name}`,
  name,
  display_prefix: "mga_Uw7S",
  scopes: null,
  expires_at: null,
  created_at: "2026-10-01T08:00:00Z",
  last_used_at: null,
  ...more,
});
const page = (items: unknown[], total = items.length) => ({ items, total, limit: 50, offset: 0 });
const DAY = 24 * 3600 * 1000;

function tokens(more: Routes = {}, address = "/account/tokens") {
  const api = mockApi({
    "GET /me/tokens": { json: page([token("laptop")]) },
    "GET /content": {
      json: page([{ name: "releases", format: "maven", type: "hosted", online: true, url: "" }]),
    },
    "POST /me/tokens": (call) => ({
      status: 201,
      json: { ...token((call.body as { name: string }).name), token: SECRET },
    }),
    ...more,
  });
  navigation.at(address);
  return { ...renderUi(<TokensScreen />, { session: ADMIN }), ...api };
}

const create = () => screen.getByRole("button", { name: "Create token" });
const sent = (calls: { method: string; body: unknown }[]) =>
  calls.find((call) => call.method === "POST")?.body as {
    name: string;
    expires_at: string | null;
    scopes: string[] | null;
  };

describe("one's API tokens (A4)", () => {
  test("are listed, as one of the pages of the account", async () => {
    const { calls } = tokens();

    const table = await screen.findByRole("table", { name: "Your tokens" });

    expect(screen.getByRole("heading", { level: 1, name: "API tokens" })).toBeVisible();
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("laptop");
    expect(calls.map((call) => call.path)).toContain("/me/tokens?limit=50&offset=0");
    expect(
      within(screen.getByRole("navigation", { name: "Account" })).getByRole("link", {
        name: "API tokens",
      }),
    ).toHaveAttribute("aria-current", "page");
    await expectAccessible();
  });

  test("say so when there is none, and what went wrong when they cannot be shown", async () => {
    const first = tokens({ "GET /me/tokens": { json: page([]) } });
    expect(await screen.findByText("You have no token.")).toBeVisible();
    first.unmount();

    tokens({ "GET /me/tokens": failure(403, "forbidden", "No.") });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
  });

  test("come a page at a time when there are many", async () => {
    const { calls } = tokens(
      { "GET /me/tokens": { json: page([token("t-51")], 120) } },
      "/account/tokens?page=2",
    );

    const pages = await screen.findByRole("navigation", { name: "Pages" });

    expect(calls.map((call) => call.path)).toContain("/me/tokens?limit=50&offset=50");
    expect(pages).toHaveTextContent("Page 2 of 3");
    expect(within(pages).getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/account/tokens",
    );
    expect(within(pages).getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/account/tokens?page=3",
    );
  });

  test("another page of them has the keyboard, and a page past the last leads to the last", async () => {
    const { rerender } = tokens({ "GET /me/tokens": { json: page([token("t")], 60) } });
    await screen.findByRole("table", { name: "Your tokens" });

    navigation.at("/account/tokens?page=2");
    rerender(<TokensScreen />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Your tokens" })).toHaveFocus());

    // As after the only token of the last page is revoked: not "You have no token."
    navigation.at("/account/tokens?page=5");
    rerender(<TokensScreen />);
    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/account/tokens?page=2"),
    );
    expect(screen.queryByText("You have no token.")).toBeNull();
  });

  test("puts the keyboard at what is still wrong at every press", async () => {
    const user = userEvent.setup();
    tokens();
    await screen.findByRole("table", { name: "Your tokens" });
    await user.selectOptions(screen.getByLabelText("Lasts"), "date");

    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveFocus();
    await user.type(screen.getByLabelText("Name"), "x");
    await user.click(create());

    expect(screen.getByLabelText("Until the end of")).toHaveFocus();
  });

  test("a new one lasts ninety days and does what its owner may, unless told otherwise", async () => {
    const user = userEvent.setup();
    const { calls } = tokens();
    await screen.findByRole("table", { name: "Your tokens" });

    await user.type(screen.getByLabelText("Name"), "  ci build ");
    await user.click(create());

    await screen.findByRole("region", { name: "The token ci build is made" });
    const wanted = sent(calls);
    expect(wanted.name).toBe("ci build");
    expect(wanted.scopes).toBeNull();
    const lasts = new Date(wanted.expires_at ?? "").getTime() - Date.now();
    expect(lasts).toBeGreaterThan(89.9 * DAY);
    expect(lasts).toBeLessThan(90.1 * DAY);
  });

  test("can last until it is revoked, or until a day that is chosen", async () => {
    const user = userEvent.setup();
    const first = tokens();
    await user.type(await screen.findByLabelText("Name"), "forever");
    await user.selectOptions(screen.getByLabelText("Lasts"), "never");
    await user.click(create());
    await screen.findByRole("region", { name: "The token forever is made" });
    expect(sent(first.calls).expires_at).toBeNull();
    first.unmount();

    const second = tokens();
    await user.type(await screen.findByLabelText("Name"), "until");
    await user.selectOptions(screen.getByLabelText("Lasts"), "date");
    await user.click(create());
    // A day is needed, and is asked for where it is missing.
    expect(screen.getByLabelText("Until the end of")).toHaveAccessibleDescription("Choose a day.");
    expect(screen.getByLabelText("Until the end of")).toHaveFocus();
    expect(second.calls.some((call) => call.method === "POST")).toBe(false);

    await user.type(screen.getByLabelText("Until the end of"), "2031-05-17");
    await user.click(create());
    await screen.findByRole("region", { name: "The token until is made" });
    // The end of that day, where the person is.
    expect(sent(second.calls).expires_at).toBe(new Date("2031-05-17T23:59:59").toISOString());
  });

  test("can be limited to reading, or to what is chosen row by row", async () => {
    const user = userEvent.setup();
    const first = tokens();
    await user.type(await screen.findByLabelText("Name"), "reader");
    await user.click(screen.getByRole("radio", { name: "Only read" }));
    await user.click(create());
    await screen.findByRole("region", { name: "The token reader is made" });
    expect(sent(first.calls).scopes).toEqual(["repository:*:*:browse", "repository:*:*:read"]);
    first.unmount();

    const second = tokens();
    await user.type(await screen.findByLabelText("Name"), "deploy");
    await user.click(screen.getByRole("radio", { name: "Only what I choose" }));
    await user.click(create());
    // Nothing chosen is not a limit: it would be a token that may do nothing.
    expect(await screen.findByRole("alert")).toHaveTextContent("Add at least one permission");
    expect(second.calls.some((call) => call.method === "POST")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Add a permission" }));
    await user.selectOptions(screen.getByLabelText("Format"), "maven");
    await user.selectOptions(screen.getByLabelText("Repository"), "releases");
    await user.selectOptions(screen.getByLabelText("Action"), "add");
    await user.click(create());
    await screen.findByRole("region", { name: "The token deploy is made" });
    expect(sent(second.calls).scopes).toEqual(["repository:maven:releases:add"]);
  });

  test("needs a name, and a name no other token of one's own has", async () => {
    const user = userEvent.setup();
    const { calls } = tokens({
      "POST /me/tokens": failure(409, "conflict", "A token named laptop already exists."),
    });
    await screen.findByRole("table", { name: "Your tokens" });

    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Give it a name.");
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    await user.type(screen.getByLabelText("Name"), "laptop");
    await user.click(create());

    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A token named laptop already exists.",
      ),
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(screen.queryByRole("region", { name: /is made/ })).toBeNull();
  });

  test("says what the server refused at the field it is about, or whole", async () => {
    const user = userEvent.setup();
    const first = tokens({
      "POST /me/tokens": failure(422, "validation_error", "The request is not valid.", [
        { field: "body.expires_at", message: "The expiry must be in the future." },
      ]),
    });
    await user.type(await screen.findByLabelText("Name"), "past");
    await user.selectOptions(screen.getByLabelText("Lasts"), "date");
    await user.type(screen.getByLabelText("Until the end of"), "2001-01-01");
    await user.click(create());
    await waitFor(() =>
      expect(screen.getByLabelText("Until the end of")).toHaveAccessibleDescription(
        "The expiry must be in the future.",
      ),
    );
    first.unmount();

    tokens({ "POST /me/tokens": failure(500, "internal_error", "Oops.") });
    await user.type(await screen.findByLabelText("Name"), "x");
    await user.click(create());
    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
  });
});

describe("the secret of a new token (A5)", () => {
  test("is shown once, where the keyboard and a screen reader are taken, and can be copied", async () => {
    const user = userEvent.setup();
    tokens();
    await user.type(await screen.findByLabelText("Name"), "ci build");
    await user.click(create());

    const made = await screen.findByRole("region", { name: "The token ci build is made" });

    expect(within(made).getByText(SECRET)).toBeVisible();
    expect(within(made).getByRole("heading", { name: "The token ci build is made" })).toHaveFocus();
    expect(made).toHaveTextContent("This is the only time it is shown.");
    expect(screen.queryByRole("button", { name: "Create token" })).toBeNull(); // one thing at a time
    await user.click(within(made).getByRole("button", { name: "Copy the token" }));
    expect(await navigator.clipboard.readText()).toBe(SECRET);
    await expectAccessible();
  });

  test("is kept nowhere: not in what was fetched, not in the address, not in the browser", async () => {
    const user = userEvent.setup();
    const { client } = tokens();
    await user.type(await screen.findByLabelText("Name"), "ci build");
    await user.click(create());
    await screen.findByRole("region", { name: "The token ci build is made" });

    const held = () =>
      JSON.stringify([
        client
          .getQueryCache()
          .getAll()
          .map((query) => query.state.data),
        client
          .getMutationCache()
          .getAll()
          .map((mutation) => mutation.state.data),
        Object.entries(window.localStorage),
        Object.entries(window.sessionStorage),
        navigation.router.push.mock.calls,
        navigation.router.replace.mock.calls,
      ]);
    await waitFor(() => expect(held()).not.toContain(SECRET));

    await user.click(screen.getByRole("button", { name: "I have copied it" }));

    expect(document.body).not.toHaveTextContent(SECRET);
    expect(held()).not.toContain(SECRET);
    // The panel that had the keyboard is gone: it is at the tokens, where the new one is.
    expect(screen.getByRole("heading", { name: "Your tokens" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Create token" })).toBeVisible();
  });
});

describe("revoking a token of one's own", () => {
  test("asks first, then says it is revoked", async () => {
    const user = userEvent.setup();
    const { calls } = tokens({ "DELETE /me/tokens/id-of-laptop": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Revoke laptop" }));
    const dialog = screen.getByRole("alertdialog", { name: "Revoke the token laptop?" });
    expect(dialog).toHaveTextContent("Whatever uses it is refused from then on.");
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Revoke" }));

    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent(
        "Revoked the token laptop.",
      ),
    );
    expect(calls.filter((call) => call.method === "DELETE")).toHaveLength(1);
  });

  test("says why when it could not be", async () => {
    const user = userEvent.setup();
    tokens({ "DELETE /me/tokens/id-of-laptop": failure(404, "not_found", "No such token.") });

    await user.click(await screen.findByRole("button", { name: "Revoke laptop" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("This was not found.");
  });
});

describe("preferences (A11)", () => {
  function preferences(session: SessionInfo = ADMIN) {
    navigation.at("/account/preferences");
    return renderUi(
      <>
        <SearchBox />
        <PreferencesScreen />
      </>,
      { session },
    );
  }

  test("are the mode and the search key, taking effect as they are chosen", async () => {
    const user = userEvent.setup();
    preferences();

    expect(screen.getByRole("heading", { level: 1, name: "Preferences" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "As the system" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Light" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("light");
    await expectAccessible();
  });

  test("turning the search key off frees the key, there and then", async () => {
    const user = userEvent.setup();
    preferences();
    const box = screen.getByRole("searchbox", { name: "Search components" });
    const key = screen.getByRole("checkbox", { name: "Go to the search box with the / key" });
    expect(key).toBeChecked();
    expect(box).toHaveAttribute("aria-keyshortcuts", "/");

    await user.click(key);

    expect(window.localStorage.getItem(SEARCH_KEY_STORAGE)).toBe("off");
    expect(box).not.toHaveAttribute("aria-keyshortcuts");
    expect(box).toHaveAttribute("placeholder", "Search"); // it no longer says there is a key
    await user.click(screen.getByRole("heading", { level: 1 }));
    await user.keyboard("/");
    expect(box).not.toHaveFocus();

    await user.click(key);
    await user.click(screen.getByRole("heading", { level: 1 }));
    await user.keyboard("/");
    expect(box).toHaveFocus();
  });

  test("start from what was chosen before in this browser", () => {
    window.localStorage.setItem(SEARCH_KEY_STORAGE, "off");
    preferences();

    expect(
      screen.getByRole("checkbox", { name: "Go to the search box with the / key" }),
    ).not.toBeChecked();
  });

  test("are a visitor's too, who has no other page of an account", () => {
    preferences(VISITOR);

    expect(screen.getByRole("heading", { level: 1, name: "Preferences" })).toBeVisible();
    expect(screen.queryByRole("navigation", { name: "Account" })).toBeNull();
  });
});

describe("the password page", () => {
  test("is one of the pages of the account", () => {
    navigation.at("/account/password");
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    expect(
      within(screen.getByRole("navigation", { name: "Account" })).getByRole("link", {
        name: "Password",
      }),
    ).toHaveAttribute("aria-current", "page");
  });

  test("leads nowhere else for whoever must choose a password first", () => {
    navigation.at("/account/password");
    renderUi(<ChangePasswordScreen />, { session: { ...ADMIN, must_change_password: true } });

    expect(screen.queryByRole("navigation", { name: "Account" })).toBeNull();
  });
});
