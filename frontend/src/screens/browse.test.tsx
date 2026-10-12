import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { BrowseScreen } from "./browse";
import { ComponentScreen } from "./component";

const RELEASES = {
  name: "releases",
  format: "maven",
  type: "hosted",
  online: true,
  url: "https://repo.example.com/repository/releases/",
  members: null,
};
const READER: SessionInfo = { ...ADMIN, permissions: ["repository:maven:releases:browse"] };
const COMPONENT = { id: "0190-c0", namespace: "com.acme", name: "app", version: "1.0" };
const VERSION = "com/acme/app/1.0";

const folder = (name: string, path: string) => ({ name, path, kind: "folder" });
const file = (name: string, path: string, size = 2516582) => ({
  name,
  path,
  kind: "file",
  size,
  modified: "2026-10-09T08:00:00Z",
  component: COMPONENT,
});
const JAR = file("app-1.0.jar", `${VERSION}/app-1.0.jar`);
const POM = file("app-1.0.pom", `${VERSION}/app-1.0.pom`, 408);
const ASSET = {
  path: JAR.path,
  size: 2516582,
  content_type: "application/java-archive",
  md5: "d41d8cd98f00b204e9800998ecf8427e",
  sha1: "2ef7bde608ce5404e97d5f042f95f89f1c232871",
  sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  sha512: "a".repeat(128),
  blob_store: "default",
  created_by: "ci",
  created: "2026-10-09T08:00:00Z",
  modified: "2026-10-09T08:00:00Z",
  last_downloaded: null,
  last_verified: null,
  component: COMPONENT,
  download: `https://repo.example.com/repository/releases/${VERSION}/app-1.0.jar`,
};

/** The API of a server that holds one version of one artifact. */
function server(more: Routes = {}) {
  return mockApi({
    "GET /content/releases": { json: RELEASES },
    "GET /content/releases/tree": { json: { items: [JAR, POM], next: null } },
    "GET /content/releases/asset": { json: ASSET },
    ...more,
  });
}

function at(address: string, session: SessionInfo = ADMIN) {
  navigation.at(address);
  return renderUi(<BrowseScreen />, { session });
}

describe("a folder of a repository", () => {
  test("is the way there, and what is in it", async () => {
    const { calls } = server();
    at(`/browse/releases/${VERSION}`);

    const table = await screen.findByRole("table", { name: `What is in ${VERSION}` });
    const rows = within(table).getAllByRole("row").slice(1);

    const title = screen.getByRole("heading", { level: 1, name: "releases" });
    expect(title).not.toHaveClass("uppercase"); // a name tells capitals from small letters
    expect(screen.getByText("maven repository, Hosted")).toBeVisible();
    const crumbs = within(screen.getByRole("navigation", { name: "Path" })).getAllByRole("link");
    expect(crumbs.map((crumb) => [crumb.textContent, crumb.getAttribute("href")])).toEqual([
      ["releases", "/browse/releases"],
      ["com", "/browse/releases/com"],
      ["acme", "/browse/releases/com/acme"],
      ["app", "/browse/releases/com/acme/app"],
      ["1.0", `/browse/releases/${VERSION}`],
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("app-1.0.jar");
    expect(rows[0]).toHaveTextContent("2.4 MiB");
    expect(rows[1]).toHaveTextContent("408 B");
    expect(calls.map((call) => call.path)).toContain(
      "/content/releases/tree?path=com%2Facme%2Fapp%2F1.0&limit=100",
    );
    await expectAccessible();
  });

  test("leads into a folder, and to a file's details without leaving the folder", async () => {
    server({
      "GET /content/releases/tree": {
        json: {
          items: [folder("1.0", VERSION), file("notes.txt", "com/acme/app/notes.txt")],
          next: null,
        },
      },
    });
    at("/browse/releases/com/acme/app");

    expect(await screen.findByRole("link", { name: "Folder 1.0" })).toHaveAttribute(
      "href",
      `/browse/releases/${VERSION}`,
    );
    expect(screen.getByRole("link", { name: "File notes.txt" })).toHaveAttribute(
      "href",
      "/browse/releases/com/acme/app?file=notes.txt",
    );
  });

  test("shows more of a long folder when asked, and no more than was asked for", async () => {
    const user = userEvent.setup();
    const { calls } = server({
      "GET /content/releases/tree": (call) =>
        call.path.includes("after=")
          ? { json: { items: [POM], next: null } }
          : { json: { items: [JAR], next: JAR.path } },
    });
    at(`/browse/releases/${VERSION}`);

    await user.click(await screen.findByRole("button", { name: "Show more" }));

    expect(await screen.findByText("app-1.0.pom")).toBeVisible();
    expect(screen.getByText("app-1.0.jar")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
    // The button is gone with the last piece: the keyboard is at the first entry it brought.
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "File app-1.0.pom" })).toHaveFocus(),
    );
    const trees = calls.filter((call) => call.path.startsWith("/content/releases/tree"));
    expect(trees[1]?.path).toContain(`after=${encodeURIComponent(JAR.path)}`);
  });

  test("says so when it holds nothing, and offers an upload to whoever may", async () => {
    server({ "GET /content/releases/tree": { json: { items: [], next: null } } });
    at("/browse/releases");

    expect(await screen.findByRole("heading", { name: "Nothing here yet" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Upload here" })[0]).toHaveAttribute(
      "href",
      "/upload/releases",
    );
  });

  test("says so when there is no such folder", async () => {
    server({ "GET /content/releases/tree": failure(404, "not_found", "No such folder.") });
    at("/browse/releases/no/such");

    expect(await screen.findByRole("heading", { name: "No such folder" })).toBeVisible();
    expect(screen.getByText("There is nothing at no/such in this repository.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Go to the top of releases" })).toHaveAttribute(
      "href",
      "/browse/releases",
    );
    expect(screen.queryByRole("button", { name: "Delete folder" })).toBeNull();
  });

  test("says what went wrong when the repository cannot be shown", async () => {
    mockApi({
      "GET /content/secret": failure(403, "forbidden", "You do not have permission to do this."),
    });
    at("/browse/secret");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
  });

  test("offers no upload and no delete to whoever may only look (UI-2)", async () => {
    server();
    at(`/browse/releases/${VERSION}?file=app-1.0.jar`, READER);

    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });
    await within(details).findByText("application/java-archive");

    expect(screen.queryByRole("link", { name: "Upload here" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete folder" })).toBeNull();
    expect(within(details).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(within(details).getByRole("link", { name: "Download" })).toBeVisible(); // the server decides
  });

  test("says of a proxy that it shows what was fetched through it", async () => {
    server({ "GET /content/releases": { json: { ...RELEASES, type: "proxy" } } });
    at("/browse/releases");

    expect(
      await screen.findByText(
        "maven repository, Proxy. What is here is what has been fetched through it.",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("link", { name: "Upload here" })).toBeNull();
  });

  test("says that an offline repository can still be browsed", async () => {
    server({ "GET /content/releases": { json: { ...RELEASES, online: false } } });
    at("/browse/releases");

    expect(await screen.findByRole("alert")).toHaveTextContent("This repository is offline");
  });

  test("shows a name as text, and puts it into an address as one segment", async () => {
    const odd = '<img src=x onerror="alert(1)">#?&';
    server({
      "GET /content/releases/tree": {
        json: { items: [folder(odd, odd), file(odd, `dir/${odd}`)], next: null },
      },
    });
    const { container } = at("/browse/releases/dir");

    const link = await screen.findByRole("link", { name: `Folder ${odd}` });
    const address = new URL(link.getAttribute("href") ?? "", "https://ui.test");

    expect(container.querySelector("img")).toBeNull();
    expect(address.hash).toBe("");
    expect(address.search).toBe("");
    expect(decodeURIComponent(address.pathname.split("/").pop() ?? "")).toBe(odd);
    const chosen = new URL(
      screen.getByRole("link", { name: `File ${odd}` }).getAttribute("href") ?? "",
      "https://ui.test",
    );
    expect(chosen.searchParams.get("file")).toBe(odd);
  });
});

describe("an address that cannot be read", () => {
  test("is nothing's, said inside the shell and not as a page of its own", () => {
    mockApi({});
    navigation.at("/browse/%E0%A4%A");
    const { container } = renderUi(<BrowseScreen />, { session: ADMIN });

    expect(
      screen.getByRole("heading", { level: 1, name: "There is nothing at this address" }),
    ).toBeVisible();
    expect(container.querySelector("main")).toBeNull();
  });
});

describe("a group", () => {
  test("holds nothing of its own, and names its members, each a way in", async () => {
    const { calls } = mockApi({
      "GET /content/all": {
        json: { ...RELEASES, name: "all", type: "group", members: ["releases", "central"] },
      },
    });
    at("/browse/all");

    const members = await screen.findAllByRole("listitem");

    expect(screen.getByRole("heading", { name: "Members" })).toBeVisible();
    expect(members.map((member) => member.textContent)).toEqual(
      expect.arrayContaining(["releases", "central"]),
    );
    expect(screen.getByRole("link", { name: "central" })).toHaveAttribute(
      "href",
      "/browse/central",
    );
    expect(calls.some((call) => call.path.includes("/tree"))).toBe(false); // which a group refuses
    // Nor is a search in it offered: search looks in what holds components, and would
    // find nothing in a group.
    expect(screen.queryByRole("link", { name: "Search this repository" })).toBeNull();
    await expectAccessible();
  });

  test("of any other kind offers a search in it", async () => {
    server();
    at("/browse/releases");

    expect(await screen.findByRole("link", { name: "Search this repository" })).toHaveAttribute(
      "href",
      "/search?repository=releases",
    );
  });
});

describe("where the keyboard is after the screen changed under it", () => {
  const current = () =>
    within(screen.getByRole("navigation", { name: "Path" })).getByRole("link", { current: "page" });

  test("is at the folder that was entered, and nowhere in particular on arrival", async () => {
    server();
    const { rerender } = at("/browse/releases/com");
    await screen.findByRole("table");
    expect(current()).not.toHaveFocus(); // on arrival the page starts at its top

    navigation.at("/browse/releases/com/acme");
    rerender(<BrowseScreen />);

    // The link that was followed is gone with the list it was in.
    await waitFor(() => expect(current()).toHaveFocus());
    expect(current()).toHaveTextContent("acme");
  });

  test("is at the folder that was entered when the screen is built anew for it", async () => {
    // Next.js builds the screen anew when a part of its address changes: the screen
    // cannot itself remember where it was.
    server();
    const before = at("/browse/releases/com");
    await screen.findByRole("table");
    before.unmount();

    at("/browse/releases/com/acme");

    await waitFor(() => expect(current()).toHaveFocus());
  });

  test("is at a file's details when the folder is entered with a file chosen", async () => {
    server();
    const before = at("/browse/releases/com");
    await screen.findByRole("table");
    before.unmount();

    at(`/browse/releases/${VERSION}?file=app-1.0.jar`);
    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });
    await within(details).findByText("application/java-archive");

    expect(within(details).getByRole("heading", { name: "app-1.0.jar" })).toHaveFocus();
  });

  test("is at the file whose details were closed", async () => {
    server();
    const { rerender } = at(`/browse/releases/${VERSION}?file=app-1.0.pom`);
    await screen.findByRole("region", { name: "Details of app-1.0.pom" });

    navigation.at(`/browse/releases/${VERSION}`);
    rerender(<BrowseScreen />);

    await waitFor(() =>
      expect(screen.getByRole("link", { name: "File app-1.0.pom" })).toHaveFocus(),
    );
  });

  test("is at the folder when the file whose details were shown is gone", async () => {
    let deleted = false;
    server({
      "GET /content/releases/tree": () => ({
        json: { items: deleted ? [POM] : [JAR, POM], next: null },
      }),
    });
    const { rerender, client } = at(`/browse/releases/${VERSION}?file=app-1.0.jar`);
    await screen.findByRole("region", { name: "Details of app-1.0.jar" });

    deleted = true;
    await client.invalidateQueries();
    navigation.at(`/browse/releases/${VERSION}`);
    rerender(<BrowseScreen />);

    await waitFor(() => expect(current()).toHaveFocus());
  });
});

describe("a file's details", () => {
  test("are everything the API says of it, beside the folder it is in", async () => {
    const { calls } = server();
    at(`/browse/releases/${VERSION}?file=app-1.0.jar`);

    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });
    await within(details).findByText("application/java-archive");

    for (const said of [
      JAR.path,
      "2.4 MiB",
      ASSET.sha1,
      ASSET.sha256,
      ASSET.md5,
      "default",
      "ci",
      "Never",
    ]) {
      expect(within(details).getByText(said)).toBeVisible();
    }
    expect(within(details).getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      ASSET.download,
    );
    expect(within(details).getByRole("link", { name: "com.acme : app : 1.0" })).toHaveAttribute(
      "href",
      "/components/releases/0190-c0",
    );
    expect(within(details).getByRole("button", { name: "Copy SHA-256" })).toBeVisible();
    expect(calls.map((call) => call.path)).toContain(
      `/content/releases/asset?path=${encodeURIComponent(JAR.path)}`,
    );
    // The folder is still there, with the file marked in it.
    expect(screen.getByRole("link", { name: "File app-1.0.jar" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    await expectAccessible();
  });

  test("take the keyboard when a file is chosen, and give a way back", async () => {
    server();
    at(`/browse/releases/${VERSION}?file=app-1.0.jar`);

    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });

    expect(within(details).getByRole("heading", { name: "app-1.0.jar" })).toHaveFocus();
    expect(within(details).getByRole("link", { name: "Close the details" })).toHaveAttribute(
      "href",
      `/browse/releases/${VERSION}`,
    );
  });

  test("say so when there is no such file", async () => {
    server({ "GET /content/releases/asset": failure(404, "not_found", "No such file.") });
    at(`/browse/releases/${VERSION}?file=gone.jar`);

    const details = await screen.findByRole("region", { name: "Details of gone.jar" });

    expect(await within(details).findByRole("alert")).toHaveTextContent("This was not found.");
  });

  test("have no download where a file has no address of its own", async () => {
    server({
      "GET /content/releases/asset": { json: { ...ASSET, download: null, component: null } },
    });
    at(`/browse/releases/${VERSION}?file=app-1.0.jar`);

    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });
    await within(details).findByText("application/java-archive");

    expect(within(details).queryByRole("link", { name: "Download" })).toBeNull();
    expect(within(details).queryByText("Part of")).toBeNull();
  });

  test("have no download to an address that is not a web address", async () => {
    server({
      "GET /content/releases/asset": { json: { ...ASSET, download: "javascript:alert(1)" } },
    });
    const { container } = at(`/browse/releases/${VERSION}?file=app-1.0.jar`);

    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });
    await within(details).findByText("application/java-archive");

    expect(within(details).queryByRole("link", { name: "Download" })).toBeNull();
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  });
});

describe("deleting", () => {
  test("a file asks first, then says it is gone and returns to the folder", async () => {
    const user = userEvent.setup();
    const { calls } = server({ "DELETE /content/releases/asset": { status: 204 } });
    at(`/browse/releases/${VERSION}?file=app-1.0.jar`);
    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });

    await user.click(await within(details).findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete app-1.0.jar?" });
    expect(calls.some((call) => call.method === "DELETE")).toBe(false); // not before it is confirmed
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith(`/browse/releases/${VERSION}`, {
        scroll: false,
      }),
    );
    expect(calls.find((call) => call.method === "DELETE")?.path).toBe(
      `/content/releases/asset?path=${encodeURIComponent(JAR.path)}`,
    );
    expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent(
      "Deleted app-1.0.jar.",
    );
    // It is gone, and is not asked for again while the screen returns to the folder: the
    // answer would be that there is no such file, shown where its details were.
    await new Promise((resolve) => setTimeout(resolve, 50));
    const since = calls.slice(calls.findIndex((call) => call.method === "DELETE") + 1);
    expect(since.filter((call) => call.path.startsWith("/content/releases/asset"))).toEqual([]);
    expect(within(details).queryByRole("alert")).toBeNull();
  });

  test("a file the format keeps is not deleted, and the screen says why", async () => {
    const user = userEvent.setup();
    server({
      "DELETE /content/releases/asset": failure(
        409,
        "managed_by_format",
        "A package's dist-tags are the registry's. They go with its last version.",
      ),
    });
    const { rerender } = at(`/browse/releases/${VERSION}?file=app-1.0.jar`);
    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });

    await user.click(await within(details).findByRole("button", { name: "Delete" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );

    expect(await within(details).findByRole("alert")).toHaveTextContent(
      "They go with its last version.",
    );
    expect(navigation.router.replace).not.toHaveBeenCalled();

    // It is said of that file, and not of the next one that is chosen.
    navigation.at(`/browse/releases/${VERSION}?file=app-1.0.pom`);
    rerender(<BrowseScreen />);
    const next = await screen.findByRole("region", { name: "Details of app-1.0.pom" });
    await within(next).findByText("application/java-archive");
    expect(within(next).queryByRole("alert")).toBeNull();
  });

  test("a folder asks for its name, deletes in pieces, and says how many went", async () => {
    const user = userEvent.setup();
    const pieces = [
      { deleted: 1000, skipped: 0, next: `${VERSION}/x` },
      { deleted: 2, skipped: 0, next: null },
    ];
    const { calls } = server({ "DELETE /content/releases/tree": () => ({ json: pieces.shift() }) });
    at(`/browse/releases/${VERSION}`);

    await user.click(await screen.findByRole("button", { name: "Delete folder" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the folder 1.0?" });
    expect(dialog).toHaveTextContent(`Every file under ${VERSION} is deleted.`);
    expect(within(dialog).getByRole("button", { name: "Delete folder" })).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Type 1.0 to go on"), "1.0");
    await user.click(within(dialog).getByRole("button", { name: "Delete folder" }));

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/browse/releases/com/acme/app"),
    );
    expect(calls.filter((call) => call.method === "DELETE")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent(
      "Deleted 1,002 files under 1.0.",
    );
  });

  test("a folder says how many files the format kept, and stays where they are", async () => {
    const user = userEvent.setup();
    server({ "DELETE /content/releases/tree": { json: { deleted: 3, skipped: 1, next: null } } });
    at(`/browse/releases/${VERSION}`);

    await user.click(await screen.findByRole("button", { name: "Delete folder" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type 1.0 to go on"), "1.0");
    await user.click(within(dialog).getByRole("button", { name: "Delete folder" }));

    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent(
        "Deleted 3 files under 1.0. 1 file is kept by the format.",
      ),
    );
    expect(navigation.router.replace).not.toHaveBeenCalled();

    // Asked again, the name is typed again: the dialog is not left armed.
    await user.click(screen.getByRole("button", { name: "Delete folder" }));
    const again = screen.getByRole("alertdialog");
    expect(within(again).getByLabelText("Type 1.0 to go on")).toHaveValue("");
    expect(within(again).getByRole("button", { name: "Delete folder" })).toBeDisabled();
  });

  test("a folder that could not be deleted says why, in the dialog that asked", async () => {
    const user = userEvent.setup();
    server({
      "DELETE /content/releases/tree": failure(
        403,
        "repository_read_only",
        "This repository is read-only.",
      ),
    });
    at(`/browse/releases/${VERSION}`);

    await user.click(await screen.findByRole("button", { name: "Delete folder" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type 1.0 to go on"), "1.0");
    await user.click(within(dialog).getByRole("button", { name: "Delete folder" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This repository is read-only.",
    );

    // Closed and asked again, the dialog starts afresh: what went wrong before is not
    // said of a try that has not been made.
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Delete folder" }));
    expect(within(screen.getByRole("alertdialog")).queryByRole("alert")).toBeNull();
  });

  test("a folder delete that the session no longer covers makes the session be asked again", async () => {
    const user = userEvent.setup();
    const { calls } = server({
      "DELETE /content/releases/tree": failure(401, "unauthorized", "Sign in."),
      "GET /auth/session": { json: ADMIN },
    });
    at(`/browse/releases/${VERSION}`);

    await user.click(await screen.findByRole("button", { name: "Delete folder" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type 1.0 to go on"), "1.0");
    await user.click(within(dialog).getByRole("button", { name: "Delete folder" }));

    await waitFor(() => expect(calls.some((call) => call.path === "/auth/session")).toBe(true));
  });
});

describe("a component", () => {
  const DETAIL = {
    ...COMPONENT,
    created: "2026-10-09T08:00:00Z",
    modified: "2026-10-09T08:00:00Z",
    files: [JAR, POM],
    usage: [
      {
        label: "Maven",
        language: "xml",
        text: "<dependency>\n  <artifactId>app</artifactId>\n</dependency>",
      },
      { label: "Gradle (Kotlin)", language: "kotlin", text: 'implementation("com.acme:app:1.0")' },
    ],
  };

  function component(more: Routes = {}, session: SessionInfo = ADMIN) {
    const api = mockApi({
      "GET /content/releases": { json: RELEASES },
      "GET /content/releases/components/0190-c0": { json: DETAIL },
      ...more,
    });
    navigation.at("/components/releases/0190-c0");
    return { ...renderUi(<ComponentScreen />, { session }), ...api };
  }

  test("is what it is, its files, and how to use it, each snippet to copy", async () => {
    const user = userEvent.setup();
    component();

    expect(await screen.findByRole("heading", { level: 1, name: "app 1.0" })).toBeVisible();
    for (const said of ["com.acme", "maven"]) expect(screen.getAllByText(said)[0]).toBeVisible();
    expect(screen.getByRole("link", { name: JAR.path })).toHaveAttribute(
      "href",
      `/browse/releases/${VERSION}?file=app-1.0.jar`,
    );
    expect(screen.getByText('implementation("com.acme:app:1.0")')).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Copy Gradle (Kotlin)" }));
    expect(await navigator.clipboard.readText()).toBe('implementation("com.acme:app:1.0")');
    await expectAccessible();
  });

  test("says so when its kind has nothing to copy", async () => {
    component({
      "GET /content/releases/components/0190-c0": { json: { ...DETAIL, usage: [], version: "" } },
    });

    expect(await screen.findByText(/has no command to copy/)).toBeVisible();
    expect(screen.getByRole("heading", { level: 1, name: "app" })).toBeVisible();
  });

  test("is deleted as a version, after asking, by whoever may", async () => {
    const user = userEvent.setup();
    const { calls } = component({ "DELETE /content/releases/components/0190-c0": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete this version" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete app 1.0?" });
    expect(dialog).toHaveTextContent("Its 2 files are deleted");
    await user.click(within(dialog).getByRole("button", { name: "Delete this version" }));

    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/browse/releases"));
    expect(calls.some((call) => call.method === "DELETE")).toBe(true);
    expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent(
      "Deleted app 1.0.",
    );
    // Nor is the version asked for again: it is gone.
    await new Promise((resolve) => setTimeout(resolve, 50));
    const since = calls.slice(calls.findIndex((call) => call.method === "DELETE") + 1);
    expect(since.filter((call) => call.path.includes("/components/"))).toEqual([]);
  });

  test("offers no delete to whoever may only look", async () => {
    component({}, READER);

    await screen.findByRole("heading", { level: 1, name: "app 1.0" });

    expect(screen.queryByRole("button", { name: "Delete this version" })).toBeNull();
  });

  test("says so when there is none", async () => {
    component({
      "GET /content/releases/components/0190-c0": failure(404, "not_found", "No such component."),
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("This was not found.");
  });
});
