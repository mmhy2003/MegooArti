import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { leaveFor } from "@/lib/leave";
import { failure, mockApi, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { ConnectedAppsScreen } from "./connected-apps";
import { ConnectScreen } from "./connect";

vi.mock("@/lib/leave", () => ({ leaveFor: vi.fn() }));

const BACK = "http://127.0.0.1:33418/callback?code=mgc_x&state=s";
const page = (items: unknown[]) => ({ items, total: items.length, limit: 200, offset: 0 });

beforeEach(() => vi.mocked(leaveFor).mockReset());

function consent(more: Routes = {}, address = "/connect?request=sealed") {
  const api = mockApi({
    "GET /oauth/consent": { json: { client: "Claude Code", redirect_host: "127.0.0.1" } },
    "POST /oauth/consent": { json: { redirect: BACK } },
    "POST /oauth/refusal": {
      json: { redirect: "http://127.0.0.1:33418/callback?error=access_denied" },
    },
    ...more,
  });
  navigation.at(address);
  return { ...renderUi(<ConnectScreen />, { session: ADMIN }), ...api };
}

describe("the consent page of an application signing in with OAuth (7.3)", () => {
  test("says who asks, in its own words, and where the browser goes back to", async () => {
    const { calls } = consent();

    expect(await screen.findByText("Claude Code")).toBeVisible();
    expect(screen.getByText(/the name it gave itself/)).toHaveTextContent("127.0.0.1");
    expect(calls[0]?.path).toBe("/oauth/consent?request=sealed");
    expect(screen.getByRole("radio", { name: /Read what I can read/ })).toBeChecked();
    expect(screen.getByLabelText("For how long")).toHaveValue("30d");
    await expectAccessible();
  });

  test("allows what was chosen, for as long as was chosen, and goes back", async () => {
    const user = userEvent.setup();
    const { calls } = consent();
    await screen.findByText("Claude Code");

    await user.click(screen.getByRole("radio", { name: /Everything I can do/ }));
    await user.selectOptions(screen.getByLabelText("For how long"), "1d");
    await user.click(screen.getByRole("button", { name: "Allow" }));

    await waitFor(() => expect(leaveFor).toHaveBeenCalledWith(BACK));
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      request: "sealed",
      access: "all",
      lasts: "1d",
    });
  });

  test("refuses, and the application is told so", async () => {
    const user = userEvent.setup();
    const { calls } = consent();
    await screen.findByText("Claude Code");

    await user.click(screen.getByRole("button", { name: "Refuse" }));

    await waitFor(() =>
      expect(leaveFor).toHaveBeenCalledWith("http://127.0.0.1:33418/callback?error=access_denied"),
    );
    expect(calls.find((call) => call.method === "POST")?.path).toBe("/oauth/refusal");
  });

  test("says when the request has expired, or when nothing was asked", async () => {
    consent({
      "GET /oauth/consent": failure(
        410,
        "request_expired",
        "This request has expired. Start again from the application.",
      ),
    });
    expect(await screen.findByText(/This request has expired/)).toBeVisible();

    consent({}, "/connect");
    expect(
      screen.getByText("Nothing is asked here. Start again from the application."),
    ).toBeVisible();
  });
});

describe("one's connected apps (7.6)", () => {
  test("are listed with what each may do, and revoked", async () => {
    const user = userEvent.setup();
    const { calls } = (() => {
      const api = mockApi({
        "GET /me/connected-apps": {
          json: page([
            {
              id: "app1",
              client: "Claude Code",
              redirect_host: "127.0.0.1",
              scopes: ["repository:*:*:browse", "repository:*:*:read", "admin:*:read"],
              created_at: "2026-10-18T08:00:00Z",
              last_used_at: "2026-10-18T09:00:00Z",
              expires_at: "2026-11-17T08:00:00Z",
            },
          ]),
        },
        "DELETE /me/connected-apps/app1": { status: 204 },
      });
      navigation.at("/account/connected-apps");
      return { ...renderUi(<ConnectedAppsScreen />, { session: ADMIN }), ...api };
    })();

    const table = await screen.findByRole("table", { name: "Your connected apps" });
    expect(table).toHaveTextContent("Read what you may read");
    await expectAccessible();
    await user.click(screen.getByRole("button", { name: "Revoke Claude Code" }));
    await user.click(screen.getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    expect(calls.find((call) => call.method === "DELETE")?.path).toBe("/me/connected-apps/app1");
  });
});
