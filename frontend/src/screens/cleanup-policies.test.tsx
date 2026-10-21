import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { NewPolicyScreen, PoliciesScreen, PolicyScreen } from "./cleanup-policies";

const page = (items: unknown[], total = items.length) => ({ items, total, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string, path: string) =>
  calls.filter((call) => call.method === method && call.path.startsWith(path));

const STALE = {
  id: "p1",
  name: "stale",
  description: "Old pre-releases",
  format: "npm",
  updated_days: 30,
  downloaded_days: null,
  release_type: "prerelease",
  asset_pattern: null,
  repositories: ["npm-hosted"],
  created_at: "2026-10-21T08:00:00Z",
  updated_at: "2026-10-21T08:00:00Z",
};
const FORMATS = [
  { name: "npm", types: ["group", "hosted", "proxy"], public_remotes: {}, has_prereleases: true },
  { name: "raw", types: ["group", "hosted", "proxy"], public_remotes: {}, has_prereleases: false },
];
const repository = (name: string, format = "npm", type = "hosted") => ({
  name,
  format,
  type,
  online: true,
  blob_store: "default",
  url_path: `/repository/${name}/`,
  hosted: null,
  format_config: {},
  proxy: null,
  group: null,
  status: null,
  cleanup_policies: [],
  cleanup: null,
});
const SELECTED = [
  {
    id: "c1",
    namespace: "",
    name: "left-pad",
    version: "2.0.0-beta.1",
    modified: "2026-08-01T00:00:00Z",
    last_downloaded: null,
  },
  {
    id: "c2",
    namespace: "",
    name: "left-pad",
    version: "1.0.0-rc.1",
    modified: "2026-07-01T00:00:00Z",
    last_downloaded: "2026-07-02T00:00:00Z",
  },
];
const SURROUNDINGS: Routes = {
  "GET /formats": { json: page(FORMATS) },
  "GET /repositories": {
    json: page([
      repository("npm-hosted"),
      repository("npm-all", "npm", "group"),
      repository("files", "raw"),
    ]),
  },
  "POST /cleanup-policies/preview": { json: page(SELECTED, 51) },
};

function render(screenOf: ReactElement, address: string, routes: Routes, session = ADMIN) {
  const api = mockApi({ ...SURROUNDINGS, ...routes });
  navigation.at(address);
  return { ...renderUi(screenOf, { session }), ...api };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("the cleanup policies (cleanup spec 6)", () => {
  test("are listed with their format, criteria in words and repositories", async () => {
    render(<PoliciesScreen />, "/admin/cleanup-policies", {
      "GET /cleanup-policies": { json: page([STALE]) },
    });

    const table = await screen.findByRole("table", { name: "Cleanup policies" });
    const row = within(table).getAllByRole("row")[1] as HTMLElement;
    expect(within(row).getByRole("link", { name: "stale" })).toHaveAttribute(
      "href",
      "/admin/cleanup-policies/stale",
    );
    expect(row).toHaveTextContent("npm");
    expect(row).toHaveTextContent("Not updated in 30 days, pre-releases");
    expect(row).toHaveTextContent("npm-hosted");
    expect(screen.getByRole("link", { name: "New cleanup policy" })).toBeVisible();
    await expectAccessible();
  });

  test("say so when there is none, and offer no new one to whoever may only read", async () => {
    render(
      <PoliciesScreen />,
      "/admin/cleanup-policies",
      { "GET /cleanup-policies": { json: page([]) } },
      holding("admin:cleanup:read"),
    );

    expect(await screen.findByText("No cleanup policy is made yet.")).toBeVisible();
    expect(screen.queryByRole("link", { name: "New cleanup policy" })).toBeNull();
  });

  test("a policy is made, then shown at its own address", async () => {
    const user = userEvent.setup();
    const { calls } = render(<NewPolicyScreen />, "/admin/cleanup-policies/~new", {
      "POST /cleanup-policies": { status: 201, json: { ...STALE, name: "old-npm" } },
    });

    await user.type(await screen.findByLabelText(/^Name/), "old-npm");
    await user.selectOptions(screen.getByLabelText(/^Format/), "npm");
    await user.click(screen.getByRole("checkbox", { name: "Not updated in" }));
    await user.clear(screen.getByRole("spinbutton", { name: /Not updated in, days/ }));
    await user.type(screen.getByRole("spinbutton", { name: /Not updated in, days/ }), "14");
    await user.click(screen.getByRole("button", { name: "Create cleanup policy" }));

    await waitFor(() =>
      expect(navigation.router.push).toHaveBeenCalledWith("/admin/cleanup-policies/old-npm"),
    );
    expect(
      of(calls, "POST", "/cleanup-policies").filter((call) => call.path === "/cleanup-policies")[0]
        ?.body,
    ).toEqual({
      name: "old-npm",
      description: "",
      format: "npm",
      updated_days: 14,
      downloaded_days: null,
      release_type: null,
      asset_pattern: null,
    });
  });

  test("what the server refuses is said at its field", async () => {
    const user = userEvent.setup();
    render(<NewPolicyScreen />, "/admin/cleanup-policies/~new", {
      "POST /cleanup-policies": failure(422, "validation_error", "The request is not valid.", [
        { field: "asset_pattern", message: "Not a pattern: missing )" },
      ]),
    });

    await user.type(await screen.findByLabelText(/^Name/), "tmp");
    await user.click(screen.getByRole("checkbox", { name: "A file's path matches" }));
    await user.type(screen.getByRole("textbox", { name: /A file's path matches, pattern/ }), "(");
    await user.click(screen.getByRole("button", { name: "Create cleanup policy" }));

    expect(await screen.findByText("Not a pattern: missing )")).toBeVisible();
  });

  test("release type goes with a format that has none", async () => {
    const user = userEvent.setup();
    const { calls } = render(<NewPolicyScreen />, "/admin/cleanup-policies/~new", {
      "POST /cleanup-policies": { status: 201, json: { ...STALE, name: "x" } },
    });

    await user.type(await screen.findByLabelText(/^Name/), "x");
    await user.selectOptions(screen.getByLabelText(/^Format/), "npm");
    await user.click(screen.getByRole("checkbox", { name: "Release type" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: /Release type, which/ }),
      "prerelease",
    );
    await user.selectOptions(screen.getByLabelText(/^Format/), "raw");
    expect(screen.queryByRole("checkbox", { name: "Release type" })).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: "Not updated in" }));
    await user.click(screen.getByRole("button", { name: "Create cleanup policy" }));

    await waitFor(() => expect(of(calls, "POST", "/cleanup-policies").length).toBeGreaterThan(0));
    const made = of(calls, "POST", "/cleanup-policies").find(
      (call) => call.path === "/cleanup-policies",
    );
    expect(made?.body).toMatchObject({ format: "raw", release_type: null });
  });

  test("the format is not offered again once made", async () => {
    render(<PolicyScreen />, "/admin/cleanup-policies/stale", {
      "GET /cleanup-policies/stale": { json: STALE },
    });

    expect(await screen.findByRole("heading", { name: "stale" })).toBeVisible();
    expect(screen.queryByRole("combobox", { name: /^Format/ })).toBeNull();
    expect(screen.getByText("npm")).toBeVisible();
  });

  test("the preview lists what the policy would remove, with the total", async () => {
    const { calls } = render(<PolicyScreen />, "/admin/cleanup-policies/stale", {
      "GET /cleanup-policies/stale": { json: STALE },
    });

    const table = await screen.findByRole("table", { name: "Would be removed" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("2.0.0-beta.1")).toBeVisible();
    expect(within(table).getByText("Never")).toBeVisible();
    expect(screen.getByText("51 components")).toBeVisible();
    expect(screen.getByRole("button", { name: "Next" })).toBeVisible();
    const asked = of(calls, "POST", "/cleanup-policies/preview")[0];
    expect(asked?.body).toMatchObject({
      format: "npm",
      updated_days: 30,
      repository: "npm-hosted",
    });
    await expectAccessible();
  });

  test("the preview waits for the typing to stop", async () => {
    const { calls } = render(<PolicyScreen />, "/admin/cleanup-policies/stale", {
      "GET /cleanup-policies/stale": { json: STALE },
    });
    await screen.findByRole("table", { name: "Would be removed" });
    const before = of(calls, "POST", "/cleanup-policies/preview").length;
    // From here the clock moves only when the test moves it: typing takes no time.
    vi.useFakeTimers();

    const days = screen.getByRole("spinbutton", { name: /Not updated in, days/ });
    for (const typed of ["", "1", "12", "123", "1234", "12345"]) {
      fireEvent.change(days, { target: { value: typed } });
    }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(of(calls, "POST", "/cleanup-policies/preview")).toHaveLength(before);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(of(calls, "POST", "/cleanup-policies/preview")).toHaveLength(before + 1);
    expect(of(calls, "POST", "/cleanup-policies/preview").at(-1)?.body).toMatchObject({
      updated_days: 12345,
    });
  });

  test("a policy with a problem is not previewed", async () => {
    const user = userEvent.setup();
    const { calls } = render(<PolicyScreen />, "/admin/cleanup-policies/stale", {
      "GET /cleanup-policies/stale": { json: STALE },
    });
    await screen.findByRole("table", { name: "Would be removed" });
    const before = of(calls, "POST", "/cleanup-policies/preview").length;

    await user.click(screen.getByRole("checkbox", { name: "Not updated in" }));
    await user.click(screen.getByRole("checkbox", { name: "Release type" }));

    expect(
      await screen.findByText("Correct the policy to see what it would remove."),
    ).toBeVisible();
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(of(calls, "POST", "/cleanup-policies/preview")).toHaveLength(before);
  });

  test("deleting asks first, naming the repositories it is detached from", async () => {
    const user = userEvent.setup();
    const { calls } = render(<PolicyScreen />, "/admin/cleanup-policies/stale", {
      "GET /cleanup-policies/stale": { json: STALE },
      "DELETE /cleanup-policies/stale": { status: 204 },
    });

    await user.click(await screen.findByRole("button", { name: "Delete cleanup policy" }));
    const asked = await screen.findByRole("alertdialog");
    expect(asked).toHaveTextContent("npm-hosted");
    await user.click(within(asked).getByRole("button", { name: "Delete cleanup policy" }));

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/admin/cleanup-policies"),
    );
    expect(of(calls, "DELETE", "/cleanup-policies/stale")).toHaveLength(1);
  });

  test("a policy saved while the formats are not known keeps its release type", async () => {
    // Saved without it, "npm pre-releases older than 30 days" would be every version.
    const user = userEvent.setup();
    const { calls } = render(<PolicyScreen />, "/admin/cleanup-policies/stale", {
      "GET /cleanup-policies/stale": { json: STALE },
      "GET /formats": failure(503, "unavailable", "Not now."),
      "PUT /cleanup-policies/stale": { json: STALE },
    });

    await user.click(await screen.findByRole("button", { name: "Save" }));

    await waitFor(() => expect(of(calls, "PUT", "/cleanup-policies/stale")).toHaveLength(1));
    expect(of(calls, "PUT", "/cleanup-policies/stale")[0]?.body).toMatchObject({
      release_type: "prerelease",
    });
  });

  test("a reader who may not list the repositories is told why there is no preview", async () => {
    render(
      <PolicyScreen />,
      "/admin/cleanup-policies/stale",
      {
        "GET /cleanup-policies/stale": { json: STALE },
        "GET /repositories": failure(403, "forbidden", "You do not have permission to do this."),
      },
      holding("admin:cleanup:read"),
    );

    expect(await screen.findByText(/permission/i)).toBeVisible();
  });

  test("whoever may only read sees the policy and its preview, and changes nothing", async () => {
    render(
      <PolicyScreen />,
      "/admin/cleanup-policies/stale",
      { "GET /cleanup-policies/stale": { json: STALE } },
      holding("admin:cleanup:read", "admin:repositories:read"),
    );

    expect(await screen.findByRole("table", { name: "Would be removed" })).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Not updated in" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete cleanup policy" })).toBeNull();
  });
});
