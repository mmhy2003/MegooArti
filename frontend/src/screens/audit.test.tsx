import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { AuditScreen } from "./audit";

const page = (items: unknown[], total = items.length) => ({
  items,
  total,
  limit: 50,
  offset: 0,
});
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

const UPDATED = {
  id: "r2",
  at: "2026-10-20T09:30:00Z",
  actor: "root",
  method: "session",
  address: "198.51.100.9",
  event: "user.updated",
  target_kind: "user",
  target_name: "kim",
  changes: {
    email: { before: null, after: "kim@corp.example" },
    roles: { before: ["dev"], after: ["dev", "ops"] },
  },
  request_id: "abc",
};
const FAILED = {
  id: "r1",
  at: "2026-10-20T09:00:00Z",
  actor: null,
  method: null,
  address: "203.0.113.7",
  event: "sign_in.failed",
  target_kind: "user",
  target_name: "kim",
  changes: null,
  request_id: "def",
};

function auditScreen(more: Routes = {}, session = ADMIN, address = "/admin/audit") {
  const api = mockApi({
    "GET /audit": { json: page([UPDATED, FAILED]) },
    "GET /audit/retention": { json: { audit_retention_days: 365 } },
    ...more,
  });
  navigation.at(address);
  return { ...renderUi(<AuditScreen />, { session }), ...api };
}

describe("the audit log (spec 9)", () => {
  test("lists who did what, about what and from where, each opening to what changed", async () => {
    const user = userEvent.setup();
    auditScreen();

    const table = await screen.findByRole("table", { name: "Audit log" });
    const rows = within(table).getAllByRole("row").slice(1);
    const cells = (row: Element | undefined) =>
      within(row as HTMLElement)
        .getAllByRole("cell")
        .slice(1, 5)
        .map((cell) => cell.textContent);
    expect(cells(rows[0])).toEqual(["rootby session", "user.updated", "userkim", "198.51.100.9"]);
    expect(cells(rows[1])).toEqual([
      "Nobody signed in",
      "sign_in.failed",
      "userkim",
      "203.0.113.7",
    ]);

    await user.click(within(rows[0] as HTMLElement).getByText("2 fields"));
    expect(within(rows[0] as HTMLElement).getByText("roles:")).toBeVisible();
    expect(within(rows[0] as HTMLElement).getByText('["dev"] → ["dev","ops"]')).toBeVisible();
    expect(within(rows[0] as HTMLElement).getByText("— → kim@corp.example")).toBeVisible();
    await expectAccessible();
  });

  test("asks for the records the address names, and pages through them", async () => {
    const { calls } = auditScreen(
      { "GET /audit": { json: { ...page([UPDATED], 120), offset: 50 } } },
      ADMIN,
      "/admin/audit?event=user&actor=root&since=2026-10-01&until=2026-10-19&page=2",
    );

    await screen.findByRole("table", { name: "Audit log" });
    const listing = of(calls, "GET").find((call) => call.path.startsWith("/audit?"));
    const asked = new URLSearchParams(listing?.path.split("?")[1]);
    expect(Object.fromEntries(asked)).toEqual({
      limit: "50",
      offset: "50",
      event: "user",
      actor: "root",
      since: "2026-10-01T00:00:00.000Z",
      until: "2026-10-20T00:00:00.000Z",
    });
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/admin/audit?event=user&actor=root&since=2026-10-01&until=2026-10-19&page=3",
    );
  });

  test("filters by what is typed, from the first page", async () => {
    const user = userEvent.setup();
    auditScreen();

    await screen.findByRole("table", { name: "Audit log" });
    await user.selectOptions(screen.getByLabelText("Event"), "sign_in");
    await user.type(screen.getByLabelText("About"), "kim");
    await user.click(screen.getByRole("button", { name: "Filter" }));

    expect(navigation.router.push).toHaveBeenCalledWith("/admin/audit?event=sign_in&target=kim");
  });

  test("exports what the filters give, as JSON Lines or CSV", async () => {
    auditScreen({}, ADMIN, "/admin/audit?event=user&until=2026-10-19");

    await screen.findByRole("table", { name: "Audit log" });

    expect(screen.getByRole("link", { name: "Export as JSON Lines" })).toHaveAttribute(
      "href",
      "/api/v1/audit/export?format=jsonl&event=user&until=2026-10-20T00%3A00%3A00.000Z",
    );
    expect(screen.getByRole("link", { name: "Export as CSV" })).toHaveAttribute(
      "href",
      "/api/v1/audit/export?format=csv&event=user&until=2026-10-20T00%3A00%3A00.000Z",
    );
  });

  test("says so when there is no record", async () => {
    auditScreen({ "GET /audit": { json: page([]) } });

    expect(await screen.findByText("No records.")).toBeVisible();
  });

  test("keeps records the days an administrator sets, and says what it refuses", async () => {
    const user = userEvent.setup();
    const { calls } = auditScreen({
      "PUT /audit/retention": (call) => ({ json: call.body }),
    });

    const days = await screen.findByLabelText("Days kept");
    await user.clear(days);
    await user.type(days, "0");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(days).toHaveAccessibleDescription(/from 1 to 36500/);
    expect(of(calls, "PUT")).toHaveLength(0);

    await user.clear(days);
    await user.type(days, "90");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Records are kept 90 days."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ audit_retention_days: 90 });
  });

  test("shows the days kept, and not their change, to whoever may only read", async () => {
    auditScreen({}, holding("admin:audit:read"));

    expect(await screen.findByLabelText("Days kept")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  test("says why when the records cannot be read, with the request to look up", async () => {
    auditScreen({ "GET /audit": failure(503, "unavailable", "The database is not reachable.") });

    expect(await screen.findByText(/req-123/)).toBeVisible();
  });
});
