import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { SearchBox } from "@/components/search-box";
import { failure, mockApi, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { SearchScreen } from "./search";

const REPOSITORIES = [
  { name: "releases", format: "maven", type: "hosted", online: true, url: "", members: null },
  { name: "npm-all", format: "npm", type: "group", online: true, url: "", members: ["npm-own"] },
  { name: "npm-own", format: "npm", type: "hosted", online: true, url: "", members: null },
];
const APP = {
  id: "0190-c0",
  repository: "releases",
  format: "maven",
  namespace: "com.acme",
  name: "app",
  version: "1.0",
  created: "2026-10-09T08:00:00Z",
  modified: "2026-10-09T08:00:00Z",
};
const SHA1 = "2ef7bde608ce5404e97d5f042f95f89f1c232871";

function server(more: Routes = {}) {
  return mockApi({
    "GET /content": { json: { items: REPOSITORIES, total: 3 } },
    "GET /search": { json: { items: [APP], total: 1 } },
    ...more,
  });
}

function at(address: string) {
  navigation.at(address);
  return renderUi(<SearchScreen />, { session: ADMIN });
}

const asked = (calls: { path: string }[]) =>
  calls
    .filter((call) => call.path.startsWith("/search"))
    .map((call) => Object.fromEntries(new URL(call.path, "https://ui.test").searchParams));

describe("searching", () => {
  test("asks for what the address says, and lists what was found", async () => {
    const { calls } = server();
    at("/search?q=app&format=maven");

    const table = await screen.findByRole("table", { name: "Results" });
    const row = within(table).getAllByRole("row")[1] as HTMLElement;

    expect(asked(calls)).toEqual([{ q: "app", format: "maven", limit: "50", offset: "0" }]);
    expect(screen.getByText("1 component found.")).toBeVisible();
    for (const said of ["com.acme", "1.0", "maven"]) expect(row).toHaveTextContent(said);
    expect(within(row).getByRole("link", { name: "app" })).toHaveAttribute(
      "href",
      "/components/releases/0190-c0",
    );
    expect(within(row).getByRole("link", { name: "releases" })).toHaveAttribute(
      "href",
      "/browse/releases",
    );
    expect(screen.getByLabelText("Words")).toHaveValue("app");
    expect(screen.getByLabelText("Format")).toHaveValue("maven");
    await expectAccessible();
  });

  test("puts what was typed into the address, so that it can be shared and gone back to", async () => {
    const user = userEvent.setup();
    server();
    at("/search");
    await screen.findByRole("table", { name: "Results" });

    await user.type(screen.getByLabelText("Words"), "  spring core ");
    await user.type(screen.getByLabelText("Group"), "org.spring*");
    await user.selectOptions(screen.getByLabelText("Repository"), "releases");
    await user.click(within(screen.getByRole("search")).getByRole("button", { name: "Search" }));

    expect(navigation.router.push).toHaveBeenCalledWith(
      "/search?q=spring+core&repository=releases&namespace=org.spring*",
    );
  });

  test("offers the formats and the repositories there are, and no group to search in", async () => {
    server();
    at("/search");
    await screen.findByRole("table", { name: "Results" });

    const choices = (label: string) =>
      within(screen.getByLabelText(label))
        .getAllByRole("option")
        .map((option) => option.textContent);

    await waitFor(() => expect(choices("Format")).toEqual(["Any", "maven", "npm"]));
    expect(choices("Repository")).toEqual(["Any", "releases", "npm-own"]);
  });

  test("reads a checksum by its length", async () => {
    const { calls } = server();
    at(`/search?checksum=${SHA1.toUpperCase()}`);

    await screen.findByRole("table", { name: "Results" });

    expect(asked(calls)).toEqual([{ sha1: SHA1, limit: "50", offset: "0" }]);
  });

  test("says what a checksum is when what was typed is none, and does not search for it", async () => {
    const user = userEvent.setup();
    server();
    at("/search");
    await screen.findByRole("table", { name: "Results" });

    await user.type(screen.getByLabelText("Checksum of a file"), "abc123");
    await user.click(within(screen.getByRole("search")).getByRole("button", { name: "Search" }));

    expect(screen.getByLabelText("Checksum of a file")).toHaveAccessibleDescription(
      expect.stringContaining("A checksum is 32, 40, 64 or 128 hexadecimal digits."),
    );
    expect(screen.getByLabelText("Checksum of a file")).toHaveAttribute("aria-invalid", "true");
    expect(navigation.router.push).not.toHaveBeenCalled();
  });

  test("an address with a checksum that is none asks nothing of the API", async () => {
    const { calls } = server();
    at("/search?checksum=zz");

    expect(await screen.findByRole("alert")).toHaveTextContent("A checksum is 32, 40, 64 or 128");
    expect(asked(calls)).toEqual([]);
  });

  test("says so when nothing is found", async () => {
    server({ "GET /search": { json: { items: [], total: 0 } } });
    at("/search?q=nothing");

    expect(await screen.findByRole("heading", { name: "Nothing found" })).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });

  test("says what the API refused, in its words", async () => {
    server({
      "GET /search": failure(422, "validation_error", "A search term is at most 200 characters."),
    });
    at("/search?q=long");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A search term is at most 200 characters.",
    );
  });

  test("goes through many results a page at a time, keeping what was asked", async () => {
    const { calls } = server({ "GET /search": { json: { items: [APP], total: 120 } } });
    at("/search?q=app&page=2");

    const pages = await screen.findByRole("navigation", { name: "Pages" });

    expect(asked(calls)).toEqual([{ q: "app", limit: "50", offset: "50" }]);
    expect(pages).toHaveTextContent("Page 2 of 3");
    expect(within(pages).getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/search?q=app",
    );
    expect(within(pages).getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/search?q=app&page=3",
    );
  });

  test("takes a page that is no number for the first", async () => {
    const { calls } = server();
    at("/search?q=app&page=-3x");

    await screen.findByRole("table", { name: "Results" });

    expect(asked(calls)[0]?.offset).toBe("0");
  });

  test("shows what a component is called as text, whatever it is called", async () => {
    const odd = '<img src=x onerror="alert(1)">';
    server({
      "GET /search": { json: { items: [{ ...APP, name: odd, namespace: odd }], total: 1 } },
    });
    const { container } = at("/search");

    expect(await screen.findByRole("link", { name: odd })).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("the search box of every screen", () => {
  test("sends what was typed to the results", async () => {
    const user = userEvent.setup();
    renderUi(<SearchBox />);

    await user.type(
      screen.getByRole("searchbox", { name: "Search components" }),
      " left pad {Enter}",
    );

    expect(navigation.router.push).toHaveBeenCalledWith("/search?q=left+pad");
  });

  test("takes the keyboard at a /, from anywhere that is not a place to type", async () => {
    const user = userEvent.setup();
    renderUi(
      <>
        <SearchBox />
        <input aria-label="Elsewhere" />
      </>,
    );
    const box = screen.getByRole("searchbox", { name: "Search components" });

    await user.keyboard("/");
    expect(box).toHaveFocus();
    expect(box).toHaveValue(""); // the key is a shortcut, not a letter of the search

    await user.click(screen.getByLabelText("Elsewhere"));
    await user.keyboard("a/b");
    expect(screen.getByLabelText("Elsewhere")).toHaveFocus();
    expect(screen.getByLabelText("Elsewhere")).toHaveValue("a/b");
  });

  test("leaves the browser's own shortcuts alone", () => {
    renderUi(<SearchBox />);

    fireEvent.keyDown(document.body, { key: "/", ctrlKey: true });

    expect(screen.getByRole("searchbox", { name: "Search components" })).not.toHaveFocus();
  });

  test("says which key it answers to, and is a search landmark", async () => {
    renderUi(<SearchBox />);

    expect(screen.getByRole("search", { name: "Search components" })).toBeVisible();
    expect(screen.getByRole("searchbox")).toHaveAttribute("aria-keyshortcuts", "/");
    await expectAccessible();
  });
});
