import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { AnonymousAccessScreen } from "./anonymous-access";
import { NewRoleScreen, RoleScreen, RolesScreen } from "./roles";
import { NewUserScreen, UserScreen } from "./user";
import { UsersScreen } from "./users";

const page = (items: unknown[], total = items.length) => ({ items, total, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });

const person = (username: string, more: Record<string, unknown> = {}) => ({
  id: `id-of-${username}`,
  username,
  display_name: `${username[0]?.toUpperCase()}${username.slice(1)} Example`,
  email: null,
  status: "active",
  must_change_password: false,
  builtin: false,
  roles: [],
  created_at: "2026-10-01T08:00:00Z",
  last_login_at: null,
  ...more,
});
const ALICE = person("alice", { roles: ["deployers"], email: "alice@example.com" });
const ANONYMOUS = person("anonymous", { builtin: true, roles: ["anonymous"] });
// The session's own user, as the users API has it.
const SELF = person("admin", { id: ADMIN.user?.id, builtin: true, roles: ["admin"] });

const role = (name: string, more: Record<string, unknown> = {}) => ({
  name,
  description: "",
  builtin: false,
  permissions: [],
  roles: [],
  ...more,
});
const ROLES = [
  role("admin", { builtin: true, description: "Full access to everything.", permissions: ["*"] }),
  role("anonymous", {
    builtin: true,
    description: "What requests without credentials may do.",
    permissions: ["repository:*:*:browse", "repository:*:*:read"],
  }),
  role("deployers", {
    description: "May deploy releases",
    permissions: ["repository:maven:releases:add", "admin:audit:read"],
    roles: ["anonymous"],
  }),
];
const DEPLOYERS = ROLES[2];
const REPOSITORIES = page([
  { name: "releases", format: "maven", type: "hosted", online: true, url: "" },
]);

const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

describe("the users (A13)", () => {
  function users(more: Routes = {}, session = ADMIN, address = "/admin/users") {
    const api = mockApi({ "GET /users": { json: page([SELF, ALICE, ANONYMOUS]) }, ...more });
    navigation.at(address);
    return { ...renderUi(<UsersScreen />, { session }), ...api };
  }

  test("are listed with their roles and whether they can sign in", async () => {
    const { calls } = users({
      "GET /users": {
        json: page([
          SELF,
          person("bob", { status: "disabled", must_change_password: true }),
          ALICE,
        ]),
      },
    });

    const table = await screen.findByRole("table", { name: "Users" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(calls[0]?.path).toBe("/users?limit=50&offset=0");
    expect(within(rows[2] as HTMLElement).getByRole("link", { name: "alice" })).toHaveAttribute(
      "href",
      "/admin/users/id-of-alice",
    );
    expect(rows[2]).toHaveTextContent("Alice Example");
    expect(rows[2]).toHaveTextContent("deployers");
    expect(rows[2]).toHaveTextContent("Active");
    expect(rows[0]).toHaveTextContent("Built in");
    expect(rows[1]).toHaveTextContent("Disabled");
    expect(rows[1]).toHaveTextContent("Must change password");
    expect(screen.getByRole("link", { name: "New user" })).toHaveAttribute(
      "href",
      "/admin/users/new",
    );
    await expectAccessible();
  });

  test("offer no new user to whoever may only read them", async () => {
    users({}, holding("admin:users:read"));

    await screen.findByRole("table", { name: "Users" });

    expect(screen.queryByRole("link", { name: "New user" })).toBeNull();
  });

  test("come a page at a time, and say so when they may not be seen", async () => {
    const first = users(
      { "GET /users": { json: page([ALICE], 101) } },
      ADMIN,
      "/admin/users?page=3",
    );
    const pages = await screen.findByRole("navigation", { name: "Pages" });
    expect(first.calls[0]?.path).toBe("/users?limit=50&offset=100");
    expect(pages).toHaveTextContent("Page 3 of 3");
    expect(within(pages).getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/admin/users?page=2",
    );
    first.unmount();

    users({ "GET /users": failure(403, "forbidden", "No.") });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
  });
});

describe("another page of a list", () => {
  test("of users has the keyboard when it is shown, and a page past the last leads to the last", async () => {
    mockApi({ "GET /users": { json: page([ALICE], 101) } });
    navigation.at("/admin/users");
    const { rerender } = renderUi(<UsersScreen />, { session: ADMIN });
    await screen.findByRole("table", { name: "Users" });
    expect(screen.getByRole("group", { name: "Users" })).not.toHaveFocus(); // not on arrival

    navigation.at("/admin/users?page=2");
    rerender(<UsersScreen />);
    // The link that was followed went while the page loaded.
    await waitFor(() => expect(screen.getByRole("group", { name: "Users" })).toHaveFocus());

    navigation.at("/admin/users?page=9");
    rerender(<UsersScreen />);
    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/admin/users?page=3"),
    );
  });

  test("of roles has the keyboard when it is shown", async () => {
    mockApi({ "GET /roles": { json: page(ROLES, 60) } });
    navigation.at("/admin/roles");
    const { rerender } = renderUi(<RolesScreen />, { session: ADMIN });
    await screen.findByRole("table", { name: "Roles" });

    navigation.at("/admin/roles?page=2");
    rerender(<RolesScreen />);

    await waitFor(() => expect(screen.getByRole("group", { name: "Roles" })).toHaveFocus());
  });
});

describe("a new user (A6)", () => {
  function fresh(more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      "GET /roles": { json: page(ROLES) },
      "POST /users": (call) => ({
        status: 201,
        json: person((call.body as { username: string }).username, {
          must_change_password: (call.body as { must_change_password: boolean })
            .must_change_password,
        }),
      }),
      "GET /auth/session": { json: session },
      ...more,
    });
    navigation.at("/admin/users/new");
    return { ...renderUi(<NewUserScreen />, { session }), ...api };
  }
  const submit = () => screen.getByRole("button", { name: "Create user" });

  test("is made with a name, a password to start with, and roles", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("User name"), "carol");
    await user.type(screen.getByLabelText("Name"), " Carol Example ");
    await user.type(screen.getByLabelText("Password"), "typed-by-hand");
    await user.click(await screen.findByRole("checkbox", { name: "deployers" }));
    await user.click(submit());

    await screen.findByRole("region", { name: "The user carol is created" });
    expect(of(calls, "POST")[0]?.body).toEqual({
      username: "carol",
      display_name: "Carol Example",
      email: null,
      password: "typed-by-hand",
      must_change_password: true,
      roles: ["deployers"],
    });
    await expectAccessible();
  });

  test("says the password to pass on once more, where the keyboard is taken", async () => {
    const user = userEvent.setup();
    const { client } = fresh();
    await user.type(screen.getByLabelText("User name"), "carol");
    await user.type(screen.getByLabelText("Name"), "Carol");
    await user.click(screen.getByRole("button", { name: "Generate one" }));
    const generated = (screen.getByLabelText("Password") as HTMLInputElement).value;
    await user.click(submit());

    const created = await screen.findByRole("region", { name: "The user carol is created" });

    // It is on this panel, to be passed on, and nowhere else: not in what the store
    // keeps of the request that sent it.
    await waitFor(() =>
      expect(
        JSON.stringify(
          client
            .getMutationCache()
            .getAll()
            .map((mutation) => [mutation.state.variables, mutation.state.data]),
        ),
      ).not.toContain(generated),
    );
    expect(within(created).getByRole("heading")).toHaveFocus();
    expect(within(created).getByText(generated)).toBeVisible();
    expect(created).toHaveTextContent("They sign in with it once, and then choose their own.");
    expect(created).toHaveTextContent("It is not shown again once you leave this page.");
    await user.click(within(created).getByRole("button", { name: "Copy the password" }));
    expect(await navigator.clipboard.readText()).toBe(generated);
    expect(within(created).getByRole("link", { name: "Open carol" })).toHaveAttribute(
      "href",
      "/admin/users/id-of-carol",
    );

    // Another one: the form is empty again, and has the keyboard.
    await user.click(within(created).getByRole("button", { name: "Create another" }));
    expect(screen.getByLabelText("User name")).toHaveValue("");
    expect(screen.getByLabelText("User name")).toHaveFocus();
    expect(document.body).not.toHaveTextContent(generated);
  });

  test("says what is wrong with what was typed, at the first field it is wrong at", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("User name"), "has space");
    await user.type(screen.getByLabelText("Email"), "not-an-address");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(submit());

    expect(screen.getByLabelText("User name")).toHaveAccessibleDescription(
      "A user name is 1 to 64 letters, digits or . _ @ -",
    );
    expect(screen.getByLabelText("User name")).toHaveFocus();
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Give their name.");
    expect(screen.getByLabelText("Email")).toHaveAccessibleDescription(
      "This is not an email address.",
    );
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      "The password must be at least 8 characters long.",
    );
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("puts the keyboard at what is still wrong at every press, not only the first", async () => {
    const user = userEvent.setup();
    fresh();

    await user.click(submit());
    expect(screen.getByLabelText("User name")).toHaveFocus();
    await user.type(screen.getByLabelText("User name"), "carol");
    await user.click(submit());

    // The name is next: without this the button would seem to do nothing.
    expect(screen.getByLabelText("Name")).toHaveFocus();
  });

  test("is not offered to whoever may not create users, though the address be typed", async () => {
    fresh({}, holding("admin:users:read", "admin:roles:read"));

    expect(await screen.findByRole("alert")).toHaveTextContent("You may not create users.");
    expect(screen.queryByRole("button", { name: "Create user" })).toBeNull();
    expect(screen.queryByLabelText("User name")).toBeNull();
  });

  test("says that a name is taken at the name, and anything else the server refuses where it belongs", async () => {
    const user = userEvent.setup();
    const fill = async () => {
      await user.type(screen.getByLabelText("User name"), "alice");
      await user.type(screen.getByLabelText("Name"), "Alice");
      await user.type(screen.getByLabelText("Password"), "long-enough");
      await user.click(submit());
    };
    const first = fresh({
      "POST /users": failure(409, "conflict", "A user named alice already exists."),
    });
    await fill();
    await waitFor(() =>
      expect(screen.getByLabelText("User name")).toHaveAccessibleDescription(
        "A user named alice already exists.",
      ),
    );
    expect(screen.getByLabelText("User name")).toHaveFocus();
    first.unmount();

    const second = fresh({
      "POST /users": failure(422, "validation_error", "The request is not valid.", [
        { field: "password", message: "The password must not be the user name." },
      ]),
    });
    await fill();
    await waitFor(() =>
      expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
        "The password must not be the user name.",
      ),
    );
    second.unmount();

    fresh({ "POST /users": failure(500, "internal_error", "Oops.") });
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
  });

  test("gives no role where the roles may not be seen, and says so", async () => {
    const user = userEvent.setup();
    const { calls } = fresh({}, holding("admin:users:read", "admin:users:write"));

    expect(screen.getByText("You may not see the roles, so none can be given here.")).toBeVisible();
    await user.type(screen.getByLabelText("User name"), "dave");
    await user.type(screen.getByLabelText("Name"), "Dave");
    await user.type(screen.getByLabelText("Password"), "long-enough");
    await user.click(submit());

    await screen.findByRole("region", { name: "The user dave is created" });
    expect(calls.some((call) => call.path.startsWith("/roles"))).toBe(false);
    expect((of(calls, "POST")[0]?.body as { roles: string[] }).roles).toEqual([]);
  });
});

describe("one user", () => {
  function one(who = ALICE, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      [`GET /users/${who.id}`]: { json: who },
      [`GET /users/${who.id}/connected-apps`]: {
        json: page([
          {
            id: "app1",
            client: "Claude",
            redirect_host: "claude.ai",
            scopes: null,
            created_at: "2026-10-18T08:00:00Z",
            last_used_at: null,
            expires_at: null,
          },
        ]),
      },
      [`GET /users/${who.id}/tokens`]: {
        json: page([
          {
            id: "t1",
            name: "ci build",
            display_prefix: "mga_Uw7S",
            scopes: null,
            expires_at: null,
            created_at: "2026-10-01T08:00:00Z",
            last_used_at: null,
          },
        ]),
      },
      "GET /roles": { json: page(ROLES) },
      "GET /users": { json: page([SELF, ALICE]) },
      "GET /auth/session": { json: session },
      ...more,
    });
    navigation.at(`/admin/users/${who.id}`);
    return { ...renderUi(<UserScreen />, { session }), ...api };
  }

  test("is who they are, what they hold, and whether they can sign in", async () => {
    one();

    expect(await screen.findByRole("heading", { level: 1, name: "alice" })).toBeVisible();
    expect(screen.getByLabelText("Name")).toHaveValue("Alice Example");
    expect(screen.getByLabelText("Email")).toHaveValue("alice@example.com");
    expect(await screen.findByRole("checkbox", { name: "deployers" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "admin" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Active" })).toBeChecked();
    expect(
      within(screen.getByRole("navigation", { name: "Path" })).getAllByRole("link")[0],
    ).toHaveAttribute("href", "/admin/users");
    await expectAccessible();
  });

  test("is saved with what was changed, and the session is asked again (A10)", async () => {
    const user = userEvent.setup();
    const { calls } = one(ALICE, { "PATCH /users/id-of-alice": { json: ALICE } });
    await screen.findByRole("checkbox", { name: "deployers" });

    await user.clear(screen.getByLabelText("Email"));
    await user.click(screen.getByRole("checkbox", { name: "admin" }));
    await user.click(screen.getByRole("radio", { name: "Disabled" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Saved alice."));
    expect(of(calls, "PATCH")[0]?.body).toEqual({
      display_name: "Alice Example",
      email: null,
      roles: ["deployers", "admin"],
      status: "disabled",
    });
    // What the person who saved may do can have changed with it.
    await waitFor(() => expect(calls.some((call) => call.path === "/auth/session")).toBe(true));
    expect(screen.getByRole("button", { name: "Save" })).toHaveFocus();
  });

  test("says what the server will not have, as it says it", async () => {
    const user = userEvent.setup();
    one(ALICE, {
      "PATCH /users/id-of-alice": failure(
        409,
        "last_administrator",
        "This would leave nobody who can sign in with full access.",
      ),
    });
    await screen.findByRole("checkbox", { name: "deployers" });

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This would leave nobody who can sign in with full access.",
    );
  });

  test("one's own account cannot be disabled or deleted here, and the screen says so (A7)", async () => {
    const user = userEvent.setup();
    const { calls } = one(SELF, { [`PATCH /users/${SELF.id}`]: { json: SELF } });
    await screen.findByRole("checkbox", { name: "admin" });

    expect(screen.queryByRole("radio", { name: "Disabled" })).toBeNull();
    expect(screen.getByText("This is your own account: you cannot disable it.")).toBeVisible();
    expect(screen.getByText("This is your own account: you cannot delete it.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Delete user" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(of(calls, "PATCH")).toHaveLength(1));
    expect(of(calls, "PATCH")[0]?.body).not.toHaveProperty("status");
  });

  test("one's own password is not set here, where doing so would lock one out (A7)", async () => {
    one(SELF);
    await screen.findByRole("checkbox", { name: "admin" });

    // Set here with "must choose a new one", it would end this page and ask for the
    // password that was on it.
    expect(screen.queryByRole("button", { name: "Set password" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Generate one" })).toBeNull();
    expect(screen.getByText(/This is your own account: your password is changed/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Change your password" })).toHaveAttribute(
      "href",
      "/account/password",
    );
  });

  test("opens with what the server holds now, and not with what was fetched before", async () => {
    const user = userEvent.setup();
    let held = ["deployers"];
    const { calls, rerender } = one(ALICE, {
      "GET /users/id-of-alice": () => ({ json: { ...ALICE, roles: held } }),
      "PATCH /users/id-of-alice": { json: ALICE },
    });
    expect(await screen.findByRole("checkbox", { name: "deployers" })).toBeChecked();

    // Away, and back within the time what was fetched is kept. Meanwhile the role was
    // taken from her elsewhere.
    rerender(<p>Elsewhere</p>);
    held = [];
    rerender(<UserScreen />);

    const role = await screen.findByRole("checkbox", { name: "deployers" });
    await waitFor(() => expect(role).not.toBeChecked());
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(of(calls, "PATCH")).toHaveLength(1));
    expect((of(calls, "PATCH")[0]?.body as { roles: string[] }).roles).toEqual([]);
  });

  test("a built-in user is not deleted, and the anonymous one has no password", async () => {
    one(ANONYMOUS);

    await screen.findByRole("heading", { level: 1, name: "anonymous" });

    expect(
      screen.getByText("This user is built in. It can be changed, and not deleted."),
    ).toBeVisible();
    expect(
      screen.getByText("A built-in user cannot be deleted. It can be disabled."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Delete user" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Set a new password" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Disabled" })).toBeVisible();
  });

  test("is shown, and not changed, by whoever may only read users", async () => {
    const { calls } = one(ALICE, {}, holding("admin:users:read"));

    await screen.findByRole("heading", { level: 1, name: "alice" });

    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByText("deployers")).toBeVisible(); // held, as text: roles may not be read
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Set a new password" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Delete this user" })).toBeNull();
    // Nor their tokens, which is a permission of its own.
    expect(screen.queryByRole("heading", { name: "API tokens" })).toBeNull();
    expect(calls.some((call) => call.path.includes("/tokens"))).toBe(false);
    expect(calls.some((call) => call.path.startsWith("/roles"))).toBe(false);
  });

  test("is given a new password, typed or generated, which is to be passed on", async () => {
    const user = userEvent.setup();
    const { calls } = one(ALICE, { "PUT /users/id-of-alice/password": { status: 204 } });
    await screen.findByRole("heading", { name: "Set a new password" });

    await user.type(screen.getByLabelText("New password"), "short");
    await user.click(screen.getByRole("button", { name: "Set password" }));
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      "The password must be at least 8 characters long.",
    );
    expect(screen.getByLabelText("New password")).toHaveFocus();
    expect(of(calls, "PUT")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Generate one" }));
    const generated = (screen.getByLabelText("New password") as HTMLInputElement).value;
    await user.click(
      screen.getByRole("checkbox", { name: "Must choose a new password at the next sign-in" }),
    );
    await user.click(screen.getByRole("button", { name: "Set password" }));

    expect(await screen.findByText("The password of alice is set")).toBeVisible();
    expect(of(calls, "PUT")[0]?.body).toEqual({
      password: generated,
      must_change_password: false,
    });
    // Still there to be copied: it is not shown again once the page is left.
    expect(screen.getByLabelText("New password")).toHaveValue(generated);
  });

  test("has their tokens listed, and revoked by whoever may", async () => {
    const user = userEvent.setup();
    const first = one(ALICE, { "DELETE /users/id-of-alice/tokens/t1": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Revoke ci build" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Revoked the token ci build of alice."),
    );
    expect(of(first.calls, "DELETE")[0]?.path).toBe("/users/id-of-alice/tokens/t1");
    first.unmount();

    one(ALICE, {}, holding("admin:users:read", "admin:tokens:read"));
    expect(await screen.findByRole("table", { name: "API tokens of alice" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Revoke ci build" })).toBeNull();
  });

  test("has the applications they connected listed, and revoked by whoever may", async () => {
    const user = userEvent.setup();
    const first = one(ALICE, { "DELETE /users/id-of-alice/connected-apps/app1": { status: 204 } });

    const table = await screen.findByRole("table", { name: "Applications alice connected" });
    expect(within(table).getByText("Sent back to claude.ai")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Revoke Claude" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Revoked Claude, which alice connected."),
    );
    expect(of(first.calls, "DELETE")[0]?.path).toBe("/users/id-of-alice/connected-apps/app1");
    first.unmount();

    one(ALICE, {}, holding("admin:users:read", "admin:tokens:read"));
    expect(
      await screen.findByRole("table", { name: "Applications alice connected" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Revoke Claude" })).toBeNull();
  });

  test("is deleted only by whoever types their name, and is then not asked for again (A8)", async () => {
    const user = userEvent.setup();
    const { calls } = one(ALICE, { "DELETE /users/id-of-alice": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete user" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the user alice?" });
    const confirm = within(dialog).getByRole("button", { name: "Delete user" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Type alice to go on"), "alice");
    await user.click(confirm);

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/admin/users"));
    expect(notices()).toHaveTextContent("Deleted the user alice.");
    await new Promise((resolve) => setTimeout(resolve, 50));
    const since = calls.slice(calls.findIndex((call) => call.method === "DELETE") + 1);
    expect(since.filter((call) => call.path.startsWith("/users/id-of-alice"))).toEqual([]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("says why when the user could not be deleted, or is not there", async () => {
    const user = userEvent.setup();
    const first = one(ALICE, {
      "DELETE /users/id-of-alice": failure(409, "last_administrator", "Nobody would be left."),
    });
    await user.click(await screen.findByRole("button", { name: "Delete user" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type alice to go on"), "alice");
    await user.click(within(dialog).getByRole("button", { name: "Delete user" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nobody would be left.");
    expect(navigation.router.replace).not.toHaveBeenCalled();
    first.unmount();

    one(ALICE, { "GET /users/id-of-alice": failure(404, "not_found", "No such user.") });
    expect(await screen.findByRole("alert")).toHaveTextContent("This was not found.");
  });
});

describe("the roles", () => {
  function roles(session = ADMIN) {
    const api = mockApi({ "GET /roles": { json: page(ROLES) } });
    navigation.at("/admin/roles");
    return { ...renderUi(<RolesScreen />, { session }), ...api };
  }

  test("are listed with what they hold", async () => {
    const { calls } = roles();

    const table = await screen.findByRole("table", { name: "Roles" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(calls[0]?.path).toBe("/roles?limit=50&offset=0");
    expect(within(rows[2] as HTMLElement).getByRole("link", { name: "deployers" })).toHaveAttribute(
      "href",
      "/admin/roles/deployers",
    );
    expect(rows[2]).toHaveTextContent("May deploy releases");
    expect(rows[2]).toHaveTextContent("repository:maven:releases:add");
    expect(rows[2]).toHaveTextContent("anonymous");
    expect(rows[0]).toHaveTextContent("Built in");
    // At an address no role's name can be: a role may be called "new".
    expect(screen.getByRole("link", { name: "New role" })).toHaveAttribute(
      "href",
      "/admin/roles/~new",
    );
    await expectAccessible();
  });

  test("show a role that no address can name, without a link to nowhere", async () => {
    mockApi({ "GET /roles": { json: page([role(".."), role("deployers")]) } });
    navigation.at("/admin/roles");
    renderUi(<RolesScreen />, { session: ADMIN });

    const table = await screen.findByRole("table", { name: "Roles" });

    expect(within(table).getByText("..")).toBeVisible();
    expect(within(table).queryByRole("link", { name: ".." })).toBeNull();
    expect(within(table).getByRole("link", { name: "deployers" })).toBeVisible();
  });

  test("offer no new role to whoever may only read them", async () => {
    roles(holding("admin:roles:read"));

    await screen.findByRole("table", { name: "Roles" });

    expect(screen.queryByRole("link", { name: "New role" })).toBeNull();
  });
});

describe("a role", () => {
  const SAVED = { ...DEPLOYERS };
  function existing(which = DEPLOYERS, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      [`GET /roles/${which?.name}`]: { json: which },
      "GET /roles": { json: page(ROLES) },
      "GET /content": { json: REPOSITORIES },
      "GET /users": { json: page([SELF]) },
      "GET /auth/session": { json: session },
      ...more,
    });
    navigation.at(`/admin/roles/${which?.name}`);
    return { ...renderUi(<RoleScreen />, { session }), ...api };
  }
  function fresh(more: Routes = {}) {
    const api = mockApi({
      "GET /roles": { json: page(ROLES) },
      "GET /content": { json: REPOSITORIES },
      "GET /users": { json: page([SELF]) },
      "GET /auth/session": { json: ADMIN },
      "POST /roles": (call) => ({ status: 201, json: role((call.body as { name: string }).name) }),
      ...more,
    });
    navigation.at("/admin/roles/~new");
    return { ...renderUi(<NewRoleScreen />, { session: ADMIN }), ...api };
  }

  test("is made with a name, permissions as rows, and the roles it contains", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("Name"), "readers");
    await user.type(screen.getByLabelText("Description"), "May read everything");
    await user.click(screen.getByRole("button", { name: "Add a permission" }));
    await user.click(await screen.findByRole("checkbox", { name: "anonymous" }));
    await user.click(screen.getByRole("button", { name: "Create role" }));

    await waitFor(() =>
      expect(navigation.router.push).toHaveBeenCalledWith("/admin/roles/readers"),
    );
    expect(of(calls, "POST")[0]?.body).toEqual({
      name: "readers",
      description: "May read everything",
      permissions: ["repository:*:*:read"],
      roles: ["anonymous"],
    });
    expect(notices()).toHaveTextContent("Created the role readers.");
  });

  test("needs a name of the kind a role has, and one no other role has", async () => {
    const user = userEvent.setup();
    const { calls } = fresh({
      "POST /roles": failure(409, "conflict", "A role named deployers already exists."),
    });

    await user.type(screen.getByLabelText("Name"), "has space");
    await user.click(screen.getByRole("button", { name: "Create role" }));
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "A role's name is 1 to 64 letters, digits or . _ -",
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(of(calls, "POST")).toHaveLength(0);

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "deployers");
    await user.click(screen.getByRole("button", { name: "Create role" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A role named deployers already exists.",
      ),
    );
    expect(navigation.router.push).not.toHaveBeenCalled();
  });

  test("cannot be called . or .., which no address can name", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    for (const dots of [".", ".."]) {
      await user.clear(screen.getByLabelText("Name"));
      await user.type(screen.getByLabelText("Name"), dots);
      await user.click(screen.getByRole("button", { name: "Create role" }));
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A role cannot be called . or .. : its page would have no address.",
      );
    }
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("may be called new, and is then opened as any other", async () => {
    existing(role("new", { description: "A role like any other" }));

    expect(await screen.findByRole("heading", { level: 1, name: "new" })).toBeVisible();
    expect(screen.getByLabelText("Description")).toHaveValue("A role like any other");
    expect(screen.getByRole("button", { name: "Save" })).toBeVisible();
  });

  test("is not offered as a form to whoever may not create roles, though the address be typed", async () => {
    mockApi({ "GET /roles": { json: page(ROLES) }, "GET /content": { json: REPOSITORIES } });
    navigation.at("/admin/roles/~new");
    renderUi(<NewRoleScreen />, { session: holding("admin:roles:read") });

    expect(await screen.findByRole("alert")).toHaveTextContent("You may not create roles.");
    expect(screen.queryByRole("button", { name: "Create role" })).toBeNull();
  });

  test("opens with what the server holds now, and not with what was fetched before", async () => {
    const user = userEvent.setup();
    let action = "read";
    const held = () => role("readers", { permissions: [`repository:maven:releases:${action}`] });
    const { calls, rerender } = existing(held(), {
      "GET /roles/readers": () => ({ json: held() }),
      "PUT /roles/readers": { json: held() },
    });
    const first = await screen.findByRole("group", { name: "Permission 1" });
    expect(within(first).getByLabelText("Action")).toHaveValue("read");

    // Away, and back. Meanwhile it was narrowed elsewhere: saving must not widen it again.
    rerender(<p>Elsewhere</p>);
    action = "browse";
    rerender(<RoleScreen />);

    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: "Permission 1" })).getByLabelText("Action"),
      ).toHaveValue("browse"),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(of(calls, "PUT")).toHaveLength(1));
    expect((of(calls, "PUT")[0]?.body as { permissions: string[] }).permissions).toEqual([
      "repository:maven:releases:browse",
    ]);
  });

  test("opens with what it holds, and loses nothing by being saved as it is (A3)", async () => {
    const user = userEvent.setup();
    const { calls } = existing(DEPLOYERS, { "PUT /roles/deployers": { json: SAVED } });

    expect(await screen.findByRole("heading", { level: 1, name: "deployers" })).toBeVisible();
    const first = screen.getByRole("group", { name: "Permission 1" });
    expect(within(first).getByLabelText("Repository")).toHaveValue("releases");
    // A permission this UI has no lists for is there as it was typed.
    expect(
      within(screen.getByRole("group", { name: "Permission 2" })).getByLabelText("Pattern"),
    ).toHaveValue("admin:audit:read");
    // A role does not contain itself, so it is not offered itself.
    expect(await screen.findByRole("checkbox", { name: "anonymous" })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "deployers" })).toBeNull();
    await expectAccessible();

    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Saved the role deployers."));
    expect(of(calls, "PUT")[0]?.body).toEqual({
      description: "May deploy releases",
      permissions: ["repository:maven:releases:add", "admin:audit:read"],
      roles: ["anonymous"],
    });
    await waitFor(() => expect(calls.some((call) => call.path === "/auth/session")).toBe(true));
  });

  test("is not saved while a permission is no pattern: the keyboard goes to it", async () => {
    const user = userEvent.setup();
    const { calls } = existing(DEPLOYERS, { "PUT /roles/deployers": { json: SAVED } });
    await screen.findByRole("group", { name: "Permission 2" });

    const typed = within(screen.getByRole("group", { name: "Permission 2" })).getByLabelText(
      "Pattern",
    );
    await user.clear(typed);
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(typed).toHaveAttribute("aria-invalid", "true");
    expect(typed).toHaveFocus();
    expect(of(calls, "PUT")).toHaveLength(0);
  });

  test("says what the server will not have: a role that would contain itself", async () => {
    const user = userEvent.setup();
    existing(DEPLOYERS, {
      "PUT /roles/deployers": failure(
        409,
        "role_cycle",
        "A role cannot contain itself, directly or indirectly.",
      ),
    });
    await screen.findByRole("group", { name: "Permission 1" });

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A role cannot contain itself, directly or indirectly.",
    );
  });

  test("the role that makes an administrator is shown, and changed by nobody (A7)", async () => {
    existing(ROLES[0]);

    expect(await screen.findByRole("heading", { level: 1, name: "admin" })).toBeVisible();
    expect(screen.getByText(/It grants everything, and cannot be changed/)).toBeVisible();
    expect(
      screen.getByText("Everything: every repository, and all of the administration."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add a permission" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete role" })).toBeNull();
  });

  test("another built-in role is changed, and not deleted", async () => {
    existing(ROLES[1]);

    expect(await screen.findByRole("button", { name: "Save" })).toBeVisible();
    expect(
      screen.getByText("This role is built in. It can be changed, and not deleted."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Delete role" })).toBeNull();
  });

  test("is shown, and not changed, by whoever may only read roles", async () => {
    existing(DEPLOYERS, {}, holding("admin:roles:read"));

    await screen.findByRole("heading", { level: 1, name: "deployers" });

    expect(screen.getByText("repository:maven:releases:add")).toBeVisible();
    expect(screen.getByText("Add in the maven repository releases.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete role" })).toBeNull();
  });

  test("is deleted after asking, and is then not asked for again (A8)", async () => {
    const user = userEvent.setup();
    const { calls } = existing(DEPLOYERS, { "DELETE /roles/deployers": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete role" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the role deployers?" });
    expect(dialog).toHaveTextContent("Everyone who holds it loses what it grants, at once.");
    await user.click(within(dialog).getByRole("button", { name: "Delete role" }));

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/admin/roles"));
    expect(notices()).toHaveTextContent("Deleted the role deployers.");
    await new Promise((resolve) => setTimeout(resolve, 50));
    const since = calls.slice(calls.findIndex((call) => call.method === "DELETE") + 1);
    expect(since.filter((call) => call.path === "/roles/deployers")).toEqual([]);
  });
});

describe("anonymous access (A9)", () => {
  function anonymous(enabled: boolean, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      "GET /settings": { json: { base_url: null, anonymous_access: { enabled } } },
      "PUT /settings/anonymous-access": (call) => ({
        json: { base_url: null, anonymous_access: call.body },
      }),
      "GET /users": { json: page([SELF, ALICE, { ...ANONYMOUS, roles: ["deployers"] }]) },
      "GET /roles": { json: page(ROLES) },
      ...more,
    });
    navigation.at("/admin/anonymous-access");
    return { ...renderUi(<AnonymousAccessScreen />, { session }), ...api };
  }

  test("is off until it is turned on, which asks first and says what it means", async () => {
    const user = userEvent.setup();
    const { calls } = anonymous(false);

    expect(await screen.findByText("Off")).toBeVisible();
    expect(screen.getByText(/Nothing is given without signing in/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    const dialog = screen.getByRole("alertdialog", { name: "Turn anonymous access on?" });
    expect(dialog).toHaveTextContent("Anyone who can reach this server");
    expect(of(calls, "PUT")).toHaveLength(0);
    await expectAccessible();
    await user.click(within(dialog).getByRole("button", { name: "Turn on" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Anonymous access is on."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ enabled: true });
    expect(screen.getByText("On")).toBeVisible();
    expect(screen.getByRole("button", { name: "Turn off" })).toBeVisible();
  });

  test("is turned off at once", async () => {
    const user = userEvent.setup();
    const { calls } = anonymous(true);

    await user.click(await screen.findByRole("button", { name: "Turn off" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Anonymous access is off."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ enabled: false });
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  test("shows what a visitor may do: the anonymous user's roles, and those they contain", async () => {
    anonymous(true);

    expect(await screen.findByRole("link", { name: "deployers" })).toHaveAttribute(
      "href",
      "/admin/roles/deployers",
    );
    expect(screen.getByRole("link", { name: "Change its roles" })).toHaveAttribute(
      "href",
      "/admin/users/id-of-anonymous",
    );
    // Of deployers itself, and of the role anonymous that it contains.
    expect(screen.getByText("repository:maven:releases:add")).toBeVisible();
    expect(screen.getByText("Browse in every repository.")).toBeVisible();
    expect(screen.getByText("Read in every repository.")).toBeVisible();
    // Not what a visitor is never allowed, whatever the roles say.
    expect(screen.queryByText("admin:audit:read")).toBeNull();
    await expectAccessible();
  });

  test("says so when it is on and gives nothing, the anonymous user being disabled", async () => {
    anonymous(true, {
      "GET /users": { json: page([SELF, { ...ANONYMOUS, status: "disabled" }]) },
    });

    expect(await screen.findByText(/The anonymous user is disabled/)).toBeVisible();
    // Not that anyone may do what is listed: nobody may, until the user is enabled.
    expect(screen.queryByText(/Anyone who can reach this server may do/)).toBeNull();
    expect(screen.getByRole("link", { name: "Change its roles" })).toHaveAttribute(
      "href",
      "/admin/users/id-of-anonymous",
    );
  });

  test("offers no switch to whoever may only read the settings, and says what it cannot show", async () => {
    const { calls } = anonymous(false, {}, holding("admin:settings:read"));

    expect(await screen.findByText("Off")).toBeVisible();

    expect(screen.queryByRole("button", { name: "Turn on" })).toBeNull();
    expect(screen.getByText(/You may not see users and roles/)).toBeVisible();
    expect(calls.map((call) => call.path)).toEqual(["/settings"]);
  });

  test("says why when it could not be changed", async () => {
    const user = userEvent.setup();
    anonymous(true, { "PUT /settings/anonymous-access": failure(403, "forbidden", "No.") });

    await user.click(await screen.findByRole("button", { name: "Turn off" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
    expect(screen.getByText("On")).toBeVisible();
  });
});
