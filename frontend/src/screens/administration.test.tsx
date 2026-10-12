import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { BlobStoresScreen } from "./blob-stores";
import { ManageRepositoriesScreen } from "./manage-repositories";
import { NewRepositoryScreen, RepositorySettingsScreen } from "./repository-settings";
import { SystemScreen } from "./system";

const page = (items: unknown[], total = items.length) => ({ items, total, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });
/** The members a group's form shows, in their order. */
const members = () =>
  within(screen.getByRole("group", { name: "Members, in the order they are asked" }))
    .queryAllByRole("listitem")
    .map((item) => item.getAttribute("data-member"));

const repository = (name: string, more: Record<string, unknown> = {}) => ({
  name,
  format: "maven",
  type: "hosted",
  online: true,
  blob_store: "default",
  url_path: `/repository/${name}/`,
  hosted: { deployment_policy: "allow_redeploy" },
  format_config: { version_policy: "release", layout_policy: "strict" },
  proxy: null,
  group: null,
  status: null,
  ...more,
});
const proxy = (name: string, more: Record<string, unknown> = {}, status: object = {}) =>
  repository(name, {
    type: "proxy",
    hosted: null,
    proxy: {
      remote_url: "https://repo.example.org/maven2",
      content_max_age_minutes: 1440,
      metadata_max_age_minutes: 1440,
      negative_cache: { enabled: true, ttl_minutes: 1440 },
      remote_auth: { type: "basic", username: "robot", has_secret: true },
      blocked: false,
      auto_block: true,
      ...more,
    },
    status: { blocked: false, auto_blocked_until: null, failures: 0, last_error: null, ...status },
  });
const RELEASES = repository("releases");
const CENTRAL = proxy("central");
const ALL = repository("all", {
  type: "group",
  blob_store: null,
  hosted: null,
  format_config: {},
  group: { members: ["releases", "central"] },
});
const NPM = repository("npm-own", { format: "npm", format_config: {} });
const store = (name: string, more: Record<string, unknown> = {}) => ({
  name,
  type: "file",
  path: name,
  blob_count: 3,
  total_bytes: 2516582,
  available_bytes: 906238099456,
  ...more,
});
const STORES = [store("default"), store("fast", { path: "/mnt/fast", available_bytes: null })];

describe("the repositories as they are set up (R1)", () => {
  function list(more: Routes = {}, session = ADMIN, address = "/admin/repositories") {
    const api = mockApi({
      "GET /repositories": { json: page([ALL, CENTRAL, RELEASES]) },
      ...more,
    });
    navigation.at(address);
    return { ...renderUi(<ManageRepositoriesScreen />, { session }), ...api };
  }

  test("are listed with their format, type, state and blob store", async () => {
    const { calls } = list({
      "GET /repositories": {
        json: page([
          ALL,
          proxy("central", {}, { blocked: true }),
          proxy("mirror", {}, { auto_blocked_until: "2099-01-01T00:00:00Z", failures: 3 }),
          repository("releases", { online: false }),
        ]),
      },
    });

    const table = await screen.findByRole("table", { name: "Manage repositories" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(calls[0]?.path).toBe("/repositories?limit=50&offset=0");
    expect(within(rows[3] as HTMLElement).getByRole("link", { name: "releases" })).toHaveAttribute(
      "href",
      "/admin/repositories/releases",
    );
    expect(rows[0]).toHaveTextContent("Group");
    expect(rows[0]).toHaveTextContent("Online");
    expect(rows[1]).toHaveTextContent("Proxy");
    expect(rows[1]).toHaveTextContent("Blocked");
    expect(rows[2]).toHaveTextContent("Left alone after a failure");
    expect(rows[3]).toHaveTextContent("Offline");
    expect(rows[3]).toHaveTextContent("default");
    // The form for a new one is where no repository's name can be (R13).
    expect(screen.getByRole("link", { name: "New repository" })).toHaveAttribute(
      "href",
      "/admin/repositories/~new",
    );
    await expectAccessible();
  });

  test("say so when there is none, and offer no new one to whoever may only read", async () => {
    const first = list({ "GET /repositories": { json: page([]) } });
    expect(await screen.findByRole("heading", { name: "No repository yet" })).toBeVisible();
    first.unmount();

    list({}, holding("admin:repositories:read"));
    await screen.findByRole("table", { name: "Manage repositories" });
    expect(screen.queryByRole("link", { name: "New repository" })).toBeNull();
  });

  test("come a page at a time, with the keyboard at the list when a page is turned", async () => {
    const { rerender, calls } = list({ "GET /repositories": { json: page([RELEASES], 120) } });
    await screen.findByRole("table", { name: "Manage repositories" });

    navigation.at("/admin/repositories?page=2");
    rerender(<ManageRepositoriesScreen />);

    await waitFor(() =>
      expect(screen.getByRole("group", { name: "Manage repositories" })).toHaveFocus(),
    );
    expect(calls.map((call) => call.path)).toContain("/repositories?limit=50&offset=50");
    expect(screen.getByRole("navigation", { name: "Pages" })).toHaveTextContent("Page 2 of 3");
  });

  test("say what went wrong when they may not be seen", async () => {
    list({ "GET /repositories": failure(403, "forbidden", "No.") });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
  });
});

describe("a new repository (R2)", () => {
  function fresh(more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      "GET /repositories": { json: page([ALL, CENTRAL, NPM, RELEASES]) },
      "GET /blob-stores": { json: page(STORES) },
      "POST /repositories": (call) => ({
        status: 201,
        json: repository((call.body as { name: string }).name),
      }),
      ...more,
    });
    navigation.at("/admin/repositories/~new");
    return { ...renderUi(<NewRepositoryScreen />, { session }), ...api };
  }
  const create = () => screen.getByRole("button", { name: "Create repository" });
  const sent = (calls: Call[]) => of(calls, "POST")[0]?.body as Record<string, unknown>;

  test("is a hosted Maven one unless said otherwise, with the server's own defaults", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("Name"), "snapshots");
    await user.click(screen.getByRole("radio", { name: "Snapshot" }));
    await user.click(create());

    await waitFor(() =>
      expect(navigation.router.push).toHaveBeenCalledWith("/admin/repositories/snapshots"),
    );
    expect(sent(calls)).toEqual({
      name: "snapshots",
      format: "maven",
      type: "hosted",
      online: true,
      blob_store: "default",
      hosted: { deployment_policy: "allow_redeploy" },
      proxy: null,
      group: null,
      format_config: { version_policy: "snapshot", layout_policy: "strict" },
    });
    expect(notices()).toHaveTextContent("Created the repository snapshots.");
  });

  test("grows with what the type has, and shows nothing of another type", async () => {
    const user = userEvent.setup();
    fresh();

    expect(screen.getByRole("group", { name: "Deployment policy" })).toBeVisible();
    expect(screen.queryByLabelText("Remote address")).toBeNull();
    expect(
      screen.queryByRole("group", { name: "Members, in the order they are asked" }),
    ).toBeNull();

    await user.click(screen.getByRole("radio", { name: "Proxy" }));
    expect(screen.getByLabelText("Remote address")).toBeVisible();
    expect(screen.getByLabelText("Trust a cached file for (minutes)")).toHaveValue("1440");
    expect(screen.queryByRole("group", { name: "Deployment policy" })).toBeNull();
    expect(screen.getByRole("group", { name: "Layout policy" })).toBeVisible(); // Maven's own

    await user.click(screen.getByRole("radio", { name: "Group" }));
    expect(
      screen.getByRole("group", { name: "Members, in the order they are asked" }),
    ).toBeVisible();
    expect(screen.queryByLabelText("Remote address")).toBeNull();
    // A group stores nothing, and has no policy of its own.
    expect(screen.queryByLabelText("Blob store")).toBeNull();
    expect(screen.queryByRole("group", { name: "Layout policy" })).toBeNull();
    await expectAccessible();
  });

  test("has Maven's settings for Maven only", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.selectOptions(screen.getByLabelText("Format"), "npm");
    expect(screen.queryByRole("group", { name: "Version policy" })).toBeNull();
    await user.type(screen.getByLabelText("Name"), "npm-team");
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({ format: "npm", format_config: {} });
  });

  test("a proxy is made with its remote and how it signs in there", async () => {
    const user = userEvent.setup();
    const { calls, client } = fresh();

    await user.type(screen.getByLabelText("Name"), "mirror");
    await user.click(screen.getByRole("radio", { name: "Proxy" }));
    await user.type(screen.getByLabelText("Remote address"), "https://repo.example.org/maven2/");
    await user.selectOptions(screen.getByLabelText("Signs in to the remote with"), "basic");
    await user.type(screen.getByLabelText("User name"), "robot");
    const secret = screen.getByLabelText("Password");
    // Never shown as it is typed, and the browser is not to fill in one of its own.
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "new-password");
    await user.type(secret, "the-remote-secret");
    await user.clear(screen.getByLabelText("Trust a cached file for (minutes)"));
    await user.type(screen.getByLabelText("Trust a cached file for (minutes)"), "-1");
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({
      type: "proxy",
      hosted: null,
      proxy: {
        remote_url: "https://repo.example.org/maven2/",
        content_max_age_minutes: -1,
        metadata_max_age_minutes: 1440,
        negative_cache: { enabled: true, ttl_minutes: 1440 },
        remote_auth: { type: "basic", username: "robot", secret: "the-remote-secret" },
        blocked: false,
        auto_block: true,
      },
    });
    // The secret went to the server and is kept nowhere here: the store lets go of the
    // request that carried it as soon as it is answered.
    await waitFor(() => expect(navigation.router.push).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        JSON.stringify(
          client
            .getMutationCache()
            .getAll()
            .map((mutation) => mutation.state.variables),
        ),
      ).not.toContain("the-remote-secret"),
    );
  });

  test("a group is made of repositories of its own format, in the order they are put", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("Name"), "public");
    await user.click(screen.getByRole("radio", { name: "Group" }));
    const candidates = () =>
      within(screen.getByLabelText("A repository to add"))
        .getAllByRole("option")
        .map((option) => option.textContent);
    // Not the npm one: a group is of one format. Another group can be a member.
    await waitFor(() => expect(candidates()).toEqual(["all", "central", "releases"]));
    await user.selectOptions(screen.getByLabelText("A repository to add"), "releases");
    await user.click(screen.getByRole("button", { name: "Add it" }));
    await user.selectOptions(screen.getByLabelText("A repository to add"), "central");
    await user.click(screen.getByRole("button", { name: "Add it" }));
    await user.click(screen.getByRole("button", { name: "Move central up" }));
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({
      type: "group",
      blob_store: null,
      group: { members: ["central", "releases"] },
      format_config: {},
    });
  });

  test("members of one format are none of another: changing the format empties them", async () => {
    const user = userEvent.setup();
    fresh();
    await user.click(screen.getByRole("radio", { name: "Group" }));
    await waitFor(() => expect(screen.getByLabelText("A repository to add")).toBeVisible());
    await user.click(screen.getByRole("button", { name: "Add it" }));
    expect(members()).toHaveLength(1);

    await user.selectOptions(screen.getByLabelText("Format"), "npm");

    expect(members()).toHaveLength(0);
    expect(
      within(screen.getByLabelText("A repository to add")).getAllByRole("option"),
    ).toHaveLength(1); // npm-own
  });

  test("says what is wrong with what was typed, at each press at the first field that is wrong", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();
    await user.click(screen.getByRole("radio", { name: "Proxy" }));

    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "A repository's name is 1 to 64 letters, digits or . _ -",
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();

    await user.type(screen.getByLabelText("Name"), "mirror");
    await user.type(screen.getByLabelText("Remote address"), "repo.example.org");
    await user.click(create());
    expect(screen.getByLabelText("Remote address")).toHaveFocus();
    expect(screen.getByLabelText("Remote address")).toHaveAccessibleDescription(
      expect.stringContaining("Give an http or https address"),
    );
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("a Docker repository is named as images are, and one called . is none", async () => {
    const user = userEvent.setup();
    fresh();

    await user.selectOptions(screen.getByLabelText("Format"), "docker");
    await user.type(screen.getByLabelText("Name"), "Images");
    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      expect.stringContaining("the first part of its images' names"),
    );

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "..");
    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "A repository cannot be called . or .. : it would have no address.",
    );
  });

  test("says what the server refuses where it belongs, or whole", async () => {
    const user = userEvent.setup();
    const attempt = async () => {
      await user.type(screen.getByLabelText("Name"), "mirror");
      await user.click(screen.getByRole("radio", { name: "Proxy" }));
      await user.type(screen.getByLabelText("Remote address"), "https://repo.example.org");
      await user.click(create());
    };
    const first = fresh({
      "POST /repositories": failure(409, "conflict", "A repository named mirror already exists."),
    });
    await attempt();
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A repository named mirror already exists.",
      ),
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();
    first.unmount();

    const second = fresh({
      "POST /repositories": failure(422, "validation_error", "The request is not valid.", [
        { field: "proxy.remote_url", message: "Must be an http or https URL with a host." },
      ]),
    });
    await attempt();
    await waitFor(() =>
      expect(screen.getByLabelText("Remote address")).toHaveAccessibleDescription(
        "Must be an http or https URL with a host.",
      ),
    );
    second.unmount();

    fresh({
      "POST /repositories": failure(
        409,
        "repository_cycle",
        "A group cannot contain itself, directly or indirectly.",
      ),
    });
    await attempt();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A group cannot contain itself, directly or indirectly.",
    );
    expect(navigation.router.push).not.toHaveBeenCalled();
  });

  test("offers the blob stores there are, or the default one where they may not be seen", async () => {
    const first = fresh();
    const choices = () =>
      within(screen.getByLabelText("Blob store"))
        .getAllByRole("option")
        .map((option) => option.textContent);
    await waitFor(() => expect(choices()).toEqual(["default", "fast"]));
    first.unmount();

    const { calls } = fresh({}, holding("admin:repositories:read", "admin:repositories:write"));
    expect(choices()).toEqual(["default"]);
    expect(
      screen.getByText("You may not see the blob stores, so the default one is used."),
    ).toBeVisible();
    expect(calls.some((call) => call.path.startsWith("/blob-stores"))).toBe(false);
  });

  test("is not offered to whoever may not create one, though the address be typed", () => {
    fresh({}, holding("admin:repositories:read"));

    expect(screen.getByRole("alert")).toHaveTextContent("You may not create repositories.");
    expect(screen.queryByRole("button", { name: "Create repository" })).toBeNull();
  });
});

describe("the settings of a repository", () => {
  function settings(which = RELEASES, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      [`GET /repositories/${which.name}`]: { json: which },
      "GET /repositories": { json: page([ALL, CENTRAL, NPM, RELEASES]) },
      ...more,
    });
    navigation.at(`/admin/repositories/${which.name}`);
    return { ...renderUi(<RepositorySettingsScreen />, { session }), ...api };
  }
  const save = () => screen.getByRole("button", { name: "Save" });

  test("show what cannot change as facts, and the rest as it is set (R3)", async () => {
    settings(repository("releases", { hosted: { deployment_policy: "read_only" } }));

    expect(await screen.findByRole("heading", { level: 1, name: "releases" })).toBeVisible();
    for (const fact of ["maven", "Hosted", "default", "release", "/repository/releases/"]) {
      expect(screen.getAllByText(fact)[0]).toBeVisible();
    }
    // Not fields: a field that cannot be changed is one that will be tried.
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(screen.queryByLabelText("Format")).toBeNull();
    expect(screen.queryByRole("radio", { name: "Proxy" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Version policy" })).toBeNull();
    expect(screen.queryByLabelText("Blob store")).toBeNull();
    expect(screen.getByRole("radio", { name: "Read only" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Online" })).toBeChecked();
    expect(screen.getByRole("link", { name: "Browse it" })).toHaveAttribute(
      "href",
      "/browse/releases",
    );
    await expectAccessible();
  });

  test("are saved as they stand, and say so", async () => {
    const user = userEvent.setup();
    const { calls } = settings(RELEASES, {
      "PUT /repositories/releases": { json: repository("releases", { online: false }) },
    });
    await screen.findByRole("radio", { name: "Allow redeploy" });

    await user.click(screen.getByRole("checkbox", { name: "Online" }));
    await user.click(screen.getByRole("radio", { name: "Disable redeploy" }));
    await user.click(screen.getByRole("radio", { name: "Permissive" }));
    await user.click(save());

    await waitFor(() => expect(notices()).toHaveTextContent("Saved the repository releases."));
    expect(of(calls, "PUT")[0]?.body).toEqual({
      online: false,
      hosted: { deployment_policy: "disable_redeploy" },
      proxy: null,
      group: null,
      format_config: { version_policy: "release", layout_policy: "permissive" },
    });
    expect(save()).toHaveFocus();
  });

  test("of a proxy keep the secret that is stored, which is shown to nobody (R4)", async () => {
    const user = userEvent.setup();
    const { calls } = settings(CENTRAL, { "PUT /repositories/central": { json: CENTRAL } });
    const secret = await screen.findByLabelText("Password");

    expect(secret).toHaveValue("");
    expect(secret).toHaveAccessibleDescription(
      "One is stored. Leave this empty to keep it, or type another to replace it.",
    );
    expect(screen.getByLabelText("Remote address")).toHaveValue("https://repo.example.org/maven2");
    expect(screen.getByLabelText("User name")).toHaveValue("robot");
    await user.click(save());

    await waitFor(() => expect(of(calls, "PUT")).toHaveLength(1));
    expect(
      (of(calls, "PUT")[0]?.body as { proxy: { remote_auth: unknown } }).proxy.remote_auth,
    ).toEqual({ type: "basic", username: "robot", secret: null });
  });

  test("of a proxy send a secret that is typed, and then keep it nowhere", async () => {
    const user = userEvent.setup();
    const { calls, client } = settings(CENTRAL, {
      "PUT /repositories/central": { json: CENTRAL },
    });

    await user.type(await screen.findByLabelText("Password"), "another-secret");
    await user.click(save());

    await waitFor(() => expect(notices()).toHaveTextContent("Saved the repository central."));
    expect(JSON.stringify(of(calls, "PUT")[0]?.body)).toContain("another-secret");
    // The field starts again from what the server holds, and the store lets go of what was sent.
    expect(screen.getByLabelText("Password")).toHaveValue("");
    await waitFor(() =>
      expect(
        JSON.stringify([
          client
            .getMutationCache()
            .getAll()
            .map((mutation) => mutation.state.variables),
          client
            .getQueryCache()
            .getAll()
            .map((query) => query.state.data),
        ]),
      ).not.toContain("another-secret"),
    );
  });

  test("say where the server wants the secret again", async () => {
    const user = userEvent.setup();
    settings(CENTRAL, {
      "PUT /repositories/central": failure(422, "validation_error", "The request is not valid.", [
        { field: "proxy.remote_auth.secret", message: "A secret is required." },
      ]),
    });
    const remote = await screen.findByLabelText("Remote address");

    await user.clear(remote);
    await user.type(remote, "https://other.example.org");
    await user.click(save());

    // The remote changed, so the server keeps the secret it was given for the old one to itself.
    await waitFor(() =>
      expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
        "A secret is required.",
      ),
    );
    expect(screen.getByLabelText("Password")).toHaveFocus();
  });

  test("of a proxy show what it last met at its remote, as text (R7)", async () => {
    const hostile = '<img src=x onerror="alert(1)"> 503 from https://repo.example.org';
    const { container } = settings(
      proxy(
        "central",
        {},
        { auto_blocked_until: "2099-01-01T00:00:00Z", failures: 4, last_error: hostile },
      ),
    );

    expect(await screen.findByText("Left alone after a failure")).toBeVisible();
    expect(screen.getByText(hostile)).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("4")).toBeVisible();
    await expectAccessible();
  });

  test("of a proxy have everything checked again when asked", async () => {
    const user = userEvent.setup();
    const { calls } = settings(proxy("central", { blocked: true }, { blocked: true }), {
      "POST /repositories/central/invalidate-cache": { status: 204 },
    });

    expect(await screen.findByText("Blocked")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Check everything again" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("central will check everything with its remote again."),
    );
    expect(of(calls, "POST").map((call) => call.path)).toEqual([
      "/repositories/central/invalidate-cache",
    ]);
  });

  test("rebuild the index and say what was found (R8)", async () => {
    const user = userEvent.setup();
    settings(RELEASES, {
      "POST /repositories/releases/rebuild-index": {
        json: { files: 120, moved: 2, components: 40, removed: 1 },
      },
    });

    await user.click(await screen.findByRole("button", { name: "Rebuild the index" }));

    expect(await screen.findByText("The index is rebuilt")).toBeVisible();
    expect(
      screen.getByText(
        "120 files looked at, 2 given to another component. 40 components looked at, 1 removed for having no file left.",
      ),
    ).toBeVisible();
  });

  test("of a group are its members, and it has no index and no remote", async () => {
    const user = userEvent.setup();
    const { calls } = settings(ALL, { "PUT /repositories/all": { json: ALL } });

    await screen.findByRole("group", { name: "Members, in the order they are asked" });
    expect(members()).toEqual(["releases", "central"]);
    expect(screen.queryByRole("heading", { name: "Rebuild the index" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "The remote" })).toBeNull();
    // Itself is not offered as a member of itself.
    expect(screen.queryByLabelText("A repository to add")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Move central up" }));
    await user.click(save());
    await waitFor(() => expect(of(calls, "PUT")).toHaveLength(1));
    expect(of(calls, "PUT")[0]?.body).toMatchObject({
      group: { members: ["central", "releases"] },
      format_config: {},
    });
  });

  test("open with what the server holds now, and not with what was fetched before (A23)", async () => {
    let policy = "allow_redeploy";
    const held = () => repository("releases", { hosted: { deployment_policy: policy } });
    const { rerender } = settings(RELEASES, {
      "GET /repositories/releases": () => ({ json: held() }),
    });
    expect(await screen.findByRole("radio", { name: "Allow redeploy" })).toBeChecked();

    rerender(<p>Elsewhere</p>);
    policy = "read_only";
    rerender(<RepositorySettingsScreen />);

    await waitFor(() => expect(screen.getByRole("radio", { name: "Read only" })).toBeChecked());
  });

  test("are shown, and not changed, by whoever may only read them", async () => {
    settings(CENTRAL, {}, holding("admin:repositories:read"));

    expect(await screen.findByLabelText("Remote address")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Check everything again" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Rebuild the index" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete repository" })).toBeNull();
    expect(screen.getByRole("heading", { name: "The remote" })).toBeVisible(); // its state can be seen
  });

  test("delete the repository only for whoever types its name, and say what goes with it (R9)", async () => {
    const user = userEvent.setup();
    const { calls } = settings(RELEASES, { "DELETE /repositories/releases": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete repository" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the repository releases?" });
    expect(dialog).toHaveTextContent("Every component and file in it is deleted");
    const confirm = within(dialog).getByRole("button", { name: "Delete repository" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Type releases to go on"), "releases");
    await user.click(confirm);

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/admin/repositories"),
    );
    expect(notices()).toHaveTextContent("Deleted the repository releases.");
    await new Promise((resolve) => setTimeout(resolve, 50));
    const since = calls.slice(calls.findIndex((call) => call.method === "DELETE") + 1);
    expect(since.filter((call) => call.path === "/repositories/releases")).toEqual([]);
  });

  test("say why when it could not be deleted, or is not there", async () => {
    const user = userEvent.setup();
    const first = settings(RELEASES, {
      "DELETE /repositories/releases": failure(
        409,
        "in_use",
        "The group all presents this repository.",
      ),
    });
    await user.click(await screen.findByRole("button", { name: "Delete repository" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type releases to go on"), "releases");
    await user.click(within(dialog).getByRole("button", { name: "Delete repository" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The group all presents this repository.",
    );
    first.unmount();

    settings(RELEASES, {
      "GET /repositories/releases": failure(404, "not_found", "No such repository."),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("This was not found.");
  });
});

describe("the blob stores (R10)", () => {
  function stores(more: Routes = {}, session = ADMIN) {
    const api = mockApi({ "GET /blob-stores": { json: page(STORES) }, ...more });
    navigation.at("/admin/blob-stores");
    return { ...renderUi(<BlobStoresScreen />, { session }), ...api };
  }
  const create = () => screen.getByRole("button", { name: "Create blob store" });

  test("are listed with what they hold and the space that is left", async () => {
    stores();

    const table = await screen.findByRole("table", { name: "Blob stores" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(rows[0]).toHaveTextContent("default");
    expect(rows[0]).toHaveTextContent("2.4 MiB");
    expect(rows[0]).toHaveTextContent("844 GiB");
    expect(rows[1]).toHaveTextContent("/mnt/fast");
    expect(rows[1]).toHaveTextContent("Not known"); // where the server cannot say
    await expectAccessible();
  });

  test("a new one needs a name, and a directory only if it is to be elsewhere", async () => {
    const user = userEvent.setup();
    const { calls } = stores({
      "POST /blob-stores": (call) => ({
        status: 201,
        json: store((call.body as { name: string }).name),
      }),
    });
    await screen.findByRole("table", { name: "Blob stores" });

    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "A blob store's name is 1 to 64 letters, digits or . _ -",
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(of(calls, "POST")).toHaveLength(0);

    await user.type(screen.getByLabelText("Name"), "second");
    await user.click(create());
    await waitFor(() => expect(notices()).toHaveTextContent("Created the blob store second."));
    expect(of(calls, "POST")[0]?.body).toEqual({ name: "second", type: "file", path: null });
    // Ready for another: empty, with nothing said to be wrong with it.
    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Name")).not.toHaveAttribute("aria-invalid");

    await user.type(screen.getByLabelText("Name"), "third");
    await user.type(screen.getByLabelText("Directory"), " /mnt/third ");
    await user.click(create());
    await waitFor(() => expect(of(calls, "POST")).toHaveLength(2));
    expect(of(calls, "POST")[1]?.body).toEqual({ name: "third", type: "file", path: "/mnt/third" });
  });

  test("says what the server refuses of a new one where it belongs", async () => {
    const user = userEvent.setup();
    const first = stores({
      "POST /blob-stores": failure(409, "conflict", "A blob store named fast already exists."),
    });
    await user.type(await screen.findByLabelText("Name"), "fast");
    await user.click(create());
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A blob store named fast already exists.",
      ),
    );
    first.unmount();

    stores({
      "POST /blob-stores": failure(422, "validation_error", "The request is not valid.", [
        { field: "path", message: "The directory overlaps the blob store default." },
      ]),
    });
    await user.type(await screen.findByLabelText("Name"), "inside");
    await user.type(screen.getByLabelText("Directory"), "default/inside");
    await user.click(create());
    await waitFor(() =>
      expect(screen.getByLabelText("Directory")).toHaveAccessibleDescription(
        "The directory overlaps the blob store default.",
      ),
    );
    expect(screen.getByLabelText("Directory")).toHaveFocus();
  });

  test("is deleted only by whoever types its name, and the keyboard is then at the list (R9)", async () => {
    const user = userEvent.setup();
    let held = STORES;
    const { calls } = stores({
      "GET /blob-stores": () => ({ json: page(held) }),
      "DELETE /blob-stores/fast": () => {
        held = [STORES[0] as (typeof STORES)[number]];
        return { status: 204 };
      },
    });

    await user.click(await screen.findByRole("button", { name: "Delete fast" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the blob store fast?" });
    expect(dialog).toHaveTextContent("Its files stay on the disk");
    const confirm = within(dialog).getByRole("button", { name: "Delete blob store" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Type fast to go on"), "fast");
    await user.click(confirm);

    await waitFor(() => expect(notices()).toHaveTextContent("Deleted the blob store fast."));
    expect(of(calls, "DELETE")).toHaveLength(1);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Delete fast" })).toBeNull());
    await waitFor(() => expect(screen.getByRole("group", { name: "Blob stores" })).toHaveFocus());
  });

  test("is not deleted while a repository uses it, and the screen says which", async () => {
    const user = userEvent.setup();
    stores({
      "DELETE /blob-stores/default": failure(
        409,
        "in_use",
        "The repository releases uses this blob store.",
      ),
    });

    await user.click(await screen.findByRole("button", { name: "Delete default" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type default to go on"), "default");
    await user.click(within(dialog).getByRole("button", { name: "Delete blob store" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The repository releases uses this blob store.",
    );
  });

  test("are shown, and neither made nor deleted, by whoever may only read them", async () => {
    stores({}, holding("admin:blobstores:read"));

    await screen.findByRole("table", { name: "Blob stores" });

    expect(screen.queryByRole("button", { name: "Create blob store" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Delete/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Delete" })).toBeNull();
  });
});

describe("the system (R11)", () => {
  const INFORMATION = {
    version: "0.1.0",
    schema: { revision: "0007", expected: "0007", current: true },
    runtime: {
      python: "3.13.1",
      platform: "Linux-6.6-x86_64-with-glibc2.41",
      started_at: "2026-10-12T08:00:00Z",
    },
    database: { version: "PostgreSQL 17.2" },
  };
  function system(more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      "GET /system/information": { json: INFORMATION },
      "GET /settings": { json: { base_url: null, anonymous_access: { enabled: false } } },
      "GET /blob-stores": { json: page(STORES) },
      "GET /content": { json: page([]) },
      ...more,
    });
    navigation.at("/admin/system");
    return { ...renderUi(<SystemScreen />, { session }), ...api };
  }
  const field = () => screen.getByLabelText("The address of this server, as its clients reach it");

  test("says what is running, and that the schema is the one this version expects", async () => {
    system();

    expect(await screen.findByText("As this version expects")).toBeVisible();
    for (const said of [
      "0.1.0",
      "0007",
      "3.13.1",
      "Linux-6.6-x86_64-with-glibc2.41",
      "PostgreSQL 17.2",
    ]) {
      expect(screen.getByText(said)).toBeVisible();
    }
    // And the blob stores' state, for whoever may see them.
    const table = await screen.findByRole("table", { name: "Blob stores" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).queryByRole("button")).toBeNull(); // they are managed on their own page
    expect(screen.getByRole("link", { name: "Manage the blob stores" })).toHaveAttribute(
      "href",
      "/admin/blob-stores",
    );
    await expectAccessible();
  });

  test("says so when the schema is another one, and which this version expects", async () => {
    system({
      "GET /system/information": {
        json: { ...INFORMATION, schema: { revision: "0005", expected: "0007", current: false } },
      },
    });

    expect(await screen.findByText("This version expects 0007")).toBeVisible();
    expect(screen.getByText("0005")).toBeVisible();
    expect(screen.queryByText("As this version expects")).toBeNull();
  });

  test("sets the base URL, as the server then keeps it", async () => {
    const user = userEvent.setup();
    const { calls } = system({
      "PUT /settings/base-url": {
        json: { base_url: "https://repo.example.org", anonymous_access: { enabled: false } },
      },
    });
    await waitFor(() => expect(field()).toHaveValue(""));

    await user.type(field(), "repo.example.org");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(field()).toHaveAccessibleDescription(
      "Give an http or https address, without a query or a fragment.",
    );
    expect(field()).toHaveFocus();
    expect(of(calls, "PUT")).toHaveLength(0);

    await user.clear(field());
    await user.type(field(), " https://repo.example.org/ ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("The base URL is saved."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ base_url: "https://repo.example.org/" });
    expect(field()).toHaveValue("https://repo.example.org"); // without the slash, as it is kept
  });

  test("clears the base URL when the field is emptied", async () => {
    const user = userEvent.setup();
    const { calls } = system({
      "GET /settings": {
        json: { base_url: "https://repo.example.org", anonymous_access: { enabled: false } },
      },
      "PUT /settings/base-url": {
        json: { base_url: null, anonymous_access: { enabled: false } },
      },
    });
    await waitFor(() => expect(field()).toHaveValue("https://repo.example.org"));

    await user.clear(field());
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("The base URL is cleared."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ base_url: null });
  });

  test("says what the server refuses of the base URL at its field", async () => {
    const user = userEvent.setup();
    system({
      "PUT /settings/base-url": failure(422, "validation_error", "The request is not valid.", [
        { field: "body.base_url", message: "Value error, must be an http or https URL" },
      ]),
    });
    await waitFor(() => expect(field()).toHaveValue(""));

    await user.type(field(), "https://repo.example.org");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(field()).toHaveAccessibleDescription("Value error, must be an http or https URL"),
    );
  });

  test("shows the base URL, and not the blob stores, to whoever may only read the settings", async () => {
    const { calls } = system({}, holding("admin:settings:read"));

    await waitFor(() => expect(field()).toBeDisabled());

    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("table", { name: "Blob stores" })).toBeNull();
    expect(calls.some((call) => call.path.startsWith("/blob-stores"))).toBe(false);
  });

  test("says what went wrong when the information cannot be had", async () => {
    system({ "GET /system/information": failure(500, "internal_error", "Oops.") });

    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
  });
});
