import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test } from "vitest";

import { expectAccessible } from "@/test/axe";
import { renderUi } from "@/test/render";

import { MemberList } from "./member-list";

function Group({
  initial,
  candidates = ["releases", "snapshots", "central", "thirdparty"],
  error,
  disabled,
}: {
  initial: string[];
  candidates?: string[];
  error?: string;
  disabled?: boolean;
}) {
  const [members, setMembers] = useState(initial);
  return (
    <MemberList
      legend="Members"
      hint="The first that has it answers."
      members={members}
      onChange={setMembers}
      candidates={candidates}
      error={error}
      disabled={disabled}
    />
  );
}

const order = () => screen.getAllByRole("listitem").map((item) => item.getAttribute("data-member"));
const button = (name: string) => screen.getByRole("button", { name });

describe("the members of a group (R5)", () => {
  test("are listed in the order they are asked, each with its place", async () => {
    renderUi(<Group initial={["releases", "central"]} />);
    const group = screen.getByRole("group", { name: "Members" });

    expect(order()).toEqual(["releases", "central"]);
    expect(group).toHaveAccessibleDescription("The first that has it answers.");
    expect(within(group).getAllByRole("listitem")[0]).toHaveTextContent("1releases");
    // The first cannot go further up, nor the last further down.
    expect(button("Move releases up")).toBeDisabled();
    expect(button("Move central down")).toBeDisabled();
    await expectAccessible();
  });

  test("are moved by buttons, which keep the keyboard and say where the member now is", async () => {
    const user = userEvent.setup();
    renderUi(<Group initial={["releases", "snapshots", "central"]} />);

    await user.click(button("Move central up"));
    expect(order()).toEqual(["releases", "central", "snapshots"]);
    expect(button("Move central up")).toHaveFocus(); // to be pressed again
    expect(screen.getByRole("status")).toHaveTextContent("central is now number 2 of 3.");

    await user.keyboard("{Enter}");
    expect(order()).toEqual(["central", "releases", "snapshots"]);
    // At the top the button can do no more, and a button that is disabled cannot keep
    // the keyboard: it goes to the one beside it.
    expect(button("Move central up")).toBeDisabled();
    expect(button("Move central down")).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("central is now number 1 of 3.");

    await user.click(button("Move releases down"));
    expect(order()).toEqual(["central", "snapshots", "releases"]);
    expect(button("Move releases up")).toHaveFocus();
  });

  test("are taken out one by one, and the keyboard goes to the list to add from", async () => {
    const user = userEvent.setup();
    renderUi(<Group initial={["releases", "central"]} />);

    await user.click(button("Take releases out"));

    expect(order()).toEqual(["central"]);
    expect(screen.getByLabelText("A repository to add")).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("releases was taken out.");
  });

  test("are added from those that are not members yet, at the end", async () => {
    const user = userEvent.setup();
    renderUi(<Group initial={["central"]} />);
    const choices = () =>
      within(screen.getByLabelText("A repository to add"))
        .getAllByRole("option")
        .map((option) => option.textContent);

    expect(choices()).toEqual(["releases", "snapshots", "thirdparty"]);
    await user.selectOptions(screen.getByLabelText("A repository to add"), "snapshots");
    await user.click(button("Add it"));

    expect(order()).toEqual(["central", "snapshots"]);
    expect(choices()).toEqual(["releases", "thirdparty"]);
    expect(screen.getByRole("status")).toHaveTextContent("snapshots was added as number 2.");
    // The list to add from shows the next that can be added, and has the keyboard.
    expect(screen.getByLabelText("A repository to add")).toHaveValue("releases");
    expect(screen.getByLabelText("A repository to add")).toHaveFocus();
  });

  test("say so when there is none, and when there is nothing left to add", async () => {
    const user = userEvent.setup();
    renderUi(<Group initial={[]} candidates={["releases"]} />);
    expect(screen.getByText("It has no member yet, and so answers nothing.")).toBeVisible();

    await user.click(button("Add it"));

    expect(order()).toEqual(["releases"]);
    expect(screen.getByText("There is no other repository of this format to add.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add it" })).toBeNull();
    await expectAccessible();
  });

  test("keep a member that is not among the repositories that could be added", () => {
    // One the caller may not see, or that is beyond what one request brings.
    renderUi(<Group initial={["hidden", "releases"]} candidates={["releases", "central"]} />);

    expect(order()).toEqual(["hidden", "releases"]);
  });

  test("say what the server refused of them, and cannot be changed by whoever may only look", () => {
    const { unmount } = renderUi(
      <Group initial={["releases"]} error="releases is not a maven repository." />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("releases is not a maven repository.");
    unmount();

    renderUi(<Group initial={["releases", "central"]} disabled />);
    expect(button("Move central up")).toBeDisabled();
    expect(button("Take releases out")).toBeDisabled();
    expect(button("Add it")).toBeDisabled();
  });
});
