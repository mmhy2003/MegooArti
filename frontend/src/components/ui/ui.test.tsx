import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { expectAccessible } from "@/test/axe";
import { renderUi } from "@/test/render";

import { Alert, StatusTag } from "./alert";
import { Button } from "./button";
import { ConfirmDialog } from "./confirm-dialog";
import { CopyButton } from "./copy-button";
import { TextField } from "./field";
import { Menu, MenuContent, MenuItem, MenuRadioGroup, MenuRadioItem, MenuTrigger } from "./menu";
import { PageHeader, Panel } from "./panel";
import { EmptyState, ErrorState, LoadingState } from "./states";
import { Table, Td, Th } from "./table";

describe("a button", () => {
  test("is pressed with the mouse and with the keyboard", async () => {
    const user = userEvent.setup();
    const pressed = vi.fn();
    renderUi(<Button onClick={pressed}>Save</Button>);

    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.keyboard("{Enter}");
    await user.keyboard(" ");

    expect(pressed).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  test("cannot be pressed again while what it started is under way, and says so", async () => {
    const user = userEvent.setup();
    const pressed = vi.fn();
    renderUi(
      <Button busy onClick={pressed}>
        Save
      </Button>,
    );

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(pressed).not.toHaveBeenCalled();
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button")).toHaveAttribute("aria-disabled", "true");
    // It keeps the keyboard: a button disabled outright drops focus to the page.
    expect(screen.getByRole("button")).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(pressed).not.toHaveBeenCalled();
  });

  test("can be a link that looks like one", async () => {
    renderUi(
      <Button asChild variant="primary">
        <a href="/login">Sign in</a>
      </Button>,
    );

    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button")).toBeNull();
    await expectAccessible();
  });
});

describe("a field", () => {
  test("has a label, and its hint is read with it", async () => {
    renderUi(<TextField label="New password" hint="At least 8 characters." type="password" />);

    const input = screen.getByLabelText("New password");

    expect(input).toHaveAccessibleDescription("At least 8 characters.");
    expect(input).not.toHaveAttribute("aria-invalid");
    await expectAccessible();
  });

  test("says what is wrong in place of the hint, with an icon beside the words", async () => {
    renderUi(<TextField label="New password" hint="At least 8 characters." error="Too short." />);

    const input = screen.getByLabelText("New password");

    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Too short.");
    expect(screen.queryByText("At least 8 characters.")).toBeNull();
    expect(screen.getByText("Too short.").parentElement?.querySelector("svg")).not.toBeNull();
    await expectAccessible();
  });

  test("two fields with the same label are still two fields", () => {
    renderUi(
      <>
        <TextField label="Password" />
        <TextField label="Password" />
      </>,
    );

    const [first, second] = screen.getAllByLabelText("Password");

    expect(first?.id).not.toBe(second?.id);
  });
});

describe("what a person is told", () => {
  test("a failure interrupts, and anything else waits its turn", async () => {
    renderUi(
      <>
        <Alert tone="danger" title="Not saved">
          The name is taken.
        </Alert>
        <Alert tone="success">Saved.</Alert>
      </>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Not saved");
    expect(screen.getByRole("alert")).toHaveTextContent("The name is taken.");
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
    await expectAccessible();
  });

  test.each(["info", "success", "warning", "danger"] as const)(
    "a %s is never colour alone: it has an icon and words (UI-15)",
    (tone) => {
      const { container } = renderUi(
        <>
          <Alert tone={tone}>Words</Alert>
          <StatusTag tone={tone}>State</StatusTag>
        </>,
      );

      expect(container.querySelectorAll("svg[aria-hidden='true']")).toHaveLength(2);
      expect(screen.getByText("Words")).toBeVisible();
      expect(screen.getByText("State")).toBeVisible();
    },
  );
});

describe("the states of a screen (UI-5)", () => {
  test("loading says so", async () => {
    renderUi(<LoadingState />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    await expectAccessible();
  });

  test("nothing to show says so, and what could be done", async () => {
    renderUi(
      <EmptyState title="No repositories" action={<Button>Create one</Button>}>
        An administrator creates them.
      </EmptyState>,
    );

    expect(screen.getByRole("heading", { name: "No repositories" })).toBeVisible();
    expect(screen.getByText("An administrator creates them.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Create one" })).toBeVisible();
    await expectAccessible();
  });

  test("a failure says what went wrong, its code and which request it was", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    const error = new ApiError(409, "redeploy_disabled", "This cannot be replaced.", [], "req-7");
    renderUi(<ErrorState error={error} onRetry={retry} />);

    const alert = screen.getByRole("alert");
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(alert).toHaveTextContent("This cannot be replaced.");
    expect(alert).toHaveTextContent("Code redeploy_disabled");
    expect(alert).toHaveTextContent("Request req-7");
    expect(retry).toHaveBeenCalledOnce();
    await expectAccessible();
  });

  test.each([
    [new ApiError(0, "network_error", ""), "The server could not be reached."],
    [new ApiError(502, "unexpected_answer", ""), "does not understand"],
    [new ApiError(403, "forbidden", "You do not have permission to do this."), "permission"],
    [new ApiError(418, "teapot", ""), "Something went wrong."],
    [new TypeError("x is not a function"), "Something went wrong."],
  ])("a failure the UI has words for uses them: %s", (error, words) => {
    renderUi(<ErrorState error={error} />);

    expect(screen.getByRole("alert")).toHaveTextContent(words);
    expect(screen.getByRole("alert")).not.toHaveTextContent("x is not a function");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("asking before something is destroyed (UI-5)", () => {
  function Deleting({ onConfirm }: { onConfirm: () => void }) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Delete</Button>
        <ConfirmDialog
          open={open}
          onOpenChange={setOpen}
          title="Delete app-1.0.jar?"
          confirmLabel="Delete it"
          onConfirm={onConfirm}
        >
          It cannot be brought back.
        </ConfirmDialog>
      </>
    );
  }

  test("focus starts on Cancel, so that Enter by habit destroys nothing", async () => {
    const user = userEvent.setup();
    const confirmed = vi.fn();
    renderUi(<Deleting onConfirm={confirmed} />);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete app-1.0.jar?" });

    expect(dialog).toHaveAccessibleDescription("It cannot be brought back.");
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus(),
    );
    await expectAccessible();

    await user.keyboard("{Enter}");

    expect(confirmed).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    // Focus goes back to what opened it, so the keyboard is where it was.
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus());
  });

  test("Escape closes it, and only the button that says so destroys", async () => {
    const user = userEvent.setup();
    const confirmed = vi.fn();
    renderUi(<Deleting onConfirm={confirmed} />);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(confirmed).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.keyboard("{Tab}{Enter}");

    expect(confirmed).toHaveBeenCalledOnce();
    // It stays until whoever asked closes it: the deletion may still be under way.
    expect(screen.getByRole("alertdialog")).toBeVisible();
  });
});

describe("a menu", () => {
  function Example({ onChoose }: { onChoose: (what: string) => void }) {
    const [mode, setMode] = useState("dark");
    return (
      <Menu>
        <MenuTrigger>Options</MenuTrigger>
        <MenuContent>
          <MenuItem onSelect={() => onChoose("rename")}>Rename</MenuItem>
          <MenuItem onSelect={() => onChoose("delete")}>Delete</MenuItem>
          <MenuRadioGroup value={mode} onValueChange={setMode}>
            <MenuRadioItem value="light">Light</MenuRadioItem>
            <MenuRadioItem value="dark">Dark</MenuRadioItem>
          </MenuRadioGroup>
        </MenuContent>
      </Menu>
    );
  }

  test("is opened and used with the keyboard alone, and gives focus back (UI-6)", async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    renderUi(<Example onChoose={chosen} />);

    await user.tab();
    expect(screen.getByRole("button", { name: "Options" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("menu")).toBeVisible();
    await user.keyboard("{ArrowDown}{Enter}");

    expect(chosen).toHaveBeenCalledWith("delete");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: "Options" })).toHaveFocus();
  });

  test("says which of its choices is in force", async () => {
    const user = userEvent.setup();
    renderUi(<Example onChoose={() => {}} />);

    await user.click(screen.getByRole("button", { name: "Options" }));
    expect(screen.getByRole("menuitemradio", { name: "Dark" })).toBeChecked();
    await user.click(screen.getByRole("menuitemradio", { name: "Light" }));
    await user.click(screen.getByRole("button", { name: "Options" }));

    expect(screen.getByRole("menuitemradio", { name: "Light" })).toBeChecked();
    expect(screen.getByRole("menuitemradio", { name: "Dark" })).not.toBeChecked();
  });

  test("closes on Escape", async () => {
    const user = userEvent.setup();
    renderUi(<Example onChoose={() => {}} />);

    await user.click(screen.getByRole("button", { name: "Options" }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("copying", () => {
  test("puts the text on the clipboard and says that it did", async () => {
    const user = userEvent.setup();
    renderUi(
      <CopyButton text="https://repo.example.com/repository/releases/" what="the address" />,
    );

    await user.click(screen.getByRole("button", { name: "Copy the address" }));

    expect(await navigator.clipboard.readText()).toBe(
      "https://repo.example.com/repository/releases/",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
    await expectAccessible();
  });

  test("says so when it could not", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    renderUi(<CopyButton text="x" what="the address" />);

    await user.click(screen.getByRole("button", { name: "Copy the address" }));

    expect(screen.getByRole("status")).toHaveTextContent("Could not copy");
  });
});

describe("a table and a page", () => {
  test("a table has a name and headers a screen reader can use", async () => {
    renderUi(
      <Panel>
        <PageHeader title="Repositories" intro="What you can browse." />
        <Table caption="Repositories">
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Format</Th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <Td>releases</Td>
              <Td>maven</Td>
            </tr>
          </tbody>
        </Table>
      </Panel>,
    );

    expect(screen.getByRole("table", { name: "Repositories" })).toBeVisible();
    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
    expect(screen.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
    await expectAccessible();
  });
});
