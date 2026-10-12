import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { mockApi } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";
import { mockUploads } from "@/test/xhr";

import { UploadChooserScreen, UploadScreen } from "./upload";

const repository = (name: string, format: string, type = "hosted") => ({
  name,
  format,
  type,
  online: true,
  url: `https://repo.example.com/repository/${name}/`,
  members: null,
});
const file = (name: string, content = "x") => new File([content], name);

/** The upload screen of one repository, and the uploads it starts. */
function at(format: string, address: string, session: SessionInfo = ADMIN, type = "hosted") {
  const name = address.split("?")[0]?.split("/").pop() ?? "";
  mockApi({
    [`GET /content/${name}`]: { json: repository(name, format, type) },
    [`GET /content/${name}/tree`]: { json: { items: [], next: null } },
  });
  const uploads = mockUploads();
  navigation.at(address);
  return { ...renderUi(<UploadScreen />, { session }), uploads };
}

const send = () => screen.getByRole("button", { name: "Upload" });

describe("uploading to a raw repository", () => {
  test("sends the files to the directory the address names, and says what was stored", async () => {
    const user = userEvent.setup();
    const { uploads } = at("raw", "/upload/files?directory=docs%2Fv1");

    expect(await screen.findByRole("heading", { level: 1, name: "Upload to files" })).toBeVisible();
    expect(screen.getByLabelText("Directory")).toHaveValue("docs/v1");
    expect(send()).toBeDisabled(); // there is nothing to send yet
    await user.upload(screen.getByLabelText("Files"), [file("a.txt"), file("b.txt")]);
    await user.click(send());

    expect(uploads).toHaveLength(1);
    expect([uploads[0]?.method, uploads[0]?.url]).toEqual(["POST", "/api/v1/content/files/upload"]);
    expect(uploads[0]?.parts).toEqual([
      ["file", "file:a.txt"],
      ["file", "file:b.txt"],
      ["directory", "docs/v1"],
    ]);

    act(() =>
      uploads[0]?.answer(201, {
        files: [{ path: "docs/v1/a.txt" }, { path: "docs/v1/b.txt" }],
        components: [],
      }),
    );

    expect(await screen.findByText("2 files stored")).toBeVisible();
    expect(screen.getByRole("link", { name: "docs/v1/a.txt" })).toHaveAttribute(
      "href",
      "/browse/files/docs/v1?file=a.txt",
    );
    expect(screen.queryByRole("list", { name: "Chosen for Files" })).toBeNull(); // ready for more
    expect(send()).toBeDisabled();
    await expectAccessible();
  });

  test("shows how much has gone, and cannot be sent twice", async () => {
    const user = userEvent.setup();
    const { uploads } = at("raw", "/upload/files");
    await user.upload(await screen.findByLabelText("Files"), file("big.bin", "x".repeat(2048)));
    await user.click(send());

    act(() => uploads[0]?.progress(512, 2048));

    const bar = screen.getByRole("progressbar", { name: "512 B of 2.0 KiB sent" });
    expect(bar).toHaveAttribute("value", "512");
    expect(screen.getByText("25%")).toBeVisible();
    await user.click(send());
    expect(uploads).toHaveLength(1);
  });

  test("can be stopped, which is not a failure", async () => {
    const user = userEvent.setup();
    const { uploads } = at("raw", "/upload/files");
    await user.upload(await screen.findByLabelText("Files"), file("big.bin"));
    await user.click(send());

    await user.click(screen.getByRole("button", { name: "Stop" }));

    expect(uploads[0]?.aborted).toBe(true);
    await waitFor(() => expect(screen.queryByRole("progressbar")).toBeNull());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("list", { name: "Chosen for Files" })).toBeVisible(); // still chosen
    expect(send()).toBeEnabled();
  });

  test("puts a refusal at the field it is about", async () => {
    const user = userEvent.setup();
    const { uploads } = at("raw", "/upload/files");
    await user.type(await screen.findByLabelText("Directory"), "../up");
    await user.upload(screen.getByLabelText("Files"), file("a.txt"));
    await user.click(send());

    act(() =>
      uploads[0]?.answer(
        422,
        {
          error: {
            code: "validation_error",
            message: "The upload was refused.",
            details: [{ field: "directory", message: "A path has no .. in it." }],
          },
        },
        { "X-Request-ID": "req-9" },
      ),
    );

    await waitFor(() =>
      expect(screen.getByLabelText("Directory")).toHaveAccessibleDescription(
        expect.stringContaining("A path has no .. in it."),
      ),
    );
    expect(screen.getByLabelText("Directory")).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText("The upload was refused.")).toBeNull(); // said once, where it belongs
  });

  test("says a refusal that is about no field as the API said it", async () => {
    const user = userEvent.setup();
    const { uploads } = at("raw", "/upload/files");
    await user.upload(await screen.findByLabelText("Files"), file("a.txt"));
    await user.click(send());

    act(() =>
      uploads[0]?.answer(403, {
        error: {
          code: "repository_read_only",
          message: "This repository is read-only.",
          details: [],
        },
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("This repository is read-only.");
    expect(screen.getByRole("list", { name: "Chosen for Files" })).toBeVisible(); // to try again
  });

  test("says so when the server could not be reached", async () => {
    const user = userEvent.setup();
    const { uploads } = at("raw", "/upload/files");
    await user.upload(await screen.findByLabelText("Files"), file("a.txt"));
    await user.click(send());

    act(() => uploads[0]?.fail());

    expect(await screen.findByRole("alert")).toHaveTextContent("The server could not be reached.");
  });
});

describe("uploading to a Maven repository", () => {
  test("sends the coordinates, the artifact, a POM and files with classifiers", async () => {
    const user = userEvent.setup();
    const { uploads } = at("maven", "/upload/releases");

    await user.type(await screen.findByLabelText(/^Group/), "com.acme");
    await user.type(screen.getByLabelText(/^Artifact name/), "app");
    await user.type(screen.getByLabelText(/^Version/), "1.0");
    await user.upload(screen.getByLabelText("Artifact"), file("build-output.jar"));
    await user.upload(screen.getByLabelText("POM"), file("pom.xml"));
    await user.click(screen.getByRole("checkbox", { name: "Write a POM if the version has none" }));
    await user.click(screen.getByRole("button", { name: "Add another file" }));
    const extra = screen.getByRole("group", { name: "Another file of this version" });
    await user.type(within(extra).getByLabelText("Classifier"), "sources");
    await user.upload(within(extra).getByLabelText("File"), file("s.jar"));
    await user.click(send());

    expect(uploads[0]?.url).toBe("/api/v1/content/releases/upload");
    expect(uploads[0]?.parts).toEqual([
      ["file", "file:build-output.jar"],
      ["group", "com.acme"],
      ["artifact", "app"],
      ["version", "1.0"],
      ["packaging", "jar"],
      ["generate_pom", "false"],
      ["pom", "file:pom.xml"],
      ["file.sources", "file:s.jar"],
    ]);
    await expectAccessible();
  });

  test("asks for a POM to be written unless told not to, and can drop a file it added", async () => {
    const user = userEvent.setup();
    const { uploads } = at("maven", "/upload/releases");

    await user.upload(await screen.findByLabelText("Artifact"), file("app.jar"));
    await user.click(screen.getByRole("button", { name: "Add another file" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.click(send());

    expect(screen.queryByRole("group", { name: "Another file of this version" })).toBeNull();
    expect(uploads[0]?.parts).toEqual([
      ["file", "file:app.jar"],
      ["packaging", "jar"],
      ["generate_pom", "true"],
    ]);
  });

  test("puts each refusal at its own field, a classifier's too", async () => {
    const user = userEvent.setup();
    const { uploads } = at("maven", "/upload/releases");
    await user.upload(await screen.findByLabelText("Artifact"), file("app.jar"));
    await user.click(screen.getByRole("button", { name: "Add another file" }));
    await user.type(screen.getByLabelText("Classifier"), "a/b");
    await user.click(send());

    act(() =>
      uploads[0]?.answer(422, {
        error: {
          code: "validation_error",
          message: "The upload was refused.",
          details: [
            { field: "version", message: "A version is needed." },
            { field: "file.a/b", message: "A classifier has no / in it." },
          ],
        },
      }),
    );

    await waitFor(() =>
      expect(screen.getByLabelText(/^Version/)).toHaveAccessibleDescription("A version is needed."),
    );
    expect(screen.getByLabelText("Classifier")).toHaveAccessibleDescription(
      expect.stringContaining("A classifier has no / in it."),
    );
    expect(screen.queryByRole("alert", { name: /refused/ })).toBeNull();
  });
});

describe("uploading to the other formats", () => {
  test("npm takes one tarball and a tag", async () => {
    const user = userEvent.setup();
    const { uploads } = at("npm", "/upload/npm-own");
    const tarball = await screen.findByLabelText("Tarball");

    expect(tarball).not.toHaveAttribute("multiple");
    expect(screen.getByLabelText("Tag")).toHaveValue("latest");
    await user.upload(tarball, file("left-pad-1.3.0.tgz"));
    await user.clear(screen.getByLabelText("Tag"));
    await user.type(screen.getByLabelText("Tag"), "next");
    await user.click(send());

    expect(uploads[0]?.parts).toEqual([
      ["file", "file:left-pad-1.3.0.tgz"],
      ["tag", "next"],
    ]);
  });

  test("PyPI takes several files, and what the files do not say of themselves", async () => {
    const user = userEvent.setup();
    const { uploads } = at("pypi", "/upload/pypi-own");
    const files = await screen.findByLabelText("Files");

    expect(files).toHaveAttribute("multiple");
    await user.upload(files, [file("demo-1.0-py3-none-any.whl"), file("demo-1.0.tar.gz")]);
    await user.type(screen.getByLabelText("Requires Python"), ">=3.9");
    await user.click(send());

    expect(uploads[0]?.parts).toEqual([
      ["file", "file:demo-1.0-py3-none-any.whl"],
      ["file", "file:demo-1.0.tar.gz"],
      ["requires_python", ">=3.9"],
    ]);
  });
});

describe("where nothing can be uploaded", () => {
  const READER: SessionInfo = { ...ADMIN, permissions: ["repository:*:*:browse"] };

  test.each([
    ["a proxy", "raw", "proxy", ADMIN, "Only a hosted repository takes an upload."],
    [
      "a Docker repository",
      "docker",
      "hosted",
      ADMIN,
      "An image is pushed with a container client",
    ],
    ["a repository one may only look at", "raw", "hosted", READER, "You do not have permission"],
  ])("%s says why, and has no form", async (_, format, type, session, said) => {
    at(format, "/upload/there", session, type);

    expect(await screen.findByRole("alert")).toHaveTextContent(said);
    expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
  });

  test("an address that is no repository's is not found", () => {
    mockApi({});
    navigation.at("/upload/a/b");
    const { container } = renderUi(<UploadScreen />, { session: ADMIN });

    expect(
      screen.getByRole("heading", { level: 1, name: "There is nothing at this address" }),
    ).toBeVisible();
    expect(container.querySelector("main")).toBeNull(); // the shell around it has the one there is
  });
});

describe("choosing where to upload", () => {
  const HELD = [
    repository("files", "raw"),
    repository("central", "maven", "proxy"),
    repository("images", "docker"),
    repository("releases", "maven"),
  ];

  test("offers the hosted repositories that take one", async () => {
    mockApi({ "GET /content": { json: { items: HELD, total: 4 } } });
    renderUi(<UploadChooserScreen />, { session: ADMIN });

    const offered = await screen.findAllByRole("link");

    expect(offered.map((link) => link.getAttribute("href"))).toEqual([
      "/upload/files",
      "/upload/releases",
    ]);
    await expectAccessible();
  });

  test("offers only those the caller may add to, and says so when there is none", async () => {
    mockApi({ "GET /content": { json: { items: HELD, total: 4 } } });
    const { unmount } = renderUi(<UploadChooserScreen />, {
      session: { ...ADMIN, permissions: ["repository:maven:releases:add"] },
    });
    expect((await screen.findAllByRole("link")).map((link) => link.textContent)).toEqual([
      "releasesmaven",
    ]);
    unmount();

    renderUi(<UploadChooserScreen />, { session: { ...ADMIN, permissions: [] } });
    expect(await screen.findByRole("heading", { name: "Nowhere to upload to" })).toBeVisible();
  });
});
