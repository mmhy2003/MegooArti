import { act, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Route } from "next";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import { expectAccessible } from "@/test/axe";
import { renderUi } from "@/test/render";

import { Breadcrumbs } from "./breadcrumbs";
import { Button } from "./button";
import { ConfirmDialog } from "./confirm-dialog";
import { Fact, Facts, Pager, Progress, Snippet, Time } from "./details";
import { CheckboxField, FilePicker, SelectField } from "./inputs";
import { useNotify } from "./notifications";
import { PageHeader } from "./panel";
import { EmptyState } from "./states";

const file = (name: string, content = "x") => new File([content], name);

describe("the way to where one is", () => {
  test("is a list of links, the last of which is the present place", async () => {
    renderUi(
      <Breadcrumbs
        label="Path"
        crumbs={[
          { name: "releases", href: "/browse/releases" as Route },
          { name: "com", href: "/browse/releases/com" as Route },
          { name: "acme", href: "/browse/releases/com/acme" as Route },
        ]}
      />,
    );

    const links = within(screen.getByRole("navigation", { name: "Path" })).getAllByRole("link");

    expect(links.map((link) => link.textContent)).toEqual(["releases", "com", "acme"]);
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([null, null, "page"]);
    expect(links[1]).toHaveAttribute("href", "/browse/releases/com");
    await expectAccessible();
  });
});

describe("saying that something was done", () => {
  function Doing() {
    const notify = useNotify();
    return <Button onClick={() => notify("Deleted app-1.0.jar.")}>Delete</Button>;
  }

  test("is heard by a screen reader, and goes by itself", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderUi(<Doing />);
    const region = screen.getByRole("region", { name: "Notifications" });

    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toBeEmptyDOMElement(); // there before anything is said, or it is not read

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(region).toHaveTextContent("Deleted app-1.0.jar.");
    await expectAccessible();

    act(() => vi.advanceTimersByTime(7000));
    expect(region).toBeEmptyDOMElement();
    vi.useRealTimers();
  });

  test("can be dismissed, one at a time", async () => {
    const user = userEvent.setup();
    renderUi(<Doing />);

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    const region = screen.getByRole("region", { name: "Notifications" });
    expect(within(region).getAllByText("Deleted app-1.0.jar.")).toHaveLength(2);
    await user.click(within(region).getAllByRole("button", { name: "Dismiss" })[0] as HTMLElement);

    expect(within(region).getAllByText("Deleted app-1.0.jar.")).toHaveLength(1);
  });
});

describe("a choice, a tick and files", () => {
  test("a choice is the browser's own list, with a label", async () => {
    const user = userEvent.setup();
    const chosen = vi.fn();
    renderUi(
      <SelectField
        label="Format"
        defaultValue=""
        onChange={(event) => chosen(event.target.value)}
        choices={[
          { value: "", label: "Any" },
          { value: "maven", label: "maven" },
        ]}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Format"), "maven");

    expect(chosen).toHaveBeenCalledWith("maven");
    await expectAccessible();
  });

  test("a tick has a label and says what it means", async () => {
    const user = userEvent.setup();
    renderUi(<CheckboxField label="Write a POM" hint="A build needs one." defaultChecked />);
    const box = screen.getByRole("checkbox", { name: "Write a POM" });

    expect(box).toBeChecked();
    expect(box).toHaveAccessibleDescription("A build needs one.");
    await user.click(box);
    expect(box).not.toBeChecked();
    await expectAccessible();
  });

  function Picking({ multiple = false }: { multiple?: boolean }) {
    const [files, setFiles] = useState<File[]>([]);
    return (
      <FilePicker
        label="Files"
        hint="Any files."
        multiple={multiple}
        files={files}
        onChange={setFiles}
      />
    );
  }
  const chosen = () =>
    within(screen.getByRole("list", { name: "Chosen for Files" }))
      .getAllByRole("listitem")
      .map((item) => item.textContent);

  test("files are chosen with the browser's own dialog, and listed with their sizes", async () => {
    const user = userEvent.setup();
    renderUi(<Picking multiple />);
    const input = screen.getByLabelText("Files");

    expect(input).toHaveAccessibleDescription("Any files.");
    expect(input).toHaveClass("text-transparent"); // the list below says what is chosen
    await user.upload(input, [file("a.txt", "12345"), file("b.txt")]);
    await user.upload(input, file("c.txt"));

    expect(chosen()).toEqual(["a.txt5 B", "b.txt1 B", "c.txt1 B"]);
    await expectAccessible();
  });

  test("files can be dropped onto it", () => {
    renderUi(<Picking multiple />);
    const zone = screen.getByLabelText("Files").parentElement as HTMLElement;

    fireEvent.drop(zone, { dataTransfer: { files: [file("dropped.bin")] } });

    expect(chosen()).toEqual(["dropped.bin1 B"]);
  });

  test("a file can be taken out again", async () => {
    const user = userEvent.setup();
    renderUi(<Picking multiple />);
    await user.upload(screen.getByLabelText("Files"), [file("a.txt"), file("b.txt")]);

    await user.click(screen.getByRole("button", { name: "Take out a.txt" }));

    expect(chosen()).toEqual(["b.txt1 B"]);
    // The button that was pressed is gone with its file: the keyboard goes to the field.
    expect(screen.getByLabelText("Files")).toHaveFocus();
  });

  test("where one file is wanted, choosing again replaces it", async () => {
    const user = userEvent.setup();
    renderUi(<Picking />);

    await user.upload(screen.getByLabelText("Files"), file("first.tgz"));
    await user.upload(screen.getByLabelText("Files"), file("second.tgz"));

    expect(chosen()).toEqual(["second.tgz1 B"]);
  });

  test("says what is wrong with what was chosen", () => {
    renderUi(
      <FilePicker
        label="Files"
        error="Two files are named a.txt."
        files={[]}
        onChange={() => {}}
      />,
    );

    expect(screen.getByLabelText("Files")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Files")).toHaveAccessibleDescription(
      "Two files are named a.txt.",
    );
  });
});

describe("what is said of one thing", () => {
  test("names and values, and a value that can be copied", async () => {
    const user = userEvent.setup();
    renderUi(
      <Facts>
        <Fact name="Size">2.4 MiB</Fact>
        <Fact name="SHA-1" copy="2ef7bde6" mono>
          2ef7bde6
        </Fact>
      </Facts>,
    );

    expect(screen.getByText("Size").tagName).toBe("DT");
    expect(screen.getByText("2.4 MiB").closest("dd")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Copy SHA-1" }));
    expect(await navigator.clipboard.readText()).toBe("2ef7bde6");
    await expectAccessible();
  });

  test("a time is how long ago to the eye, and exact to a screen reader and on hover", () => {
    const moment = new Date(Date.now() - (3 * 24 + 1) * 3600 * 1000); // three days and an hour
    const { container } = renderUi(<Time value={moment.toISOString()} />);
    const time = container.querySelector("time") as HTMLElement;

    expect(time).toHaveAttribute("datetime", moment.toISOString());
    expect(time.querySelector("[aria-hidden='true']")).toHaveTextContent("3 days ago");
    expect(time.querySelector(".sr-only")?.textContent).toBe(time.getAttribute("title"));
    expect(time.getAttribute("title")).toMatch(/\d{4}/);
  });

  test("a time that is not one is said as it came, and none as never", () => {
    renderUi(
      <>
        <Time value={null} />
        <Time value="not a date" />
      </>,
    );

    expect(screen.getByText("Never")).toBeVisible();
    expect(screen.getByText("not a date")).toBeVisible();
  });

  test("a snippet is text as it stands, with a way to copy all of it", async () => {
    const user = userEvent.setup();
    const text = "<dependency>\n  <groupId>com.acme</groupId>\n</dependency>";
    const { container } = renderUi(<Snippet label="Maven" text={text} />);

    expect(container.querySelector("pre")?.textContent).toBe(text);
    expect(container.querySelector("dependency")).toBeNull(); // text, not markup
    expect(container.querySelector("pre")).toHaveAttribute("tabindex", "0");
    await user.click(screen.getByRole("button", { name: "Copy Maven" }));
    expect(await navigator.clipboard.readText()).toBe(text);
    await expectAccessible();
  });

  test("pages say where one is, and lead on and back", async () => {
    const hrefFor = (page: number) => `/search?page=${page}` as Route;
    const { unmount } = renderUi(<Pager page={2} pages={7} hrefFor={hrefFor} />);
    const pages = screen.getByRole("navigation", { name: "Pages" });

    expect(pages).toHaveTextContent("Page 2 of 7");
    expect(within(pages).getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/search?page=1",
    );
    expect(within(pages).getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/search?page=3",
    );
    await expectAccessible();

    unmount();
    renderUi(<Pager page={1} pages={1} hrefFor={hrefFor} />);
    expect(screen.queryByRole("navigation", { name: "Pages" })).toBeNull(); // one page needs none
  });

  test("the first and the last page have nowhere further to go", () => {
    const hrefFor = (page: number) => `/search?page=${page}` as Route;
    const { unmount } = renderUi(<Pager page={1} pages={3} hrefFor={hrefFor} />);
    expect(screen.queryByRole("link", { name: "Previous" })).toBeNull();
    expect(screen.getByRole("link", { name: "Next" })).toBeVisible();
    unmount();

    renderUi(<Pager page={3} pages={3} hrefFor={hrefFor} />);
    expect(screen.queryByRole("link", { name: "Next" })).toBeNull();
  });

  test("progress is a bar with a name, and a number", async () => {
    renderUi(<Progress label="1.0 MiB of 4.0 MiB sent" value={1} max={4} />);

    const bar = screen.getByRole("progressbar", { name: "1.0 MiB of 4.0 MiB sent" });
    expect(bar).toHaveAttribute("value", "1");
    expect(bar).toHaveAttribute("max", "4");
    expect(screen.getByText("25%")).toBeVisible();
    await expectAccessible();
  });
});

describe("asking for a name before something large is destroyed", () => {
  function Deleting({ onConfirm }: { onConfirm: () => void }) {
    const [open, setOpen] = useState(true);
    return (
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Delete the folder logs?"
        confirmLabel="Delete folder"
        mustType="logs"
        onConfirm={onConfirm}
      >
        Every file under it goes.
      </ConfirmDialog>
    );
  }

  test("the button that does it cannot be pressed until the name is typed, exactly", async () => {
    const user = userEvent.setup();
    const confirmed = vi.fn();
    renderUi(<Deleting onConfirm={confirmed} />);
    const dialog = screen.getByRole("alertdialog");
    const button = within(dialog).getByRole("button", { name: "Delete folder" });
    const field = within(dialog).getByLabelText("Type logs to go on");

    expect(button).toBeDisabled();
    await user.type(field, "Logs");
    expect(button).toBeDisabled();
    await user.click(button);
    expect(confirmed).not.toHaveBeenCalled();

    await user.clear(field);
    await user.type(field, "logs");
    expect(button).toBeEnabled();
    await user.click(button);

    expect(confirmed).toHaveBeenCalledOnce();
    await expectAccessible();
  });

  test("the name is typed again each time, whoever closed the dialog", async () => {
    const user = userEvent.setup();
    // A screen that closes the dialog itself once the action is done, as a folder's does.
    function Twice() {
      const [open, setOpen] = useState(true);
      return (
        <>
          <Button onClick={() => setOpen(true)}>Delete folder again</Button>
          <ConfirmDialog
            open={open}
            onOpenChange={setOpen}
            title="Delete the folder logs?"
            confirmLabel="Delete folder"
            mustType="logs"
            onConfirm={() => setOpen(false)}
          >
            Every file under it goes.
          </ConfirmDialog>
        </>
      );
    }
    renderUi(<Twice />);
    await user.type(screen.getByLabelText("Type logs to go on"), "logs");
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete folder" }),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Delete folder again" }));
    const dialog = screen.getByRole("alertdialog");

    expect(within(dialog).getByLabelText("Type logs to go on")).toHaveValue("");
    expect(within(dialog).getByRole("button", { name: "Delete folder" })).toBeDisabled();
  });

  test("the name is shown as it is to be typed, not in capitals", () => {
    renderUi(<Deleting onConfirm={() => {}} />);
    const dialog = screen.getByRole("alertdialog");

    expect(within(dialog).getByText("Type logs to go on")).not.toHaveClass("label-caps");
    expect(
      within(dialog).getByRole("heading", { name: "Delete the folder logs?" }),
    ).not.toHaveClass("uppercase");
  });
});

describe("the heading of a screen", () => {
  test("is the title of an empty state when that is all the page has", () => {
    const { unmount } = renderUi(<EmptyState title="Nothing here yet" />);
    expect(screen.getByRole("heading", { level: 2, name: "Nothing here yet" })).toBeVisible();
    unmount();

    renderUi(<EmptyState page title="There is nothing at this address" />);
    expect(
      screen.getByRole("heading", { level: 1, name: "There is nothing at this address" }),
    ).toBeVisible();
  });

  test("is in capitals when it is the screen's own word, and as written when it is a name", () => {
    const { unmount } = renderUi(<PageHeader title="Search" intro="Components." />);
    expect(screen.getByRole("heading", { level: 1, name: "Search" })).toHaveClass("uppercase");
    expect(screen.getByText("Components.")).toBeVisible();
    unmount();

    renderUi(<PageHeader named title="Releases-EU" />);
    expect(screen.getByRole("heading", { level: 1, name: "Releases-EU" })).not.toHaveClass(
      "uppercase",
    );
  });
});
