import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { NewSelectorScreen, SelectorScreen, SelectorsScreen } from "./content-selectors";

const page = (items: unknown[]) => ({ items, total: items.length, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

const ACME = {
  id: "s1",
  name: "acme",
  description: "Acme's own",
  expression: 'path =^ "/com/acme/"',
  created_at: "2026-10-21T08:00:00Z",
  updated_at: "2026-10-21T08:00:00Z",
};

function render(screenOf: ReactElement, address: string, routes: Routes, session = ADMIN) {
  const api = mockApi(routes);
  navigation.at(address);
  return { ...renderUi(screenOf, { session }), ...api };
}

describe("the content selectors (spec 10)", () => {
  test("are listed with what each matches, each leading to its page", async () => {
    render(<SelectorsScreen />, "/admin/content-selectors", {
      "GET /content-selectors": { json: page([ACME]) },
    });

    const table = await screen.findByRole("table", { name: "Content selectors" });
    const row = within(table).getAllByRole("row")[1] as HTMLElement;
    expect(within(row).getByRole("link", { name: "acme" })).toHaveAttribute(
      "href",
      "/admin/content-selectors/acme",
    );
    expect(row).toHaveTextContent('path =^ "/com/acme/"');
    expect(screen.getByRole("link", { name: "New content selector" })).toBeVisible();
    await expectAccessible();
  });

  test("say so when there is none, and offer no new one to whoever may only read", async () => {
    render(
      <SelectorsScreen />,
      "/admin/content-selectors",
      { "GET /content-selectors": { json: page([]) } },
      holding("admin:selectors:read"),
    );

    expect(await screen.findByText(/No content selector is made yet/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "New content selector" })).toBeNull();
  });

  test("are made with a name, a description and an expression", async () => {
    const user = userEvent.setup();
    const { calls } = render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors": (call) => ({
        status: 201,
        json: { ...ACME, ...(call.body as object) },
      }),
    });

    await user.type(screen.getByLabelText(/^Name/), "acme");
    await user.type(screen.getByLabelText("Description"), "Acme's own");
    await user.type(screen.getByLabelText(/^Expression/), 'path =^ "/com/acme/"');
    await user.click(screen.getByRole("button", { name: "Create content selector" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Created the content selector acme."));
    expect(of(calls, "POST")[0]?.body).toEqual({
      name: "acme",
      description: "Acme's own",
      expression: 'path =^ "/com/acme/"',
    });
    expect(navigation.router.push).toHaveBeenCalledWith("/admin/content-selectors/acme");
  });

  test("say what is wrong with an expression where the server says it is", async () => {
    const user = userEvent.setup();
    render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors": failure(422, "validation_error", "The request is not valid.", [
        { field: "expression", message: "Unexpected '=' (at character 6)" },
      ]),
    });

    await user.type(screen.getByLabelText(/^Name/), "acme");
    const expression = screen.getByLabelText(/^Expression/);
    await user.type(expression, 'path = "/com/"');
    await user.click(screen.getByRole("button", { name: "Create content selector" }));

    await waitFor(() =>
      expect(expression).toHaveAccessibleDescription(/Unexpected '=' \(at character 6\)/),
    );
  });

  test("need a name of the server's rule and an expression before anything is sent", async () => {
    const user = userEvent.setup();
    const { calls } = render(<NewSelectorScreen />, "/admin/content-selectors/~new", {});

    await user.type(screen.getByLabelText(/^Name/), "with space");
    await user.click(screen.getByRole("button", { name: "Create content selector" }));

    expect(screen.getByLabelText(/^Name/)).toHaveAccessibleDescription(/1 to 64 letters/);
    expect(screen.getByLabelText(/^Expression/)).toHaveAccessibleDescription(
      /An expression is needed/,
    );
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("are tried against paths before they are saved, and say which match", async () => {
    const user = userEvent.setup();
    const { calls } = render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors/preview": {
        json: {
          paths: [
            { path: "/com/acme/app/1.0/app-1.0.jar", matches: true },
            { path: "/org/other/1.0/other-1.0.jar", matches: false },
          ],
        },
      },
    });

    await user.type(screen.getByLabelText(/^Expression/), 'path =^ "/com/acme/"');
    await user.type(
      screen.getByLabelText(/^Paths to try/),
      "/com/acme/app/1.0/app-1.0.jar{Enter}{Enter}/org/other/1.0/other-1.0.jar",
    );
    await user.click(screen.getByRole("button", { name: "Try the expression" }));

    const tried = await screen.findByRole("list", { name: "What the expression matches" });
    const items = within(tried).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Matches/com/acme/app/1.0/app-1.0.jar");
    expect(items[1]).toHaveTextContent("Does not match/org/other/1.0/other-1.0.jar");
    expect(of(calls, "POST")[0]?.body).toEqual({
      expression: 'path =^ "/com/acme/"',
      format: "maven",
      paths: ["/com/acme/app/1.0/app-1.0.jar", "/org/other/1.0/other-1.0.jar"],
    });
    expect(of(calls, "POST").map((call) => call.path)).toEqual(["/content-selectors/preview"]);
    await expectAccessible();
  });

  test("say at the expression why trying it was refused", async () => {
    const user = userEvent.setup();
    render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors/preview": failure(422, "validation_error", "Not valid.", [
        { field: "expression", message: "Expected a string in double quotes (at character 9)" },
      ]),
    });

    const expression = screen.getByLabelText(/^Expression/);
    await user.type(expression, "path == maven");
    await user.type(screen.getByLabelText(/^Paths to try/), "/x");
    await user.click(screen.getByRole("button", { name: "Try the expression" }));

    await waitFor(() => expect(expression).toHaveAccessibleDescription(/at character 9/));
  });

  test("show no result of a try once what was tried has changed", async () => {
    const user = userEvent.setup();
    render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors/preview": {
        json: { paths: [{ path: "/com/acme/x.jar", matches: true }] },
      },
    });

    const expression = screen.getByLabelText(/^Expression/);
    await user.type(expression, 'path =^ "/com/acme/"');
    await user.type(screen.getByLabelText(/^Paths to try/), "/com/acme/x.jar");
    await user.click(screen.getByRole("button", { name: "Try the expression" }));
    await screen.findByRole("list", { name: "What the expression matches" });

    await user.clear(expression);
    await user.type(expression, 'path =^ "/org/"');

    expect(screen.queryByRole("list", { name: "What the expression matches" })).toBeNull();
  });

  test("say at the expression what the last try said, not what an earlier save did", async () => {
    const user = userEvent.setup();
    render(<NewSelectorScreen />, "/admin/content-selectors/~new", {
      "POST /content-selectors": failure(422, "validation_error", "The request is not valid.", [
        { field: "expression", message: "Unexpected '=' (at character 6)" },
      ]),
      "POST /content-selectors/preview": failure(422, "validation_error", "Not valid.", [
        { field: "expression", message: "Expected a string in double quotes (at character 9)" },
      ]),
    });

    await user.type(screen.getByLabelText(/^Name/), "acme");
    const expression = screen.getByLabelText(/^Expression/);
    await user.type(expression, 'path = "/com/"');
    await user.click(screen.getByRole("button", { name: "Create content selector" }));
    await waitFor(() => expect(expression).toHaveAccessibleDescription(/at character 6/));

    await user.clear(expression);
    await user.type(expression, "path == maven");
    await user.type(screen.getByLabelText(/^Paths to try/), "/x");
    await user.click(screen.getByRole("button", { name: "Try the expression" }));

    await waitFor(() => expect(expression).toHaveAccessibleDescription(/at character 9/));
  });

  test("are changed on their page, and kept there", async () => {
    const user = userEvent.setup();
    const { calls } = render(<SelectorScreen />, "/admin/content-selectors/acme", {
      "GET /content-selectors/acme": { json: ACME },
      "PUT /content-selectors/acme": (call) => ({ json: { ...ACME, ...(call.body as object) } }),
    });

    const expression = await screen.findByLabelText(/^Expression/);
    expect(expression).toHaveValue('path =^ "/com/acme/"');
    await user.clear(expression);
    await user.type(expression, 'path =^ "/com/"');
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Saved the content selector acme."));
    expect(of(calls, "PUT")[0]?.body).toEqual({
      description: "Acme's own",
      expression: 'path =^ "/com/"',
    });
  });

  test("are shown and tried, and not changed, by whoever may only read them", async () => {
    render(
      <SelectorScreen />,
      "/admin/content-selectors/acme",
      { "GET /content-selectors/acme": { json: ACME } },
      holding("admin:selectors:read"),
    );

    expect(await screen.findByText('path =^ "/com/acme/"')).toBeVisible();
    expect(screen.getByRole("button", { name: "Try the expression" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete content selector" })).toBeNull();
  });

  test("are deleted after a question, and one a role names says so", async () => {
    const user = userEvent.setup();
    let tries = 0;
    render(<SelectorScreen />, "/admin/content-selectors/acme", {
      "GET /content-selectors/acme": { json: ACME },
      "DELETE /content-selectors/acme": () =>
        ++tries === 1
          ? failure(409, "in_use", "Roles name this content selector: acme-readers.")
          : { status: 204 },
    });

    await user.click(await screen.findByRole("button", { name: "Delete content selector" }));
    let dialog = screen.getByRole("alertdialog", { name: "Delete the content selector acme?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete content selector" }));
    expect(await screen.findByText(/Roles name this content selector: acme-readers/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Delete content selector" }));
    dialog = screen.getByRole("alertdialog", { name: "Delete the content selector acme?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete content selector" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Deleted the content selector acme."));
    expect(navigation.router.replace).toHaveBeenCalledWith("/admin/content-selectors");
  });
});
