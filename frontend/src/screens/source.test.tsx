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

function oneSource(more: Routes = {}, session = ADMIN, id = "corp") {
  const api = mockApi({
    "GET /auth-sources/corp": { json: CORP },
    "GET /roles": { json: ROLES },
    ...more,
  });
  navigation.at(`/admin/authentication/${id}`);
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
      "GET /auth-sources/corp": { json: { ...CORP, kind: "saml", redirect_uri: null } },
    });

    expect(
      await screen.findByText("A source of the kind saml is set up through the API."),
    ).toBeVisible();
    expect(within(document.body).queryByLabelText("Issuer")).toBeNull();
  });
});

describe("an LDAP source (spec 7)", () => {
  const DIRECTORY = {
    ...CORP,
    id: "directory",
    kind: "ldap",
    name: "Corp LDAP",
    settings: {
      url: "ldap://ldap.corp.example",
      starttls: true,
      bind_dn: "cn=reader,dc=corp,dc=example",
      user_base: "ou=people,dc=corp,dc=example",
      user_filter: "(uid={username})",
      groups: "search",
      username_attribute: "uid",
      name_attribute: "cn",
      email_attribute: "mail",
      member_of_attribute: "memberOf",
      group_base: "ou=groups,dc=corp,dc=example",
      group_filter: "(member={dn})",
      group_name_attribute: "cn",
    },
    secrets: ["bind_password"],
    redirect_uri: null,
  };

  test("is made with its directory's settings, its groups found as chosen", async () => {
    const user = userEvent.setup();
    const { calls } = newSource({
      "POST /auth-sources": (call) => ({
        status: 201,
        json: { ...DIRECTORY, ...(call.body as object) },
      }),
    });

    await user.click(await screen.findByRole("radio", { name: /LDAP/ }));
    await user.type(screen.getByLabelText("Name"), "Corp LDAP");
    await user.type(screen.getByLabelText("Address"), "ldap://ldap.corp.example");
    await user.click(screen.getByRole("checkbox", { name: "StartTLS" }));
    await user.type(screen.getByLabelText("Bind DN"), "cn=reader,dc=corp,dc=example");
    await user.type(screen.getByLabelText("Bind password"), "s3cret");
    await user.type(screen.getByLabelText("Users' base DN"), "ou=people,dc=corp,dc=example");
    expect(screen.queryByLabelText("Groups' base DN")).toBeNull();
    await user.click(screen.getByRole("radio", { name: /From a search/ }));
    await user.type(screen.getByLabelText("Groups' base DN"), "ou=groups,dc=corp,dc=example");
    await expectAccessible();
    await user.click(screen.getByRole("button", { name: "Create source" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Created the sign-in source Corp LDAP."),
    );
    expect(of(calls, "POST")[0]?.body).toEqual({
      kind: "ldap",
      name: "Corp LDAP",
      enabled: false,
      settings: {
        url: "ldap://ldap.corp.example",
        starttls: true,
        bind_dn: "cn=reader,dc=corp,dc=example",
        bind_password: "s3cret",
        user_base: "ou=people,dc=corp,dc=example",
        user_filter: "(uid={username})",
        username_attribute: "uid",
        name_attribute: "cn",
        email_attribute: "mail",
        groups: "search",
        group_base: "ou=groups,dc=corp,dc=example",
        group_filter: "(member={dn})",
        group_name_attribute: "cn",
      },
      group_mapping: [],
    });
  });

  test("says what is wrong with its address, its base and its filter before sending", async () => {
    const user = userEvent.setup();
    const { calls } = newSource();

    await user.click(await screen.findByRole("radio", { name: /LDAP/ }));
    await user.type(screen.getByLabelText("Name"), "Corp LDAP");
    await user.type(screen.getByLabelText("Address"), "https://ldap.corp.example");
    await user.clear(screen.getByLabelText("Users' filter"));
    await user.type(screen.getByLabelText("Users' filter"), "(uid=kim)");
    await user.click(screen.getByRole("button", { name: "Create source" }));

    expect(screen.getByLabelText("Address")).toHaveAccessibleDescription(/ldap:\/\/ or ldaps:\/\//);
    expect(screen.getByLabelText("Users' base DN")).toHaveAccessibleDescription(
      /base DN is needed/,
    );
    expect(screen.getByLabelText("Users' filter")).toHaveAccessibleDescription(/must name/);
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("opens with what it has, and keeps its bind password when saved", async () => {
    const user = userEvent.setup();
    const { calls } = oneSource(
      {
        "GET /auth-sources/directory": { json: DIRECTORY },
        "PUT /auth-sources/directory": (call) => ({
          json: { ...DIRECTORY, ...(call.body as object) },
        }),
      },
      ADMIN,
      "directory",
    );

    expect(await screen.findByLabelText("Address")).toHaveValue("ldap://ldap.corp.example");
    expect(screen.getByRole("checkbox", { name: "StartTLS" })).toBeChecked();
    expect(screen.getByLabelText("Groups' base DN")).toHaveValue("ou=groups,dc=corp,dc=example");
    expect(screen.getByLabelText("Bind password")).toHaveAccessibleDescription(/Leave this empty/);
    expect(screen.queryByText("Redirect address")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Saved Corp LDAP."));
    const sent = of(calls, "PUT")[0]?.body as { settings: Record<string, unknown> };
    expect(sent.settings).not.toHaveProperty("bind_password");
    expect(sent.settings.groups).toBe("search");
  });
});

describe("a trusted header source (spec 8)", () => {
  test("is made with the headers that name a person and their groups", async () => {
    const user = userEvent.setup();
    const { calls } = newSource({
      "POST /auth-sources": (call) => ({
        status: 201,
        json: {
          ...CORP,
          id: "proxy",
          kind: "header",
          ...(call.body as object),
          redirect_uri: null,
        },
      }),
    });

    await user.click(await screen.findByRole("radio", { name: /Trusted header/ }));
    await user.type(screen.getByLabelText("Name"), "Corp SSO proxy");
    expect(screen.getByLabelText("User name header")).toHaveValue("X-Forwarded-User");
    await user.type(screen.getByLabelText("Groups header"), "X-Forwarded-Groups");
    await expectAccessible();
    await user.click(screen.getByRole("button", { name: "Create source" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("Created the sign-in source Corp SSO proxy."),
    );
    expect(of(calls, "POST")[0]?.body).toEqual({
      kind: "header",
      name: "Corp SSO proxy",
      enabled: false,
      settings: { user_header: "X-Forwarded-User", groups_header: "X-Forwarded-Groups" },
      group_mapping: [],
    });
  });

  test("needs the header that names a person, and sends no groups header left empty", async () => {
    const user = userEvent.setup();
    const { calls } = newSource({
      "POST /auth-sources": (call) => ({
        status: 201,
        json: {
          ...CORP,
          id: "proxy",
          kind: "header",
          ...(call.body as object),
          redirect_uri: null,
        },
      }),
    });

    await user.click(await screen.findByRole("radio", { name: /Trusted header/ }));
    await user.type(screen.getByLabelText("Name"), "Proxy");
    await user.clear(screen.getByLabelText("User name header"));
    await user.click(screen.getByRole("button", { name: "Create source" }));
    expect(screen.getByLabelText("User name header")).toHaveAccessibleDescription(/is needed/);
    expect(of(calls, "POST")).toHaveLength(0);

    await user.type(screen.getByLabelText("User name header"), "X-Remote-User");
    await user.click(screen.getByRole("button", { name: "Create source" }));

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect((of(calls, "POST")[0]?.body as { settings: object }).settings).toEqual({
      user_header: "X-Remote-User",
      groups_header: null,
    });
  });
});
