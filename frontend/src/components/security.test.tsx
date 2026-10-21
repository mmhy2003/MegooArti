import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import type { TokenInfo } from "@/lib/api/types";
import { ALPHABET } from "@/lib/passwords";
import { failure, mockApi } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi, VISITOR } from "@/test/render";

import { AccountNav } from "./account-nav";
import { NewPasswordField } from "./new-password-field";
import { PermissionList, PermissionRows, patternsAreValid } from "./permission-rows";
import { TokenList } from "./token-list";
import { CheckList, ChoiceGroup } from "./ui/inputs";

const REPOSITORIES = [
  { name: "releases", format: "maven" },
  { name: "snapshots", format: "maven" },
  { name: "npm-own", format: "npm" },
];

/** The rows, and the patterns they were last said to stand for. */
function Rows({ initial, checked = false }: { initial: string[]; checked?: boolean }) {
  const [patterns, setPatterns] = useState(initial);
  return (
    <>
      <PermissionRows
        legend="Permissions"
        initial={initial}
        onChange={setPatterns}
        repositories={REPOSITORIES}
        selectors={["acme", "jars"]}
        checked={checked}
      />
      <output aria-label="Patterns">{JSON.stringify(patterns)}</output>
    </>
  );
}
const patterns = () => JSON.parse(screen.getByLabelText("Patterns").textContent ?? "[]");
const row = (number: number) => screen.getByRole("group", { name: `Permission ${number}` });
const options = (select: HTMLElement) =>
  within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);

describe("permissions as rows (A2)", () => {
  test("each pattern is a row, taken apart, with what it grants in words", async () => {
    renderUi(<Rows initial={["repository:maven:releases:read", "admin:users:write", "*"]} />);

    expect(within(row(1)).getByLabelText("About")).toHaveValue("repository");
    expect(within(row(1)).getByLabelText("Format")).toHaveValue("maven");
    expect(within(row(1)).getByLabelText("Repository")).toHaveValue("releases");
    expect(within(row(1)).getByLabelText("Action")).toHaveValue("read");
    expect(row(1)).toHaveTextContent("repository:maven:releases:read");
    expect(row(1)).toHaveTextContent("Read in the maven repository releases.");

    expect(within(row(2)).getByLabelText("Area")).toHaveValue("users");
    expect(row(2)).toHaveTextContent("Change the users.");
    expect(within(row(3)).getByLabelText("About")).toHaveValue("all");
    expect(row(3)).toHaveTextContent(
      "Everything: every repository, and all of the administration.",
    );
    await expectAccessible();
  });

  test("choosing from the lists makes the pattern", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["repository:*:*:read"]} />);

    await user.selectOptions(within(row(1)).getByLabelText("Format"), "maven");
    expect(options(within(row(1)).getByLabelText("Repository"))).toEqual([
      "Any",
      "releases",
      "snapshots",
    ]);
    await user.selectOptions(within(row(1)).getByLabelText("Repository"), "snapshots");
    await user.selectOptions(within(row(1)).getByLabelText("Action"), "delete");

    expect(patterns()).toEqual(["repository:maven:snapshots:delete"]);
    expect(row(1)).toHaveTextContent("Delete in the maven repository snapshots.");

    // Changing the format does not widen what the row grants to every repository of
    // the new one: the name stays, to be chosen again, and grants nothing meanwhile.
    await user.selectOptions(within(row(1)).getByLabelText("Format"), "npm");
    expect(patterns()).toEqual(["repository:npm:snapshots:delete"]);
    expect(row(1)).toHaveTextContent("Delete in the npm repository snapshots.");
    expect(options(within(row(1)).getByLabelText("Repository"))).toEqual([
      "Any",
      "snapshots",
      "npm-own",
    ]);
  });

  test("a selector's row gives an action where a content selector matches (spec 10)", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["selector:gone:npm:*:edit"]} />);

    expect(within(row(1)).getByLabelText("About")).toHaveValue("selector");
    // A selector a row holds is one of its choices, though it is not among those there are.
    expect(options(within(row(1)).getByLabelText("Content selector"))).toEqual([
      "Any",
      "gone",
      "acme",
      "jars",
    ]);
    expect(row(1)).toHaveTextContent(
      "Edit in every npm repository, where the content selector gone matches.",
    );

    await user.selectOptions(within(row(1)).getByLabelText("About"), "repository");
    await user.selectOptions(within(row(1)).getByLabelText("About"), "selector");
    expect(patterns()).toEqual(["selector:*:*:*:read"]);
    expect(row(1)).toHaveTextContent(
      "Read in every repository, where any content selector matches.",
    );

    await user.selectOptions(within(row(1)).getByLabelText("Content selector"), "acme");
    await user.selectOptions(within(row(1)).getByLabelText("Format"), "maven");
    await user.selectOptions(within(row(1)).getByLabelText("Repository"), "releases");
    await user.selectOptions(within(row(1)).getByLabelText("Action"), "add");

    expect(patterns()).toEqual(["selector:acme:maven:releases:add"]);
    expect(row(1)).toHaveTextContent(
      "Add in the maven repository releases, where the content selector acme matches.",
    );
    await expectAccessible();
  });

  test("offers every format, whether or not a repository of it exists", () => {
    renderUi(<Rows initial={["repository:*:*:read"]} />);

    expect(options(within(row(1)).getByLabelText("Format"))).toEqual([
      "Any",
      "apk",
      "apt",
      "docker",
      "maven",
      "npm",
      "nuget",
      "pypi",
      "raw",
      "yum",
    ]);
  });

  test("changing what a row is about starts it afresh", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["repository:maven:releases:delete"]} />);

    await user.selectOptions(within(row(1)).getByLabelText("About"), "admin");
    expect(patterns()).toEqual(["admin:*:read"]);
    expect(row(1)).toHaveTextContent("See everything an administrator keeps.");

    await user.selectOptions(within(row(1)).getByLabelText("Area"), "blobstores");
    await user.selectOptions(within(row(1)).getByLabelText("Action"), "*");
    expect(patterns()).toEqual(["admin:blobstores:*"]);
    expect(row(1)).toHaveTextContent("See and change the blob stores.");

    await user.selectOptions(within(row(1)).getByLabelText("About"), "all");
    expect(patterns()).toEqual(["*"]);
  });

  test("what the lists cannot say is typed, and stays as it was typed (A3)", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["repository:maven", "admin:jobs:read"]} />);

    expect(within(row(1)).getByLabelText("About")).toHaveValue("typed");
    expect(within(row(1)).getByLabelText("Pattern")).toHaveValue("repository:maven");
    expect(row(1)).toHaveTextContent("Whatever this pattern matches.");
    expect(patterns()).toEqual(["repository:maven", "admin:jobs:read"]);

    // Typing a pattern that a row could say does not turn the field into lists under
    // the hands that are typing it.
    const typed = within(row(2)).getByLabelText("Pattern");
    await user.clear(typed);
    await user.type(typed, "repository:npm:*:read");
    expect(within(row(2)).getByLabelText("Pattern")).toHaveFocus();
    expect(patterns()[1]).toBe("repository:npm:*:read");
  });

  test("a repository or a format that is not among the choices is still what the row holds", () => {
    renderUi(<Rows initial={["repository:helm:gone-repo:read"]} />);

    expect(within(row(1)).getByLabelText("Format")).toHaveValue("helm");
    expect(within(row(1)).getByLabelText("Repository")).toHaveValue("gone-repo");
    expect(patterns()).toEqual(["repository:helm:gone-repo:read"]);
  });

  test("what is typed and is no pattern is said to be wrong, where it is", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={[]} />);
    expect(screen.getByText("No permission yet.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Add a permission" }));
    await user.selectOptions(within(row(1)).getByLabelText("About"), "typed");
    await user.type(within(row(1)).getByLabelText("Pattern"), "admin::read");

    const field = within(row(1)).getByLabelText("Pattern");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(expect.stringContaining("words joined by a colon"));
    expect(patternsAreValid(patterns())).toBe(false);
    await expectAccessible();
  });

  test("a row left empty is wrong only once saving was tried", () => {
    const { unmount } = renderUi(<Rows initial={[""]} />);
    expect(within(row(1)).getByLabelText("Pattern")).not.toHaveAttribute("aria-invalid");
    expect(patternsAreValid([""])).toBe(false);
    unmount();

    renderUi(<Rows initial={[""]} checked />);
    expect(within(row(1)).getByLabelText("Pattern")).toHaveAttribute("aria-invalid", "true");
  });

  test("a row that is added has the keyboard, and one that is removed leaves it at the button that adds", async () => {
    const user = userEvent.setup();
    renderUi(<Rows initial={["*"]} />);

    await user.click(screen.getByRole("button", { name: "Add a permission" }));
    expect(patterns()).toEqual(["*", "repository:*:*:read"]);
    expect(within(row(2)).getByLabelText("About")).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Remove permission 1" }));
    expect(patterns()).toEqual(["repository:*:*:read"]);
    expect(screen.getByRole("button", { name: "Add a permission" })).toHaveFocus();
    expect(screen.queryByRole("group", { name: "Permission 2" })).toBeNull();
  });

  test("as a list, for whoever may only read them", async () => {
    const { unmount } = renderUi(
      <PermissionList patterns={["repository:*:*:browse", "<img src=x>"]} empty="None." />,
    );

    expect(screen.getByText("Browse in every repository.")).toBeVisible();
    expect(screen.getByText("<img src=x>")).toBeVisible(); // as text, whatever it is
    expect(screen.queryByRole("img")).toBeNull();
    await expectAccessible();
    unmount();

    renderUi(<PermissionList patterns={[]} empty="None." />);
    expect(screen.getByText("None.")).toBeVisible();
  });
});

describe("a password set for someone else (A6)", () => {
  function Field() {
    const [value, setValue] = useState("");
    return (
      <NewPasswordField label="Password" hint="At least 8." value={value} onChange={setValue} />
    );
  }

  test("is hidden as it is typed, and shown when asked", async () => {
    const user = userEvent.setup();
    renderUi(<Field />);
    const field = screen.getByLabelText("Password");

    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "new-password");
    await user.type(field, "typed-by-hand");
    await user.click(screen.getByRole("button", { name: "Show it" }));

    expect(field).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Show it" })).toHaveAttribute("aria-pressed", "true");
    await expectAccessible();
  });

  test("can be generated: then it is shown, and can be copied to pass on", async () => {
    const user = userEvent.setup();
    renderUi(<Field />);
    expect(screen.queryByRole("button", { name: "Copy Password" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Generate one" }));
    const made = (screen.getByLabelText("Password") as HTMLInputElement).value;

    expect(made).toHaveLength(20);
    expect(Array.from(made).every((character) => ALPHABET.includes(character))).toBe(true);
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Copy Password" }));
    expect(await navigator.clipboard.readText()).toBe(made);
  });
});

describe("one of a few, and any of a list", () => {
  test("one of a few is the browser's own radio buttons, each with what it means", async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    renderUi(
      <ChoiceGroup
        legend="State"
        value="active"
        onChange={chosen}
        options={[
          { value: "active", label: "Active", hint: "Can sign in." },
          { value: "disabled", label: "Disabled" },
        ]}
      />,
    );
    const group = screen.getByRole("group", { name: "State" });

    expect(within(group).getByRole("radio", { name: "Active" })).toBeChecked();
    expect(within(group).getByRole("radio", { name: "Active" })).toHaveAccessibleDescription(
      "Can sign in.",
    );
    await user.click(within(group).getByRole("radio", { name: "Disabled" }));
    expect(chosen).toHaveBeenCalledWith("disabled");
    await expectAccessible();
  });

  test("a press on the choice that is shown is a choice too", async () => {
    // A browser says nothing when the radio that is checked is pressed. Where what is
    // shown is only a default, pressing it is how a person says "this one".
    const user = userEvent.setup();
    const chosen = vi.fn();
    renderUi(
      <ChoiceGroup
        legend="State"
        value="active"
        onChange={chosen}
        options={[
          { value: "active", label: "Active" },
          { value: "disabled", label: "Disabled" },
        ]}
      />,
    );

    await user.click(screen.getByRole("radio", { name: "Active" }));
    expect(chosen).toHaveBeenCalledWith("active");
    chosen.mockClear();
    await user.click(screen.getByText("Active")); // its label
    expect(chosen).toHaveBeenCalledWith("active");
    chosen.mockClear();
    screen.getByRole("radio", { name: "Active" }).focus();
    await user.keyboard(" ");
    expect(chosen).toHaveBeenCalledWith("active");
  });

  test("any of a list is ticks, and says so when there is nothing to tick", async () => {
    const user = userEvent.setup();
    function Roles() {
      const [held, setHeld] = useState(["admin"]);
      return (
        <CheckList
          legend="Roles"
          value={held}
          onChange={setHeld}
          options={[
            { value: "admin", label: "admin" },
            { value: "deployers", label: "deployers", hint: "May deploy." },
          ]}
        />
      );
    }
    const { unmount } = renderUi(<Roles />);
    const group = screen.getByRole("group", { name: "Roles" });

    await user.click(within(group).getByRole("checkbox", { name: "deployers" }));
    await user.click(within(group).getByRole("checkbox", { name: "admin" }));

    expect(within(group).getByRole("checkbox", { name: "deployers" })).toBeChecked();
    expect(within(group).getByRole("checkbox", { name: "admin" })).not.toBeChecked();
    await expectAccessible();
    unmount();

    renderUi(
      <CheckList legend="Roles" value={[]} onChange={() => {}} options={[]} empty="No role." />,
    );
    expect(screen.getByText("No role.")).toBeVisible();
  });
});

describe("a list of API tokens", () => {
  const token = (name: string, more: Partial<TokenInfo> = {}): TokenInfo => ({
    id: `id-of-${name}`,
    name,
    display_prefix: "mga_Uw7S",
    scopes: null,
    expires_at: null,
    created_at: "2026-10-01T08:00:00Z",
    last_used_at: null,
    ...more,
  });
  const TOKENS = [
    token("ci build", { scopes: ["repository:maven:releases:read"] }),
    token("old", { expires_at: "2020-01-01T00:00:00Z" }),
    token("laptop", { expires_at: "2099-01-01T00:00:00Z" }),
  ];

  test("says of each how it begins, what it may do and when it ends, and never its secret", async () => {
    renderUi(<TokenList caption="Your tokens" tokens={TOKENS} empty="None." onRevoke={vi.fn()} />);
    const rows = within(screen.getByRole("table", { name: "Your tokens" })).getAllByRole("row");

    expect(rows[1]).toHaveTextContent("ci build");
    expect(rows[1]).toHaveTextContent("mga_Uw7S…");
    expect(rows[1]).toHaveTextContent("repository:maven:releases:read");
    expect(rows[1]).toHaveTextContent("Never");
    expect(rows[2]).toHaveTextContent("Everything its owner may");
    expect(rows[2]).toHaveTextContent("Expired");
    expect(rows[3]).not.toHaveTextContent("Expired");
    await expectAccessible();
  });

  test("revokes after asking, and leaves the keyboard at the list", async () => {
    const user = userEvent.setup();
    const revoke = vi.fn().mockResolvedValue(undefined);
    // As a screen has it: once a token is revoked it is no longer among those listed.
    function Listed() {
      const [tokens, setTokens] = useState(TOKENS);
      return (
        <TokenList
          caption="Your tokens"
          tokens={tokens}
          empty="None."
          onRevoke={async (token) => {
            await revoke(token);
            setTokens((held) => held.filter((one) => one.id !== token.id));
          }}
        />
      );
    }
    renderUi(<Listed />);

    await user.click(screen.getByRole("button", { name: "Revoke ci build" }));
    const dialog = screen.getByRole("alertdialog", { name: "Revoke the token ci build?" });
    expect(revoke).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Revoke" }));

    expect(revoke).toHaveBeenCalledWith(TOKENS[0]);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.queryByRole("button", { name: "Revoke ci build" })).toBeNull();
    // The button that was pressed went with its row.
    await waitFor(() => expect(screen.getByRole("group", { name: "Your tokens" })).toHaveFocus());
  });

  test("says why when a token could not be revoked", async () => {
    const user = userEvent.setup();
    mockApi({ "DELETE /me/tokens/x": failure(404, "not_found", "No such token.") });
    const revoke = vi.fn(async () => {
      await fetch("/api/v1/me/tokens/x", { method: "DELETE" });
      throw new Error("refused");
    });
    renderUi(<TokenList caption="Your tokens" tokens={TOKENS} empty="None." onRevoke={revoke} />);

    await user.click(screen.getByRole("button", { name: "Revoke old" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  test("offers no revoking to whoever may only look, and says so when there is none", () => {
    const { unmount } = renderUi(
      <TokenList caption="Tokens of alice" tokens={TOKENS} empty="None." />,
    );
    expect(screen.queryByRole("button", { name: /Revoke/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Revoke" })).toBeNull();
    unmount();

    renderUi(<TokenList caption="Tokens of alice" tokens={[]} empty="This user has no token." />);
    expect(screen.getByText("This user has no token.")).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("the pages of an account (A1)", () => {
  test("are links to each other, with the present one marked", async () => {
    navigation.at("/account/tokens");
    renderUi(<AccountNav />, { session: ADMIN });
    const links = within(screen.getByRole("navigation", { name: "Account" })).getAllByRole("link");

    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["API tokens", "/account/tokens"],
      ["Connected apps", "/account/connected-apps"],
      ["Password", "/account/password"],
      ["Preferences", "/account/preferences"],
    ]);
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([
      "page",
      null,
      null,
      null,
    ]);
    await expectAccessible();
  });

  test("are not listed for a visitor, who has no account", () => {
    navigation.at("/account/preferences");
    renderUi(<AccountNav />, { session: VISITOR });

    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
