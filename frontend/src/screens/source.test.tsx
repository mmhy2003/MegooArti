import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { NewSourceScreen, SourceScreen } from "./source";

const page = (items: unknown[]) => ({ items, total: items.length, limit: 200, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });
const ROLES = page(
  ["admin", "deployers", "readers"].map((name) => ({
    name,
    description: "",
    builtin: name === "admin",
    permissions: [],
    roles: [],
  })),
);
const CORP = {
  id: "corp",
  kind: "oidc",
  name: "Corp SSO",
  enabled: true,
  position: 0,
  settings: {
    issuer: "https://sso.example/realms/corp",
    client_id: "megooarti",
    scopes: ["openid", "profile", "email", "groups"],
    require_verified_email: false,
    username_claim: "preferred_username",
    name_claim: "name",
    email_claim: "email",
    groups_claim: "groups",
  },
  secrets: ["client_secret"],
  group_mapping: [{ group: "developers", roles: ["deployers", "readers"] }],
  users: 4,
  redirect_uri: "https://repo.example.org/api/v1/auth/oidc/corp/callback",
  created_at: "2026-10-19T08:00:00Z",
  updated_at: "2026-10-19T08:00:00Z",
};

function newSource(more: Routes = {}, session = ADMIN) {
  const api = mockApi({ "GET /roles": { json: ROLES }, ...more });
  navigation.at("/admin/authentication/~new");
  return { ...renderUi(<NewSourceScreen />, { session }), ...api };
}

function oneSource(more: Routes = {}, session = ADMIN) {
  const api = mockApi({
    "GET /auth-sources/corp": { json: CORP },
    "GET /roles": { json: ROLES },
    ...more,
  });
  navigation.at("/admin/authentication/corp");
  return { ...renderUi(<SourceScreen />, { session }), ...api };
}

describe("a new OIDC source (spec 5)", () => {
  test("is made off, with what was typed, the claims' defaults, and the groups' roles", async () => {
    const user = userEvent.setup();
    const { calls } = newSource({
      "POST /auth-sources": (call) => ({
        status: 201,
        json: { ...CORP, ...(call.body as object) },
      }),
    });

    await user.type(await screen.findByLabelText("Name"), "Corp SSO");
    await user.type(screen.getByLabelText("Issuer"), "https://sso.example/realms/corp");
    await user.type(screen.getByLabelText("Client ID"), "megooarti");
    await user.type(screen.getByLabelText("Client secret"), "s3cret");
    await user.click(screen.getByRole("button", { name: "Give a group a role" }));
    await user.type(screen.getByLabelText("Group 1"), "developers");
    await user.selectOptions(screen.getByLabelText("Role 1"), "deployers");
    await user.click(screen.getByRole("button", { name: "Give a group a role" }));
    await user.type(screen.getByLabelText("Group 2"), "developers");
    await user.selectOptions(screen.getByLabelText("Role 2"), "readers");
    await expectAccessible();
    await user.click(screen.getByRole("button", { name: "Create source" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Created the sign-in source Corp SSO."),
    );
    expect(of(calls, "POST")[0]?.body).toEqual({
      kind: "oidc",
      name: "Corp SSO",
      enabled: false,
      settings: {
        issuer: "https://sso.example/realms/corp",
        client_id: "megooarti",
        client_secret: "s3cret",
        scopes: ["openid", "profile", "email"],
        require_verified_email: false,
        username_claim: "preferred_username",
        name_claim: "name",
        email_claim: "email",
        groups_claim: "groups",
      },
      group_mapping: [{ group: "developers", roles: ["deployers", "readers"] }],
    });
    expect(navigation.router.replace).toHaveBeenCalledWith("/admin/authentication/corp");
  });

  test("says what is wrong at each field, before it is sent and as the server says", async () => {
    const user = userEvent.setup();
    const { calls } = newSource({
      "POST /auth-sources": failure(422, "validation_error", "The request is not valid.", [
        { field: "settings.scopes", message: "Scopes are words without spaces or quotes." },
      ]),
    });

    await user.click(await screen.findByRole("button", { name: "Create source" }));
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(/1 to 64 letters/);
    expect(screen.getByLabelText("Issuer")).toHaveAccessibleDescription(/http or https/);
    expect(of(calls, "POST")).toHaveLength(0);

    await user.type(screen.getByLabelText("Name"), "Corp SSO");
    await user.type(screen.getByLabelText("Issuer"), "https://sso.example");
    await user.type(screen.getByLabelText("Client ID"), "megooarti");
    await user.click(screen.getByRole("button", { name: "Create source" }));

    await waitFor(() =>
      expect(screen.getByLabelText("Scopes")).toHaveAccessibleDescription(/without spaces/),
    );
  });

  test("says so of a row with a group and no role, and sends nothing", async () => {
    const user = userEvent.setup();
    const { calls } = newSource();

    await user.type(await screen.findByLabelText("Name"), "Corp SSO");
    await user.type(screen.getByLabelText("Issuer"), "https://sso.example/realms/corp");
    await user.type(screen.getByLabelText("Client ID"), "megooarti");
    await user.click(screen.getByRole("button", { name: "Give a group a role" }));
    await user.type(screen.getByLabelText("Group 1"), "developers");
    await user.click(screen.getByRole("button", { name: "Create source" }));

    expect(await screen.findByText("Each row needs a group and a role.")).toBeVisible();
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("is not offered to whoever may only read sources", () => {
    newSource({}, holding("admin:security:read"));

    expect(screen.queryByRole("button", { name: "Create source" })).toBeNull();
  });
});

describe("an OIDC source", () => {
  test("shows the address to register at the provider, to copy", async () => {
    oneSource();

    expect(await screen.findByText(CORP.redirect_uri)).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy Redirect address" })).toBeVisible();
    expect(screen.getByLabelText("Client secret")).toHaveAccessibleDescription(/Leave this empty/);
    await expectAccessible();
  });

  test("opens with what it has, its mapping a row a role, and keeps its secret when saved", async () => {
    const user = userEvent.setup();
    const { calls } = oneSource({
      "PUT /auth-sources/corp": (call) => ({ json: { ...CORP, ...(call.body as object) } }),
    });

    expect(await screen.findByLabelText("Scopes")).toHaveValue("openid profile email groups");
    expect(screen.getByLabelText("Group 1")).toHaveValue("developers");
    expect(screen.getByLabelText("Role 2")).toHaveValue("readers");
    await user.click(screen.getByRole("button", { name: "Remove row 1" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Saved Corp SSO."));
    const sent = of(calls, "PUT")[0]?.body as {
      settings: object;
      group_mapping: object;
      enabled: boolean;
    };
    expect(sent.enabled).toBe(true); // turned on and off on the list, not here
    expect(sent.settings).not.toHaveProperty("client_secret");
    expect(sent.group_mapping).toEqual([{ group: "developers", roles: ["readers"] }]);
  });

  test("is shown, and not changed, to whoever may only read it", async () => {
    oneSource({}, holding("admin:security:read"));

    expect(await screen.findByLabelText("Issuer")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  test("says what went wrong when it cannot be had", async () => {
    oneSource({ "GET /auth-sources/corp": failure(404, "not_found", "No such sign-in source.") });

    expect(await screen.findByRole("alert")).toHaveTextContent("This was not found.");
  });

  test("of another kind is said to be set up through the API", async () => {
    oneSource({
      "GET /auth-sources/corp": { json: { ...CORP, kind: "ldap", redirect_uri: null } },
    });

    expect(
      await screen.findByText("A source of the kind ldap is set up through the API."),
    ).toBeVisible();
    expect(within(document.body).queryByLabelText("Issuer")).toBeNull();
  });
});
