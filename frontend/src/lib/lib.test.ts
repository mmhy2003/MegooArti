import { describe, expect, test, vi } from "vitest";

import { setCsrfToken } from "@/lib/api/client";
import type { RepositoryView, SessionInfo } from "@/lib/api/types";
import { upload } from "@/lib/api/upload";
import { forgetPlaces, movedTo } from "@/lib/places";
import { failure, mockApi } from "@/test/api";
import { ADMIN, NOBODY, VISITOR } from "@/test/render";
import { mockUploads } from "@/test/xhr";

import { deleteFolder, may, takesUploads } from "./content";
import {
  exactTime,
  formatBytes,
  formatFingerprint,
  readChecksum,
  relativeTime,
  shortFingerprint,
} from "./format";
import {
  browseHref,
  componentHref,
  fileHref,
  httpAddress,
  parentOf,
  parseBrowse,
  parseComponent,
  parseUpload,
  searchHref,
  split,
  uploadHref,
} from "./paths";

describe("a fingerprint", () => {
  const SHA256 = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0";

  test("is read out in pairs, in capitals, as people compare them", () => {
    expect(formatFingerprint(SHA256)).toBe(
      "0F:1E:2D:3C:4B:5A:69:78:87:96:A5:B4:C3:D2:E1:F0:0F:1E:2D:3C:4B:5A:69:78:87:96:A5:B4:C3:D2:E1:F0",
    );
  });

  test("is cut to its first eight pairs in a list", () => {
    expect(shortFingerprint(SHA256)).toBe("0F:1E:2D:3C:4B:5A:69:78…");
  });
});

describe("a size", () => {
  test.each([
    [0, "0 B"],
    [1, "1 B"],
    [1023, "1023 B"],
    [1024, "1.0 KiB"],
    [1536, "1.5 KiB"],
    [104857, "102 KiB"],
    [2516582, "2.4 MiB"],
    [10 * 1024 ** 3, "10.0 GiB"],
    [5 * 1024 ** 4, "5.0 TiB"],
    [3000 * 1024 ** 4, "3000 TiB"],
  ])("of %d bytes is written %s", (bytes, written) => {
    expect(formatBytes(bytes)).toBe(written);
  });

  test("that is not one is written as nothing", () => {
    expect(formatBytes(-1)).toBe("");
    expect(formatBytes(Number.NaN)).toBe("");
  });
});

describe("a time", () => {
  const now = new Date("2026-10-12T12:00:00Z");
  const ago = (seconds: number) => new Date(now.getTime() - seconds * 1000);

  test.each([
    [0, "just now"],
    [59, "just now"],
    [60, "1 minute ago"],
    [3599, "59 minutes ago"],
    [3600, "1 hour ago"],
    [86400, "yesterday"],
    [3 * 86400, "3 days ago"],
    [45 * 86400, "last month"],
    [800 * 86400, "2 years ago"],
  ])("%d seconds back is %s", (seconds, said) => {
    expect(relativeTime(ago(seconds), now)).toBe(said);
  });

  test("ahead of the clock, by a server whose clock differs, is still said sensibly", () => {
    expect(relativeTime(ago(-30), now)).toBe("just now");
    expect(relativeTime(ago(-7200), now)).toBe("in 2 hours");
  });

  test("is exact to the minute, with its date", () => {
    expect(exactTime(new Date(2026, 9, 12, 10, 15))).toBe("Oct 12, 2026, 10:15 AM");
  });
});

describe("a checksum that was pasted", () => {
  const sha1 = "2ef7bde608ce5404e97d5f042f95f89f1c232871";

  test.each([
    ["d41d8cd98f00b204e9800998ecf8427e", "md5"],
    [sha1, "sha1"],
    ["9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08", "sha256"],
    ["a".repeat(128), "sha512"],
  ])("is known by its length: %s", (typed, kind) => {
    expect(readChecksum(typed)).toEqual({ kind, value: typed });
  });

  test("is read as tools print it: in capitals, with spaces, with its name in front", () => {
    expect(readChecksum(`  ${sha1.toUpperCase()}\n`)).toEqual({ kind: "sha1", value: sha1 });
    expect(readChecksum(`sha1:${sha1}`)).toEqual({ kind: "sha1", value: sha1 });
    expect(readChecksum(`SHA1:${sha1}`)).toEqual({ kind: "sha1", value: sha1 });
  });

  test.each(["", "abc", sha1.slice(1), `${sha1}0`, "z".repeat(40), `sha1:${sha1} extra`])(
    "%j is none",
    (typed) => {
      expect(readChecksum(typed)).toBeNull();
    },
  );

  test("named as one kind and as long as another, is the kind its length says", () => {
    expect(readChecksum(`sha256:${sha1}`)).toEqual({ kind: "sha1", value: sha1 });
  });
});

describe("an address", () => {
  const ODD = "a b#c%?&=d/e\\f@g";

  test("of a folder, a file, a component and an upload", () => {
    expect(browseHref("releases")).toBe("/browse/releases");
    expect(browseHref("releases", "com/acme/app")).toBe("/browse/releases/com/acme/app");
    expect(browseHref("releases", "com/acme", "app-1.0.jar")).toBe(
      "/browse/releases/com/acme?file=app-1.0.jar",
    );
    expect(fileHref("releases", "com/acme/app-1.0.jar")).toBe(
      "/browse/releases/com/acme?file=app-1.0.jar",
    );
    expect(fileHref("files", "notes.txt")).toBe("/browse/files?file=notes.txt");
    expect(componentHref("releases", "0190-abc")).toBe("/components/releases/0190-abc");
    expect(uploadHref("files", "docs/v1")).toBe("/upload/files?directory=docs%2Fv1");
    expect(uploadHref("files")).toBe("/upload/files");
    expect(searchHref({ q: "commons lang", format: "", name: undefined })).toBe(
      "/search?q=commons+lang",
    );
  });

  test("holds a name as text, whatever is in it", () => {
    const href = browseHref("files", `docs/${ODD.split("/")[0]}`, ODD);
    const address = new URL(href, "https://ui.test");

    // Nothing of the name became a query, a fragment or another segment.
    expect(address.hash).toBe("");
    expect(Array.from(address.searchParams.keys())).toEqual(["file"]);
    expect(address.searchParams.get("file")).toBe(ODD);
    expect(parseBrowse(address.pathname)).toEqual({
      repository: "files",
      folder: "docs/a b#c%?&=d",
    });
  });

  test("of an npm scope and of a Docker digest goes there and back", () => {
    for (const folder of ["@acme/tool/-", "manifests/team/app", "blobs/sha256:ab12"]) {
      const address = new URL(browseHref("r", folder), "https://ui.test");

      expect(parseBrowse(address.pathname)).toEqual({ repository: "r", folder });
    }
  });

  test("is read back into what it names", () => {
    expect(parseBrowse("/browse/releases")).toEqual({ repository: "releases", folder: "" });
    expect(parseBrowse("/browse/releases/com/acme/")).toEqual({
      repository: "releases",
      folder: "com/acme",
    });
    expect(parseComponent("/components/releases/0190-abc")).toEqual({
      repository: "releases",
      id: "0190-abc",
    });
    expect(parseUpload("/upload/files")).toEqual({ repository: "files" });
  });

  test.each(["/browse", "/browse/", "/browsers/x", "/search", "/browse/%E0%A4%A"])(
    "%s is not a folder of a repository",
    (pathname) => {
      expect(parseBrowse(pathname)).toBeNull();
    },
  );

  test("from the API becomes a link only if it is an http or https one", () => {
    const download = "https://repo.example.com/repository/files/a%20b.txt";

    expect(httpAddress(download)).toBe(download);
    expect(httpAddress("http://localhost:8000/repository/files/a.txt")).not.toBeNull();
    for (const other of [
      "javascript:alert(1)",
      "JavaScript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "//evil.example/a.txt",
      "/repository/files/a.txt",
      "not an address",
      "",
      null,
      undefined,
    ]) {
      expect(httpAddress(other)).toBeNull();
    }
  });

  test("that is not a component's or an upload's is not read as one", () => {
    expect(parseComponent("/components/releases")).toBeNull();
    expect(parseComponent("/components/releases/id/more")).toBeNull();
    expect(parseUpload("/upload")).toBeNull();
    expect(parseUpload("/upload/a/b")).toBeNull();
  });

  test("of a path splits into its folder and its name", () => {
    expect(split("com/acme/app.jar")).toEqual({ folder: "com/acme", name: "app.jar" });
    expect(split("app.jar")).toEqual({ folder: "", name: "app.jar" });
    expect(parentOf("com/acme")).toBe("com");
    expect(parentOf("com")).toBe("");
    expect(parentOf("")).toBeNull();
  });
});

describe("what a caller is offered in a repository", () => {
  const hosted = (format: string, type = "hosted"): RepositoryView => ({
    name: "r",
    format,
    type,
    online: true,
    url: "",
    setup: [],
  });
  const publisher: SessionInfo = { ...ADMIN, permissions: ["repository:raw:r:add"] };

  test("deleting, only with delete on it", () => {
    expect(may(ADMIN, hosted("raw"), "delete")).toBe(true);
    expect(may(publisher, hosted("raw"), "delete")).toBe(false);
    expect(may(NOBODY, hosted("raw"), "delete")).toBe(false);
    expect(may(undefined, hosted("raw"), "delete")).toBe(false);
    expect(may(VISITOR, hosted("raw"), "delete")).toBe(false);
  });

  test("uploading, with add or edit, to a hosted repository of a format that takes one", () => {
    expect(takesUploads(publisher, hosted("raw"))).toBe(true);
    expect(takesUploads({ ...ADMIN, permissions: ["repository:raw:r:edit"] }, hosted("raw"))).toBe(
      true,
    );
    expect(takesUploads({ ...ADMIN, permissions: ["repository:raw:r:read"] }, hosted("raw"))).toBe(
      false,
    );
    expect(takesUploads(ADMIN, hosted("raw", "proxy"))).toBe(false);
    expect(takesUploads(ADMIN, hosted("raw", "group"))).toBe(false);
    expect(takesUploads(ADMIN, hosted("docker"))).toBe(false);
    for (const format of ["maven", "npm", "pypi"])
      expect(takesUploads(ADMIN, hosted(format))).toBe(true);
  });
});

describe("deleting a folder", () => {
  test("is done in the pieces the API does it in, and says how far it is", async () => {
    const answers = [
      { deleted: 1000, skipped: 0, next: "logs/day-999" },
      { deleted: 998, skipped: 2, next: "logs/day-1999" },
      { deleted: 5, skipped: 0, next: null },
    ];
    const { calls } = mockApi({ "DELETE /content/files/tree": () => ({ json: answers.shift() }) });
    const seen: number[] = [];

    const done = await deleteFolder("files", "logs", {
      onProgress: (progress) => seen.push(progress.deleted),
    });

    expect(done).toEqual({ deleted: 2003, skipped: 2, finished: true });
    expect(seen).toEqual([1000, 1998, 2003]);
    expect(calls.map((call) => call.path)).toEqual([
      "/content/files/tree?path=logs",
      "/content/files/tree?path=logs&after=logs%2Fday-999",
      "/content/files/tree?path=logs&after=logs%2Fday-1999",
    ]);
  });

  test("stops between pieces when told to, and says what it had done", async () => {
    const stop = new AbortController();
    mockApi({
      "DELETE /content/files/tree": { json: { deleted: 1000, skipped: 0, next: "logs/more" } },
    });

    const done = await deleteFolder("files", "logs", {
      onProgress: () => stop.abort(),
      signal: stop.signal,
    });

    expect(done).toEqual({ deleted: 1000, skipped: 0, finished: false });
  });

  test("fails as the API failed, with what was done before left done", async () => {
    let asked = 0;
    mockApi({
      "DELETE /content/files/tree": () =>
        asked++ === 0
          ? { json: { deleted: 1000, skipped: 0, next: "logs/more" } }
          : failure(403, "forbidden", "You do not have permission to do this."),
    });

    await expect(deleteFolder("files", "logs")).rejects.toMatchObject({ code: "forbidden" });
  });
});

describe("where a screen was", () => {
  test("is nowhere when it is first shown, and somewhere else once it has moved", () => {
    expect(movedTo("browse", "releases/")).toBe(false); // the page was just loaded
    expect(movedTo("browse", "releases/")).toBe(false); // shown again, in the same place
    expect(movedTo("browse", "releases/com")).toBe(true);
    expect(movedTo("search", "1")).toBe(false); // another screen has its own place

    forgetPlaces();
    expect(movedTo("browse", "releases/")).toBe(false);
  });
});

describe("an upload", () => {
  const form = () => {
    const body = new FormData();
    body.append("directory", "docs");
    body.append("file", new File(["x"], "a.txt"));
    return body;
  };

  test("is one form sent to the API, with the session's token, and answers what was stored", async () => {
    const uploads = mockUploads();
    setCsrfToken("token-of-the-session");

    const done = upload<{ files: unknown[] }>("/content/files/upload", form());
    uploads[0]?.answer(201, { files: [{ path: "docs/a.txt" }], components: [] });

    expect(await done).toEqual({ files: [{ path: "docs/a.txt" }], components: [] });
    expect([uploads[0]?.method, uploads[0]?.url]).toEqual(["POST", "/api/v1/content/files/upload"]);
    expect(uploads[0]?.headers).toEqual({
      Accept: "application/json",
      "X-CSRF-Token": "token-of-the-session",
    });
    // The browser writes the form's content type itself, with its boundary.
    expect(uploads[0]?.parts).toEqual([
      ["directory", "docs"],
      ["file", "file:a.txt"],
    ]);
  });

  test("says how much has gone", async () => {
    const uploads = mockUploads();
    const seen = vi.fn();

    const done = upload("/content/files/upload", form(), { onProgress: seen });
    uploads[0]?.progress(512, 2048);
    uploads[0]?.progress(2048, 2048);
    uploads[0]?.answer(201, {});
    await done;

    expect(seen.mock.calls).toEqual([[{ sent: 512, total: 2048 }], [{ sent: 2048, total: 2048 }]]);
  });

  test("fails as any request fails: with the API's error and the request's ID", async () => {
    const uploads = mockUploads();

    const done = upload("/content/files/upload", form());
    uploads[0]?.answer(
      422,
      {
        error: {
          code: "validation_error",
          message: "No.",
          details: [{ field: "file", message: "Two files are named a.txt." }],
        },
      },
      { "X-Request-ID": "req-9" },
    );

    await expect(done).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      requestId: "req-9",
      details: [{ field: "file", message: "Two files are named a.txt." }],
    });
  });

  test.each([
    [502, "<html>Bad Gateway</html>"],
    [413, ""],
    [201, "not json"],
  ])("is still an error when the answer is %d with %j", async (status, body) => {
    const uploads = mockUploads();

    const done = upload("/content/files/upload", form());
    uploads[0]?.answer(status, body);

    await expect(done).rejects.toMatchObject({ status, code: "unexpected_answer" });
  });

  test("says so when no answer came", async () => {
    const uploads = mockUploads();

    const done = upload("/content/files/upload", form());
    uploads[0]?.fail();

    await expect(done).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  test("can be stopped, and then ends as one that was", async () => {
    const uploads = mockUploads();
    const stop = new AbortController();

    const done = upload("/content/files/upload", form(), { signal: stop.signal });
    stop.abort();

    await expect(done).rejects.toMatchObject({ name: "AbortError" });
    expect(uploads[0]?.aborted).toBe(true);
  });

  test("is not started at all if it was stopped before", async () => {
    const uploads = mockUploads();
    const stop = new AbortController();
    stop.abort();

    await expect(upload("/x", form(), { signal: stop.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(uploads).toHaveLength(0);
  });
});
