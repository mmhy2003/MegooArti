import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { AuthenticationScreen } from "./authentication";

const page = (items: unknown[], total = items.length) => ({ items, total, limit: 200, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

const source = (name: string, position: number, more: Record<string, unknown> = {}) => ({
  id: name.toLowerCase().replace(" ", "-"),
  kind: "ldap",
  name,
  enabled: true,
  position,
  settings: { url: "ldaps://ldap.example" },
  secrets: ["bind_password"],
  group_mapping: [{ group: "developers", roles: ["deployers"] }],
  users: 3,
  created_at: "2026-10-19T08:00:00Z",
  updated_at: "2026-10-19T08:00:00Z",
  ...more,
});
const CORP = source("Corp LDAP", 0);
const LAB = source("Lab LDAP", 1, { enabled: false, users: 0 });
const SIGN_IN = { default_role: null, local_sign_in: { enabled: true } };
const ROLES = page(
  ["admin", "anonymous", "deployers"].map((name) => ({
    name,
    description: "",
    builtin: name !== "deployers",
    permissions: [],
    roles: [],
  })),
);

function authentication(more: Routes = {}, session = ADMIN) {
  const api = mockApi({
    "GET /settings/sign-in": { json: SIGN_IN },
    "GET /auth-sources": { json: page([CORP, LAB]) },
    "GET /roles": { json: ROLES },
    "GET /auth/session": { json: session },
    ...more,
  });
  navigation.at("/admin/authentication");
  return { ...renderUi(<AuthenticationScreen />, { session }), ...api };
}

/** The rows of the table of sources, each as the text of its cells. */
async function rows() {
  const table = await screen.findByRole("table", { name: "Sign-in sources" });
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .slice(0, 4)
        .map((cell) => cell.textContent),
    );
}

describe("the sign-in sources (SEC-15)", () => {
  test("are MegooArti's own users first, then each source in the order it is asked", async () => {
    authentication();

    expect(await rows()).toEqual([
      ["MegooArti's own users", "local", "", "On"],
      ["Corp LDAP", "ldap", "3", "On"],
      ["Lab LDAP", "ldap", "0", "Off"],
    ]);
    expect(screen.getByRole("button", { name: "Move Corp LDAP up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move Lab LDAP down" })).toBeDisabled();
    await expectAccessible();
  });

  test("lead to each source's page, and to a new one for whoever may write", async () => {
    authentication();

    expect(await screen.findByRole("link", { name: "Corp LDAP" })).toHaveAttribute(
      "href",
      "/admin/authentication/corp-ldap",
    );
    expect(screen.getByRole("link", { name: "New OIDC source" })).toHaveAttribute(
      "href",
      "/admin/authentication/~new",
    );
  });

  test("say so when there is none but ours", async () => {
    authentication({ "GET /auth-sources": { json: page([]) } });

    expect(await screen.findByText(/There is no other source yet/)).toBeVisible();
  });

  test("are moved by sending the whole order, and shown in the order the server answers", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "PUT /auth-sources/order": {
        json: page([
          { ...LAB, position: 0 },
          { ...CORP, position: 1 },
        ]),
      },
    });

    await user.click(await screen.findByRole("button", { name: "Move Lab LDAP up" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Moved Lab LDAP."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ ids: ["lab-ldap", "corp-ldap"] });
    expect((await rows()).map((row) => row[0])).toEqual([
      "MegooArti's own users",
      "Lab LDAP",
      "Corp LDAP",
    ]);
  });

  test("are turned on and off with what they have, their secrets kept by the server", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "PUT /auth-sources/lab-ldap": (call) => ({
        json: { ...LAB, ...(call.body as object) },
      }),
    });

    await user.click(await screen.findByRole("button", { name: "Turn on Lab LDAP" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Lab LDAP is on."));
    expect(of(calls, "PUT")[0]?.body).toEqual({
      name: "Lab LDAP",
      enabled: true,
      settings: { url: "ldaps://ldap.example" },
      group_mapping: [{ group: "developers", roles: ["deployers"] }],
    });
  });

  test("are tested, and what the test found is said", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "POST /auth-sources/corp-ldap/test": {
        json: { ok: false, message: "ldap.example did not answer.", user: null },
      },
    });

    await user.click(await screen.findByRole("button", { name: "Test Corp LDAP" }));

    expect(await screen.findByText("ldap.example did not answer.")).toBeVisible();
    expect(of(calls, "POST")[0]?.body).toEqual({});
  });

  test("are deleted only for whoever types the name, and say their users are kept", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({ "DELETE /auth-sources/corp-ldap": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete Corp LDAP" }));
    const dialog = screen.getByRole("alertdialog", {
      name: "Delete the sign-in source Corp LDAP?",
    });
    expect(dialog).toHaveTextContent("3 users are disabled, and kept with what they own.");
    expect(within(dialog).getByRole("button", { name: "Delete source" })).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox"), "Corp LDAP");
    await user.click(within(dialog).getByRole("button", { name: "Delete source" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Deleted the sign-in source Corp LDAP."),
    );
    expect(of(calls, "DELETE")).toHaveLength(1);
  });

  test("say what the server refuses", async () => {
    const user = userEvent.setup();
    authentication({
      "PUT /auth-sources/order": failure(422, "validation_error", "Give every source once."),
    });

    await user.click(await screen.findByRole("button", { name: "Move Lab LDAP up" }));

    expect(await screen.findByText(/Give every source once/)).toBeVisible();
  });

  test("are shown, and not changed, to whoever may only read them", async () => {
    authentication({}, holding("admin:security:read"));

    expect((await rows()).length).toBe(3);
    expect(screen.queryByRole("button", { name: /Delete|Turn|Move|Test/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "New OIDC source" })).toBeNull();
    expect(screen.getByText("None")).toBeVisible();
    expect(screen.queryByLabelText("Default role")).toBeNull();
  });
});

describe("MegooArti's own users (E1)", () => {
  test("are turned off only after saying that only admin will sign in here", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "PUT /settings/local-sign-in": (call) => ({
        json: { ...SIGN_IN, local_sign_in: call.body },
      }),
    });

    const [local] = await rows();
    expect(local).toEqual(["MegooArti's own users", "local", "", "On"]);
    await user.click(screen.getByRole("button", { name: "Turn off" }));
    const dialog = screen.getByRole("alertdialog", { name: "Turn off MegooArti's own users?" });
    expect(dialog).toHaveTextContent("Only the built-in admin will sign in");
    expect(of(calls, "PUT")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Turn off" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent(
        "Only the built-in admin signs in as one of MegooArti's own users now.",
      ),
    );
    expect(of(calls, "PUT")[0]?.body).toEqual({ enabled: false });
    // What the person who did it may do can have changed with it.
    await waitFor(() =>
      expect(of(calls, "GET").some((c) => c.path === "/auth/session")).toBe(true),
    );
  });

  test("say why they stay on when the server refuses", async () => {
    const user = userEvent.setup();
    authentication({
      "PUT /settings/local-sign-in": failure(
        409,
        "last_administrator",
        "This change would leave no active user with full access.",
      ),
    });

    await user.click(await screen.findByRole("button", { name: "Turn off" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Turn off" }),
    );

    expect(
      await screen.findByText(/This change would leave no active user with full access/),
    ).toBeVisible();
  });
});

describe("the default role (SEC-16)", () => {
  test("is none until one is chosen, and is saved as it is chosen", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "PUT /settings/default-role": (call) => ({ json: { ...SIGN_IN, ...(call.body as object) } }),
    });

    const chooser = await screen.findByLabelText("Default role");
    expect(chooser).toHaveValue("");
    await user.selectOptions(chooser, "deployers");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Every signed-in user has the role deployers."),
    );
    expect(of(calls, "PUT")[0]?.body).toEqual({ default_role: "deployers" });
  });

  test("is taken away by choosing none", async () => {
    const user = userEvent.setup();
    const { calls } = authentication({
      "GET /settings/sign-in": { json: { ...SIGN_IN, default_role: "deployers" } },
      "PUT /settings/default-role": (call) => ({ json: { ...SIGN_IN, ...(call.body as object) } }),
    });

    const chooser = await screen.findByLabelText("Default role");
    expect(chooser).toHaveValue("deployers");
    await user.selectOptions(chooser, "None");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("There is no default role."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ default_role: null });
  });
});
