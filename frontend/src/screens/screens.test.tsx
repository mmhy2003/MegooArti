import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Answer } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, NOBODY, renderUi } from "@/test/render";

import { ChangePasswordScreen } from "./change-password";
import { HomeScreen } from "./home";
import { NotFoundScreen } from "./not-found";
import { SignInScreen } from "./sign-in";

async function fillIn(label: string, text: string) {
  await userEvent.type(screen.getByLabelText(label), text);
}

describe("signing in", () => {
  /** The API of a server where `password` is right for anyone, and the cookie is kept or not. */
  function server({ cookieKept = true }: { cookieKept?: boolean } = {}) {
    let signedIn = false;
    return mockApi({
      "POST /auth/login": (call) => {
        const body = call.body as { password: string };
        if (body.password !== "right") {
          return failure(401, "unauthorized", "The username or password is not correct.");
        }
        signedIn = cookieKept;
        return { json: ADMIN };
      },
      "GET /auth/session": () => ({ json: signedIn ? ADMIN : NOBODY }),
      "GET /auth/sources": { json: { items: [], total: 0, limit: 200, offset: 0 } },
    });
  }

  test("is a form with labels, used by keyboard alone (UI-6)", async () => {
    const user = userEvent.setup();
    const { calls } = server();
    const { client } = renderUi(<SignInScreen />, { session: NOBODY });

    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    expect(screen.getByLabelText("User name")).toHaveFocus();
    await expectAccessible();

    await user.keyboard("ada{Tab}right{Enter}");

    await waitFor(() => expect(client.getQueryData(["session"])).toEqual(ADMIN));
    expect(calls.find((call) => call.method === "POST")).toMatchObject({
      path: "/auth/login",
      body: { username: "ada", password: "right" },
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("cannot be sent with nothing in it", async () => {
    server();
    renderUi(<SignInScreen />, { session: NOBODY });

    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    await fillIn("User name", "ada");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    await fillIn("Password", "x");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  test("says that the name or the password is wrong, and not which", async () => {
    const user = userEvent.setup();
    server();
    const { client } = renderUi(<SignInScreen />, { session: NOBODY });

    await fillIn("User name", "ada");
    await fillIn("Password", "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The user name or the password is not correct.",
    );
    expect(client.getQueryData<SessionInfo>(["session"])?.authenticated).toBe(false);
    expect(screen.getByLabelText("Password")).toHaveValue("wrong"); // nothing typed is lost
    await expectAccessible();
  });

  test("says to wait after too many attempts", async () => {
    const user = userEvent.setup();
    mockApi({
      "POST /auth/login": failure(429, "too_many_attempts", "Too many attempts."),
      "GET /auth/session": { json: NOBODY },
    });
    renderUi(<SignInScreen />, { session: NOBODY });

    await fillIn("User name", "ada");
    await fillIn("Password", "right");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts. Wait a little");
  });

  test("says why when the browser did not keep the session", async () => {
    const user = userEvent.setup();
    server({ cookieKept: false });
    const { client } = renderUi(<SignInScreen />, { session: NOBODY });

    await fillIn("User name", "ada");
    await fillIn("Password", "right");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your browser did not keep the session");
    expect(alert).toHaveTextContent("MEGOOARTI_SESSION_COOKIE_SECURE=false");
    expect(client.getQueryData<SessionInfo>(["session"])?.authenticated).toBe(false);
  });

  test("says so when the server cannot be reached", async () => {
    const user = userEvent.setup();
    mockApi({ "POST /auth/login": "network-failure" });
    renderUi(<SignInScreen />, { session: NOBODY });

    await fillIn("User name", "ada");
    await fillIn("Password", "right");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The server could not be reached.");
  });
});

describe("signing in at a provider (spec 5)", () => {
  const SOURCES = {
    items: [
      { id: "id-of-corp", name: "Corp SSO", kind: "oidc" },
      { id: "id-of-lab", name: "Lab SSO", kind: "oidc" },
    ],
    total: 2,
    limit: 200,
    offset: 0,
  };

  test("offers each provider, leaving for it with where to go after", async () => {
    mockApi({ "GET /auth/sources": { json: SOURCES } });
    navigation.at("/login?next=%2Fsearch%3Fq%3Dcommons");
    renderUi(<SignInScreen />, { session: NOBODY });

    const corp = await screen.findByRole("link", { name: "Sign in with Corp SSO" });
    expect(corp).toHaveAttribute(
      "href",
      "/api/v1/auth/oidc/id-of-corp/start?next=%2Fsearch%3Fq%3Dcommons",
    );
    expect(screen.getByRole("link", { name: "Sign in with Lab SSO" })).toBeVisible();
    expect(screen.getByLabelText("User name")).toBeVisible(); // a password still signs in
    await expectAccessible();
  });

  test("offers none where there is none, or where they cannot be asked for", async () => {
    mockApi({ "GET /auth/sources": failure(404, "not_found", "Not found.") });
    navigation.at("/login");
    renderUi(<SignInScreen />, { session: NOBODY });

    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeVisible());
    expect(screen.queryByText("or")).toBeNull();
    expect(screen.queryByRole("link", { name: /Sign in with/ })).toBeNull();
  });

  test.each([
    ["denied", "The provider did not let you sign in."],
    ["refused", "You may not sign in here. Ask the administrator."],
    ["expired", "The sign-in took too long"],
    ["unavailable", "The provider cannot be reached now."],
    ["failed", "Signing in at the provider did not work."],
    ["something-else", "Signing in at the provider did not work."],
  ])("says why a sign-in came back with %s", async (error, said) => {
    mockApi({ "GET /auth/sources": { json: SOURCES } });
    navigation.at(`/login?error=${error}&next=%2Fsearch`);
    renderUi(<SignInScreen />, { session: NOBODY });

    expect(await screen.findByRole("alert")).toHaveTextContent(said);
  });

  test("says why when the browser did not keep the session the provider's sign-in made", async () => {
    mockApi({ "GET /auth/sources": { json: SOURCES } });
    // The gate shows this screen after a sign-in only when the session is not there.
    navigation.at("/login?signed_in=1&next=%2Fsearch");
    renderUi(<SignInScreen />, { session: NOBODY });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your browser did not keep the session",
    );
  });
});

describe("changing a password", () => {
  const PENDING: SessionInfo = { ...ADMIN, must_change_password: true };

  function server(answer: Answer = { status: 204 }) {
    let changed = false;
    return mockApi({
      "PUT /me/password": () => {
        if (answer !== "network-failure" && (answer.status ?? 200) < 300) changed = true;
        return answer;
      },
      "GET /auth/session": () => ({ json: changed ? ADMIN : PENDING }),
    });
  }

  async function send(current: string, next: string, repeat = next) {
    await fillIn("Current password", current);
    await fillIn("New password", next);
    await fillIn("New password, again", repeat);
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
  }

  test("sends the two passwords, says it is done, and empties the form", async () => {
    const { calls } = server();
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    expect(screen.getByRole("heading", { level: 1, name: "Change password" })).toBeVisible();
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      "At least 8 characters.",
    );
    await expectAccessible();
    await send("the old one", "a new password");

    expect(await screen.findByText("Your password is changed.")).toBeVisible();
    expect(calls[0]).toMatchObject({
      method: "PUT",
      path: "/me/password",
      body: { current_password: "the old one", new_password: "a new password" },
    });
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  test("for whoever was made to: says why they are here, and goes on when it is done", async () => {
    server();
    const { client } = renderUi(<ChangePasswordScreen />, { session: PENDING });

    expect(screen.getByRole("heading", { level: 1, name: "Choose a new password" })).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Your password was set for you.");
    await send("generated", "my own password");

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/"));
    expect(client.getQueryData<SessionInfo>(["session"])?.must_change_password).toBe(false);
  });

  test.each([
    ["short", "short", "New password", "at least 8 characters"],
    ["the same one", "the same one", "New password", "must be different"],
    ["a new password", "a new passw0rd", "New password, again", "are not the same"],
  ])(
    "refuses %j before asking the server, at the field that is wrong",
    async (next, repeat, label, words) => {
      const { calls } = server();
      renderUi(<ChangePasswordScreen />, { session: ADMIN });

      await send("the same one", next, repeat);

      const field = screen.getByLabelText(label);
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field).toHaveAccessibleDescription(expect.stringContaining(words));
      // The keyboard goes to what is wrong, so a screen reader reads the field and why.
      await waitFor(() => expect(field).toHaveFocus());
      expect(calls).toHaveLength(0);
    },
  );

  test("puts what the server refuses at the field it is about", async () => {
    server(
      failure(422, "validation_error", "The request is not valid.", [
        { field: "body.current_password", message: "The current password is not correct." },
      ]),
    );
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    await send("not it", "a new password");

    await waitFor(() =>
      expect(screen.getByLabelText("Current password")).toHaveAccessibleDescription(
        "The current password is not correct.",
      ),
    );
    await waitFor(() => expect(screen.getByLabelText("Current password")).toHaveFocus());
    expect(screen.queryByText("Your password is changed.")).toBeNull();
  });

  test("puts a refusal of the new password at the new password", async () => {
    server(
      failure(422, "validation_error", "The request is not valid.", [
        { field: "password", message: "The password must not be the same as the username." },
      ]),
    );
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    await send("the old one", "adminadmin");

    await waitFor(() =>
      expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
        "The password must not be the same as the username.",
      ),
    );
  });

  test("says so when it failed for a reason that is no field's", async () => {
    server(failure(500, "internal_error", "Something failed."));
    renderUi(<ChangePasswordScreen />, { session: ADMIN });

    await send("the old one", "a new password");

    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
    expect(screen.getByLabelText("Current password")).toHaveValue("the old one");
  });
});

describe("the home screen", () => {
  const page = (...names: string[]) => ({
    items: names.map((name, index) => ({
      name,
      format: index % 2 ? "npm" : "maven",
      type: ["hosted", "proxy", "group"][index % 3],
      online: index !== 1,
      url: `https://repo.example.com/repository/${name}/`,
      members: null,
    })),
    total: names.length,
    limit: 200,
    offset: 0,
  });

  test("lists the repositories a caller may browse", async () => {
    const { calls } = mockApi({ "GET /content": { json: page("releases", "npmjs", "all") } });
    renderUi(<HomeScreen />, { session: ADMIN });

    await screen.findByText("releases");
    const table = screen.getByRole("table", { name: "Repositories" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(calls[0]?.path).toBe("/content?limit=200");
    expect(rows.map((row) => within(row).getAllByRole("cell")[0]?.textContent)).toEqual([
      "releases",
      "npmjs",
      "all",
    ]);
    expect(within(rows[0] as HTMLElement).getByRole("link", { name: "releases" })).toHaveAttribute(
      "href",
      "/browse/releases",
    );
    expect(rows[0]).toHaveTextContent("Hosted");
    expect(rows[0]).toHaveTextContent("Online");
    expect(rows[1]).toHaveTextContent("Proxy");
    expect(rows[1]).toHaveTextContent("Offline");
    expect(rows[2]).toHaveTextContent("Group");
    expect(rows[0]).toHaveTextContent("https://repo.example.com/repository/releases/");
    expect(
      within(rows[0] as HTMLElement).getByRole("button", {
        name: "Copy https://repo.example.com/repository/releases/",
      }),
    ).toBeVisible();
    await expectAccessible();
  });

  test("says it is loading, in a shape of what is coming", async () => {
    mockApi({ "GET /content": { json: page("releases") } });
    renderUi(<HomeScreen />, { session: ADMIN });

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(screen.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();

    await screen.findByText("releases");
    expect(screen.queryByText("Loading")).toBeNull();
  });

  test("says so when there is none, and who makes them", async () => {
    mockApi({ "GET /content": { json: page() } });
    renderUi(<HomeScreen />, { session: ADMIN });

    expect(await screen.findByRole("heading", { name: "No repositories" })).toBeVisible();
    expect(screen.getByText(/An administrator creates repositories/)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
    await expectAccessible();
  });

  test("says what went wrong, and tries again when asked", async () => {
    const user = userEvent.setup();
    let working = false;
    mockApi({
      "GET /content": () =>
        working
          ? { json: page("releases") }
          : failure(403, "forbidden", "You do not have permission to do this."),
    });
    renderUi(<HomeScreen />, { session: ADMIN });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You do not have permission to do this.");
    expect(alert).toHaveTextContent("Code forbidden");
    working = true;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("releases")).toBeVisible();
  });

  test("says when there are more than it shows", async () => {
    mockApi({ "GET /content": { json: { ...page("a", "b"), total: 250 } } });
    renderUi(<HomeScreen />, { session: ADMIN });

    expect(await screen.findByText("Showing 2 of 250.")).toBeVisible();
  });

  test("shows a name as text, whatever is in it", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    mockApi({ "GET /content": { json: page(hostile) } });
    const { container } = renderUi(<HomeScreen />, { session: ADMIN });

    expect(await screen.findByText(hostile)).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
  });

  test("shows a kind of repository it has no word for as the API named it", async () => {
    const odd = page("x");
    odd.items[0] = { ...odd.items[0]!, type: "mirror" };
    mockApi({ "GET /content": { json: odd } });
    renderUi(<HomeScreen />, { session: ADMIN });

    expect(await screen.findByText("mirror")).toBeVisible();
  });
});

describe("an address with nothing at it", () => {
  test("says so, and leads home", async () => {
    renderUi(<NotFoundScreen />);

    // The page's one heading: a screen reader's list of headings starts with it.
    expect(
      screen.getByRole("heading", { level: 1, name: "There is nothing at this address" }),
    ).toBeVisible();
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Go to the repositories" })).toHaveAttribute(
      "href",
      "/",
    );
    await expectAccessible();
  });
});
