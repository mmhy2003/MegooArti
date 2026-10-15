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
/** A repository as the browsing screens have it: with the address its clients use. */
const view = (of: { name: string; format: string; type: string }, url?: string) => ({
  name: of.name,
  format: of.format,
  type: of.type,
  online: true,
  members: null,
  url: url ?? `https://ui.test/repository/${of.name}/`,
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
/** A repository's signing key, as the API shows it. */
const KEY = {
  kind: "openpgp",
  algorithm: "ed25519",
  fingerprint: "0F1E2D3C4B5A69788796A5B4C3D2E1F00F1E2D3C",
  public_key: "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nmDMEZ\n-----END PGP PUBLIC KEY BLOCK-----\n",
  created_at: "2026-10-01T09:30:00Z",
};
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

  test("starts with the policy the server gives it, and follows the form until one is chosen (H1)", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();
    const policy = (name: string) => screen.getByRole("radio", { name });

    // A Maven repository for releases: a release is deployed once.
    expect(policy("Disable redeploy")).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Snapshot" }));
    expect(policy("Allow redeploy")).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Release" }));
    expect(policy("Disable redeploy")).toBeChecked();
    await user.selectOptions(screen.getByLabelText("Format"), "npm");
    expect(policy("Allow redeploy")).toBeChecked();

    // Once chosen it is the person's, whatever the form then becomes.
    await user.click(policy("Read only"));
    await user.selectOptions(screen.getByLabelText("Format"), "maven");
    expect(policy("Read only")).toBeChecked();

    await user.type(screen.getByLabelText("Name"), "frozen");
    await user.click(create());
    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls).hosted).toEqual({ deployment_policy: "read_only" });
  });

  test("keeps the policy that is shown once it is pressed, whatever is changed after (H1)", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();
    const follows = "Until you choose one, this follows the format and the version policy.";

    // Not yet a choice, and the form says so: it would change with the version policy.
    expect(screen.getByText(follows)).toBeVisible();
    await user.click(screen.getByRole("radio", { name: "Disable redeploy" })); // the one shown
    expect(screen.queryByText(follows)).toBeNull();

    await user.click(screen.getByRole("radio", { name: "Mixed" }));
    expect(screen.getByRole("radio", { name: "Disable redeploy" })).toBeChecked();
    await user.type(screen.getByLabelText("Name"), "both");
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({
      hosted: { deployment_policy: "disable_redeploy" },
      format_config: { version_policy: "mixed" },
    });
  });

  test("a Maven repository for releases is made refusing redeploy when nothing is chosen (H1)", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("Name"), "releases");
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({
      format: "maven",
      hosted: { deployment_policy: "disable_redeploy" },
      format_config: { version_policy: "release", layout_policy: "strict" },
    });
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

  test("a group is offered every repository of its format, however many there are", async () => {
    const user = userEvent.setup();
    const others = Array.from({ length: 200 }, (_, index) =>
      repository(`npm-${index}`, { format: "npm", format_config: {} }),
    );
    const { calls } = fresh({
      "GET /repositories": (call) =>
        call.path.includes("offset=200")
          ? { json: { items: [repository("the-last")], total: 201, limit: 200, offset: 200 } }
          : { json: { items: others, total: 201, limit: 200, offset: 0 } },
    });

    await user.click(screen.getByRole("radio", { name: "Group" }));

    // The one Maven repository is the last of them all, beyond what one request brings.
    await waitFor(() =>
      expect(screen.getByLabelText("A repository to add")).toHaveValue("the-last"),
    );
    expect(
      calls.map((call) => call.path).filter((path) => path.startsWith("/repositories")),
    ).toEqual(["/repositories?limit=200&offset=0", "/repositories?limit=200&offset=200"]);
  });

  test("says so when the repositories cannot be had, and not that there are none", async () => {
    const user = userEvent.setup();
    let fails = true;
    fresh({
      "GET /repositories": () =>
        fails ? failure(500, "internal_error", "Broken.") : { json: page([RELEASES]) },
    });

    await user.click(screen.getByRole("radio", { name: "Group" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The server met a fault.");
    expect(screen.queryByText("There is no other repository of this format to add.")).toBeNull();
    // Members that are there can still be put in order, and the list is asked for again.
    fails = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getByLabelText("A repository to add")).toHaveValue("releases"),
    );
  });

  test("asks for the other repositories only for a group, which has members", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();
    const asked = () => calls.filter((call) => call.path.startsWith("/repositories")).length;
    await waitFor(() =>
      expect(calls.some((call) => call.path.startsWith("/blob-stores"))).toBe(true),
    );

    expect(asked()).toBe(0);
    await user.click(screen.getByRole("radio", { name: "Group" }));
    await waitFor(() => expect(asked()).toBe(1));
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
    // The keyboard is moved after the refusal is drawn, not with it.
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveFocus());
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

  test("offers APT, YUM and apk among the formats", () => {
    fresh();

    const formats = within(screen.getByLabelText("Format"))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(formats).toEqual(expect.arrayContaining(["apt", "yum", "apk"]));
  });

  test("a hosted APT repository is made with the suite that is typed, which is checked first", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.selectOptions(screen.getByLabelText("Format"), "apt");
    const suite = screen.getByLabelText("Suite");
    expect(suite).toHaveValue("stable"); // the server's own
    await user.type(screen.getByLabelText("Name"), "apt-own");
    await user.clear(suite);
    await user.type(suite, "-trixie");
    await user.click(create());
    expect(suite).toHaveAccessibleDescription(
      "A suite is 1 to 64 letters, digits or . _ - , and begins with a letter or a digit.",
    );
    expect(of(calls, "POST")).toHaveLength(0);

    await user.clear(suite);
    await user.type(suite, "trixie");
    await user.click(create());
    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({ format: "apt", format_config: { suite: "trixie" } });
  });

  test("a hosted YUM repository is made with the depth of its metadata", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.selectOptions(screen.getByLabelText("Format"), "yum");
    const depth = screen.getByLabelText("Depth of the metadata");
    expect(depth).toHaveValue("0");
    await user.type(screen.getByLabelText("Name"), "yum-own");
    await user.clear(depth);
    await user.type(depth, "6");
    await user.click(create());
    expect(depth).toHaveAccessibleDescription("A whole number from 0 to 5.");

    await user.clear(depth);
    await user.type(depth, "2");
    await user.click(create());
    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({ format: "yum", format_config: { repodata_depth: 2 } });
  });

  test("a proxy of APT, YUM or apk is given its remote's keys, and told why", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.selectOptions(screen.getByLabelText("Format"), "apk");
    await user.click(screen.getByRole("radio", { name: "Proxy" }));
    expect(screen.queryByLabelText("Suite")).toBeNull();
    const keys = screen.getByLabelText("The remote's public keys");
    expect(keys).toHaveAccessibleDescription(
      /Alpine's are in \/usr\/share\/apk\/keys\. A group checks what this proxy fetched with them: without them, it cannot be a member of one\./,
    );
    await user.selectOptions(screen.getByLabelText("Format"), "yum");
    expect(screen.getByLabelText("The remote's public keys")).toHaveAccessibleDescription(
      /They are not needed: dnf checks each package's own signature\./,
    );
    await user.selectOptions(screen.getByLabelText("Format"), "apt");
    await user.type(screen.getByLabelText("Name"), "apt-debian");
    await user.type(screen.getByLabelText("Remote address"), "http://deb.debian.org/debian");
    await user.type(screen.getByLabelText("The remote's public keys"), "the keys");
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({
      format: "apt",
      type: "proxy",
      format_config: { remote_keys: "the keys" },
    });
    await expectAccessible();
  });

  test("says where the server refuses a suite, a depth or a remote's keys", async () => {
    const user = userEvent.setup();
    fresh({
      "POST /repositories": failure(422, "validation_error", "The request is not valid.", [
        { field: "format_config.remote_keys", message: "These are not public keys." },
      ]),
    });

    await user.selectOptions(screen.getByLabelText("Format"), "apt");
    await user.click(screen.getByRole("radio", { name: "Proxy" }));
    await user.type(screen.getByLabelText("Name"), "apt-debian");
    await user.type(screen.getByLabelText("Remote address"), "http://deb.debian.org/debian");
    await user.type(screen.getByLabelText("The remote's public keys"), "nonsense");
    await user.click(create());

    await waitFor(() =>
      expect(screen.getByLabelText("The remote's public keys")).toHaveAccessibleDescription(
        "These are not public keys.",
      ),
    );
    expect(screen.queryByRole("alert")).toBeNull();
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

  test("says so when the blob stores cannot be had", async () => {
    fresh({ "GET /blob-stores": failure(500, "internal_error", "Broken.") });

    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
    // The default one is always there to be used.
    expect(screen.getByLabelText("Blob store")).toHaveValue("default");
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
      [`GET /content/${which.name}`]: { json: view(which) },
      "GET /repositories": { json: page([ALL, CENTRAL, NPM, RELEASES]) },
      ...more,
    });
    navigation.at(`/admin/repositories/${which.name}`);
    return { ...renderUi(<RepositorySettingsScreen />, { session }), ...api };
  }
  const save = () => screen.getByRole("button", { name: "Save" });

  test("say nothing of a policy that follows: the one a repository has is its own", async () => {
    settings();

    await screen.findByRole("radio", { name: "Allow redeploy" });
    expect(
      screen.queryByText("Until you choose one, this follows the format and the version policy."),
    ).toBeNull();
  });

  test("show what cannot change as facts, and the rest as it is set (R3)", async () => {
    settings(repository("releases", { hosted: { deployment_policy: "read_only" } }));

    expect(await screen.findByRole("heading", { level: 1, name: "releases" })).toBeVisible();
    for (const fact of ["maven", "Hosted", "default", "release"]) {
      expect(screen.getAllByText(fact)[0]).toBeVisible();
    }
    // The address its clients use, whole: what is copied is what a client is given.
    expect(await screen.findByText("https://ui.test/repository/releases/")).toBeVisible();
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

  test("show the address a registry has of its own, and none to whoever may not browse it", async () => {
    const images = repository("images", { format: "docker", format_config: {} });
    const first = settings(images, {
      "GET /content/images": { json: view(images, "ui.test/images") },
    });

    expect(await screen.findByText("ui.test/images")).toBeVisible();
    // Not the path the other formats are served under: a registry answers 404 there.
    expect(screen.queryByText("/repository/images/")).toBeNull();
    first.unmount();

    const { calls } = settings(images, {
      "GET /content/images": failure(404, "not_found", "No repository images."),
    });
    await screen.findByRole("heading", { level: 1, name: "images" });
    await waitFor(() => expect(calls.some((call) => call.path === "/content/images")).toBe(true));
    expect(screen.queryByText("Address")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("ask for the other repositories only for a group", async () => {
    const { calls } = settings();

    await screen.findByText("https://ui.test/repository/releases/");
    expect(calls.map((call) => call.path).sort()).toEqual([
      "/content/releases",
      "/repositories/releases",
    ]);
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

  test("of APT and YUM show the suite and the depth they were made with as facts", async () => {
    const apt = repository("apt-own", {
      format: "apt",
      hosted: { deployment_policy: "allow_redeploy" },
      format_config: { suite: "trixie" },
    });
    const first = settings(apt, {
      "GET /repositories/apt-own/signing-key": { json: KEY },
    });
    expect(await screen.findByText("trixie")).toBeVisible();
    expect(screen.getByText("Suite")).toBeVisible();
    expect(screen.queryByLabelText("Suite")).toBeNull(); // chosen once
    first.unmount();

    const yum = repository("yum-own", { format: "yum", format_config: { repodata_depth: 2 } });
    settings(yum, { "GET /repositories/yum-own/signing-key": { json: KEY } });
    expect(await screen.findByText("Depth of the metadata")).toBeVisible();
    expect(screen.getByText("2")).toBeVisible();
    expect(screen.queryByLabelText("Depth of the metadata")).toBeNull();
  });

  test("of an APT, YUM or apk proxy keep its remote's keys, and send them back when saved", async () => {
    const user = userEvent.setup();
    const held = repository("apk-alpine", {
      ...proxy("apk-alpine"),
      format: "apk",
      format_config: { remote_keys: "the keys" },
    });
    const { calls } = settings(held, { "PUT /repositories/apk-alpine": { json: held } });

    const keys = await screen.findByLabelText("The remote's public keys");
    expect(keys).toHaveValue("the keys");
    await user.click(screen.getByRole("checkbox", { name: "Online" }));
    await user.click(save());

    await waitFor(() => expect(of(calls, "PUT")).toHaveLength(1));
    expect(of(calls, "PUT")[0]?.body).toMatchObject({
      online: false,
      format_config: { remote_keys: "the keys" },
    });
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

describe("the signing key of a repository (4.2)", () => {
  const APT = repository("apt-own", { format: "apt", format_config: { suite: "stable" } });
  const APK = repository("apk-own", { format: "apk", format_config: {} });
  const NEW_KEY = {
    ...KEY,
    algorithm: "rsa4096",
    fingerprint: "AAAA1111BBBB2222CCCC3333DDDD4444EEEE5555",
  };
  const RSA_KEY = {
    ...KEY,
    kind: "rsa",
    algorithm: "rsa4096",
    public_key: "-----BEGIN PUBLIC KEY-----\nMIIC\n-----END PUBLIC KEY-----\n",
  };

  function keyed(which: ReturnType<typeof repository> = APT, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      [`GET /repositories/${which.name}`]: { json: which },
      [`GET /content/${which.name}`]: { json: view(which) },
      [`GET /repositories/${which.name}/signing-key`]: { json: KEY },
      "GET /repositories": { json: page([which]) },
      ...more,
    });
    navigation.at(`/admin/repositories/${which.name}`);
    return { ...renderUi(<RepositorySettingsScreen />, { session }), ...api };
  }
  const panel = () =>
    screen.getByRole("heading", { name: "Signing key" }).parentElement as HTMLElement;
  const dialog = (name: string) => screen.getByRole("alertdialog", { name });

  test("is shown with what it is, and its public key to copy or to save", async () => {
    keyed();

    expect(await screen.findByText(KEY.fingerprint)).toBeVisible();
    for (const fact of ["OpenPGP", "ed25519"])
      expect(within(panel()).getByText(fact)).toBeVisible();
    expect(within(panel()).getByRole("figure")).toHaveTextContent("BEGIN PGP PUBLIC KEY BLOCK");
    const download = within(panel()).getByRole("link", { name: "Download the public key" });
    expect(download).toHaveAttribute("download", "apt-own.asc");
    expect(download.getAttribute("href")).toBe(
      `data:application/pgp-keys;charset=utf-8,${encodeURIComponent(KEY.public_key)}`,
    );
    await expectAccessible();
  });

  test("of apk is saved under the name apk finds it by", async () => {
    keyed(APK, { "GET /repositories/apk-own/signing-key": { json: RSA_KEY } });

    const download = await screen.findByRole("link", { name: "Download the public key" });
    expect(download).toHaveAttribute("download", "megooarti-apk-own.rsa.pub");
    expect(within(panel()).getByText("RSA")).toBeVisible();
  });

  test("is had for a group of them too, and for no proxy and no other format", async () => {
    const group = repository("apt-all", {
      format: "apt",
      type: "group",
      blob_store: null,
      hosted: null,
      format_config: {},
      group: { members: [] },
    });
    const first = keyed(group);
    expect(await screen.findByText(KEY.fingerprint)).toBeVisible();
    first.unmount();

    const mirror = repository("apt-debian", {
      ...proxy("apt-debian"),
      format: "apt",
      format_config: { remote_keys: "" },
    });
    const { calls } = keyed(mirror);
    await screen.findByRole("heading", { level: 1, name: "apt-debian" });
    await screen.findByText("https://ui.test/repository/apt-debian/");
    expect(calls.some((call) => call.path.endsWith("/signing-key"))).toBe(false);
    expect(screen.queryByRole("heading", { name: "Signing key" })).toBeNull();
  });

  test("a new one is made only after asking, of the algorithm chosen, and is shown", async () => {
    const user = userEvent.setup();
    const { calls } = keyed(APT, {
      "POST /repositories/apt-own/signing-key/generate": { json: NEW_KEY },
    });
    await screen.findByText(KEY.fingerprint);

    await user.selectOptions(screen.getByLabelText("Algorithm of a new key"), "rsa4096");
    await user.click(screen.getByRole("button", { name: "Generate a new key" }));
    const asked = dialog("Sign apt-own with a new key?");
    expect(asked).toHaveTextContent(
      "Every machine that uses apt-own must install the new public key, or it refuses what the repository serves.",
    );
    expect(of(calls, "POST")).toHaveLength(0);
    await user.click(within(asked).getByRole("button", { name: "Generate a new key" }));

    await waitFor(() => expect(notices()).toHaveTextContent("apt-own signs with a new key."));
    expect(of(calls, "POST")[0]?.body).toEqual({ algorithm: "rsa4096" });
    expect(screen.getByText(NEW_KEY.fingerprint)).toBeVisible();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  test("a new apk key is RSA, and no algorithm is asked for", async () => {
    const user = userEvent.setup();
    const { calls } = keyed(APK, {
      "GET /repositories/apk-own/signing-key": { json: RSA_KEY },
      "POST /repositories/apk-own/signing-key/generate": { json: RSA_KEY },
    });
    await screen.findByText(RSA_KEY.fingerprint);

    expect(screen.queryByLabelText("Algorithm of a new key")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Generate a new key" }));
    await user.click(
      within(dialog("Sign apk-own with a new key?")).getByRole("button", {
        name: "Generate a new key",
      }),
    );

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(of(calls, "POST")[0]?.body).toEqual({});
  });

  test("one is imported only after asking, is refused at its field, and is then kept nowhere", async () => {
    const user = userEvent.setup();
    let answer = failure(422, "validation_error", "The request is not valid.", [
      { field: "body.private_key", message: "This key is protected by a passphrase." },
    ]);
    const { calls, client } = keyed(APT, {
      "PUT /repositories/apt-own/signing-key": () => answer,
    });
    await screen.findByText(KEY.fingerprint);
    const field = screen.getByLabelText("A private key to import");
    const press = () => user.click(screen.getByRole("button", { name: "Import the key" }));

    await press();
    expect(field).toHaveAccessibleDescription("Paste the private key.");
    expect(screen.queryByRole("alertdialog")).toBeNull();

    await user.type(field, "the-private-key");
    await press();
    const asked = dialog("Sign apt-own with the imported key?");
    expect(asked).toHaveTextContent(
      "Every machine that uses apt-own must install the new public key",
    );
    await user.click(within(asked).getByRole("button", { name: "Import the key" }));
    await waitFor(() =>
      expect(field).toHaveAccessibleDescription("This key is protected by a passphrase."),
    );
    expect(field).toHaveValue("the-private-key"); // to be put right, not typed again

    answer = { json: NEW_KEY };
    await press();
    await user.click(
      within(dialog("Sign apt-own with the imported key?")).getByRole("button", {
        name: "Import the key",
      }),
    );
    await waitFor(() =>
      expect(notices()).toHaveTextContent("apt-own signs with the imported key."),
    );
    expect(of(calls, "PUT").map((call) => call.body)).toEqual([
      { private_key: "the-private-key" },
      { private_key: "the-private-key" },
    ]);
    expect(field).toHaveValue("");
    expect(screen.getByText(NEW_KEY.fingerprint)).toBeVisible();
    await waitFor(() =>
      expect(
        JSON.stringify(
          client
            .getMutationCache()
            .getAll()
            .map((mutation) => mutation.state.variables),
        ),
      ).not.toContain("the-private-key"),
    );
  });

  test("is shown, and not replaced, to whoever may only read it", async () => {
    keyed(APT, {}, holding("admin:repositories:read"));

    expect(await screen.findByText(KEY.fingerprint)).toBeVisible();
    expect(screen.getByRole("link", { name: "Download the public key" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Generate a new key" })).toBeNull();
    expect(screen.queryByLabelText("A private key to import")).toBeNull();
  });

  test("says so when it cannot be had", async () => {
    keyed(APT, {
      "GET /repositories/apt-own/signing-key": failure(500, "internal_error", "Something broke."),
    });

    await screen.findByRole("heading", { name: "Signing key" });
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("The server met a fault.");
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

  test("one called . or .. is none, and is not asked for (R13)", async () => {
    const user = userEvent.setup();
    const { calls } = stores();
    await screen.findByRole("table", { name: "Blob stores" });

    for (const dots of [".", ".."]) {
      await user.clear(screen.getByLabelText("Name"));
      await user.type(screen.getByLabelText("Name"), dots);
      await user.click(create());
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A blob store cannot be called . or .. : its directory would not be its own.",
      );
    }
    expect(of(calls, "POST")).toHaveLength(0);
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

  test("the default one is always kept, and is offered no button that would be refused (H7)", async () => {
    stores();

    const table = await screen.findByRole("table", { name: "Blob stores" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(within(rows[0] as HTMLElement).queryByRole("button")).toBeNull();
    expect(rows[0]).toHaveTextContent("Always kept");
    expect(
      within(rows[1] as HTMLElement).getByRole("button", { name: "Delete fast" }),
    ).toBeVisible();
    expect(rows[1]).not.toHaveTextContent("Always kept");
    await expectAccessible();
  });

  test("is not deleted while a repository uses it, and the screen says which", async () => {
    const user = userEvent.setup();
    stores({
      "DELETE /blob-stores/fast": failure(
        409,
        "in_use",
        "The repository releases uses this blob store.",
      ),
    });

    await user.click(await screen.findByRole("button", { name: "Delete fast" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type fast to go on"), "fast");
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

  test("says so when the database was never migrated", async () => {
    system({
      "GET /system/information": {
        json: { ...INFORMATION, schema: { revision: null, expected: "0007", current: false } },
      },
    });

    expect(await screen.findByText("Never migrated")).toBeVisible();
    expect(screen.getByText("This version expects 0007")).toBeVisible();
  });

  test("shows every blob store, however many there are", async () => {
    const many = Array.from({ length: 200 }, (_, index) => store(`store-${index}`));
    system({
      "GET /blob-stores": (call) =>
        call.path.includes("offset=200")
          ? { json: { items: [store("the-last")], total: 201, limit: 200, offset: 200 } }
          : { json: { items: many, total: 201, limit: 200, offset: 0 } },
    });

    const table = await screen.findByRole("table", { name: "Blob stores" });
    expect(within(table).getAllByRole("row")).toHaveLength(202);
    expect(within(table).getAllByText("the-last")[0]).toBeVisible();
  });

  test("sets the base URL, as the server then keeps it", async () => {
    const user = userEvent.setup();
    const { calls } = system({
      "PUT /settings/base-url": {
        json: { base_url: "https://repo.example.org", anonymous_access: { enabled: false } },
      },
    });
    await waitFor(() => expect(field()).toHaveValue(""));

    // No address, and addresses that would carry somebody's name to every client (H4).
    for (const none of [
      "repo.example.org",
      "https://robot:secret@repo.example.org",
      "https://robot@repo.example.org",
      "https://@repo.example.org",
    ]) {
      await user.clear(field());
      await user.type(field(), none);
      await user.click(screen.getByRole("button", { name: "Save" }));
      expect(field()).toHaveAccessibleDescription(
        "Give an http or https address, without a user name, a password, a query or a fragment.",
      );
      expect(field()).toHaveFocus();
    }
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
