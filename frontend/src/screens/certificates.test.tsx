import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { CertificatesScreen } from "./certificates";

const page = (items: unknown[]) => ({ items, total: items.length, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

const PEM = "-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIU\n-----END CERTIFICATE-----\n";
const view = (subject: string, fingerprint: string, more: Record<string, unknown> = {}) => ({
  subject,
  issuer: "CN=Corp Root CA,O=Corp",
  fingerprint,
  not_after: "2031-05-17T00:00:00Z",
  pem: PEM,
  ...more,
});
const ROOT = {
  ...view("CN=Corp Root CA,O=Corp", "0f".repeat(32)),
  id: "root",
  added_by: "admin",
  added_at: "2026-10-19T08:00:00Z",
};
const OLD = {
  ...view("CN=Old CA,O=Corp", "aa".repeat(32), { not_after: "2020-01-01T00:00:00Z" }),
  id: "old",
  added_by: "dana",
  added_at: "2019-01-01T08:00:00Z",
};

function certificatesScreen(more: Routes = {}, session = ADMIN) {
  const api = mockApi({ "GET /certificates": { json: page([ROOT, OLD]) }, ...more });
  navigation.at("/admin/certificates");
  return { ...renderUi(<CertificatesScreen />, { session }), ...api };
}

describe("the trusted certificates (spec 6)", () => {
  test("are listed with who they are, who vouches for them, their fingerprint and expiry", async () => {
    certificatesScreen();

    const table = await screen.findByRole("table", { name: "Certificates" });
    const rows = within(table).getAllByRole("row").slice(1);
    const cells = (row: Element | undefined) =>
      within(row as HTMLElement)
        .getAllByRole("cell")
        .slice(0, 3)
        .map((cell) => cell.textContent);
    expect(cells(rows[0])).toEqual([
      "CN=Corp Root CA,O=Corp",
      "CN=Corp Root CA,O=Corp",
      "0F:0F:0F:0F:0F:0F:0F:0F…",
    ]);
    expect(within(rows[0] as HTMLElement).queryByText("Expired")).toBeNull();
    expect(within(rows[1] as HTMLElement).getByText("Expired")).toBeVisible();
    await expectAccessible();
  });

  test("say so when there is none", async () => {
    certificatesScreen({ "GET /certificates": { json: page([]) } });

    expect(await screen.findByText(/No certificate is added/)).toBeVisible();
  });

  test("take one pasted, and say where the server refuses it", async () => {
    const user = userEvent.setup();
    let tries = 0;
    const { calls } = certificatesScreen({
      "POST /certificates": () =>
        (tries += 1) === 1
          ? failure(422, "validation_error", "The request is not valid.", [
              { field: "pem", message: "Paste one certificate at a time." },
            ])
          : { status: 201, json: ROOT },
    });

    await user.click(await screen.findByLabelText("Certificate (PEM)"));
    await user.paste(PEM);
    await user.click(screen.getByRole("button", { name: "Trust this certificate" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Certificate (PEM)")).toHaveAccessibleDescription(
        /one certificate at a time/,
      ),
    );
    await user.click(screen.getByRole("button", { name: "Trust this certificate" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Trusted CN=Corp Root CA,O=Corp."));
    expect(of(calls, "POST")[1]?.body).toEqual({ pem: PEM });
    expect(screen.getByLabelText("Certificate (PEM)")).toHaveValue("");
  });

  test("are fetched from a server, and one is trusted only after its fingerprint is shown", async () => {
    const user = userEvent.setup();
    const LEAF = view("CN=ldap.corp.example", "11".repeat(32));
    const CA = view("CN=Corp Root CA,O=Corp", "0f".repeat(32));
    const { calls } = certificatesScreen({
      "POST /certificates/fetch": { json: { chain: [LEAF, CA] } },
      "POST /certificates": { status: 201, json: ROOT },
    });

    await user.type(await screen.findByLabelText("Host"), "ldap.corp.example");
    await user.clear(screen.getByLabelText("Port"));
    await user.type(screen.getByLabelText("Port"), "636");
    await user.click(screen.getByRole("button", { name: "Fetch" }));
    const presented = await screen.findByRole("list", { name: "What the server presented" });
    const [own, authority] = within(presented).getAllByRole("listitem");
    expect(own).toHaveTextContent("The server's own");
    expect(authority).toHaveTextContent("Its authority 1");
    await user.click(
      within(authority as HTMLElement).getByRole("button", { name: "Trust this certificate" }),
    );

    const dialog = screen.getByRole("alertdialog", { name: "Trust this certificate?" });
    expect(dialog).toHaveTextContent(
      "0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F:0F",
    );
    expect(dialog).toHaveTextContent("Check its fingerprint");
    expect(of(calls, "POST").map((call) => call.path)).toEqual(["/certificates/fetch"]);
    await user.click(within(dialog).getByRole("button", { name: "Trust it" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Trusted CN=Corp Root CA,O=Corp."));
    expect(of(calls, "POST")[0]?.body).toEqual({ host: "ldap.corp.example", port: 636 });
    expect(of(calls, "POST")[1]?.body).toEqual({ pem: PEM });
  });

  test("say why a server could not be asked", async () => {
    const user = userEvent.setup();
    certificatesScreen({
      "POST /certificates/fetch": failure(
        502,
        "fetch_failed",
        "ldap.corp.example:636 could not be reached over TLS.",
      ),
    });

    await user.type(await screen.findByLabelText("Host"), "ldap.corp.example");
    await user.click(screen.getByRole("button", { name: "Fetch" }));

    expect(await screen.findByText(/could not be reached over TLS/)).toBeVisible();
  });

  test("are removed after a question", async () => {
    const user = userEvent.setup();
    const { calls } = certificatesScreen({ "DELETE /certificates/old": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Remove CN=Old CA,O=Corp" }));
    const dialog = screen.getByRole("alertdialog", { name: "Trust CN=Old CA,O=Corp no more?" });
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("CN=Old CA,O=Corp is trusted no more."),
    );
    expect(of(calls, "DELETE")).toHaveLength(1);
  });

  test("are shown, and not changed or fetched, to whoever may only read them", async () => {
    certificatesScreen({}, holding("admin:certificates:read"));

    await screen.findByRole("table", { name: "Certificates" });
    expect(screen.queryByLabelText("Host")).toBeNull();
    expect(screen.queryByLabelText("Certificate (PEM)")).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
  });
});
