# Browsing, Search, Upload and Delete Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person who uses the repositories can do so in the web UI: open a repository one folder at a time, see everything known of a file and download it, read how to use a component and copy it, search from every screen, upload to a hosted repository with the form its format needs, and delete a file, a version or a folder.

**Architecture:** Each screen is a client component that reads where it is from the address and asks the content API of plan 8 for what it shows, through TanStack Query. Addresses are made and read in one module, a segment at a time, so that nothing in a name is ever read as part of an address. The upload is the one request made with `XMLHttpRequest`, for its progress. What a caller may not do is left out by asking the session's permissions; the server decides in every case. No backend change.

**Tech Stack:** Next.js 16.4 (App Router), React 19.3, TypeScript 5.9, Tailwind CSS 4.3, Radix primitives, TanStack Query 5, `next-intl` 4, Vitest 5 with Testing Library and axe, Playwright with `@axe-core/playwright`. No new dependency.

**Spec:** [docs/superpowers/specs/2026-10-12-frontend-design.md](../specs/2026-10-12-frontend-design.md), section 12 (decisions S1 to S12, and 12.2). Business requirements: [docs/BRD.md](../../BRD.md) CMP-1 to CMP-7, UI-1 to UI-6. Task 7 amends the spec where this plan settles something it left open.

**Read first:** `frontend/AGENTS.md`. Next.js 16 is not the Next.js of earlier years: `params` is a promise, a route's title is its `metadata` or `generateMetadata`, and `next typegen` writes the types of the routes that `typedRoutes` checks links against. Its documentation is in `frontend/node_modules/next/dist/docs/`.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| B1 | A name someone chose (a repository, a folder, a version) is never put in capitals: not in a screen's title, not in a dialog's title, and not in the label that asks for it to be typed. | Names tell capitals from small letters, and the name typed to confirm is compared exactly. |
| B2 | A folder that is not there says so and leads to the top of its repository. | Deleting the last file of a folder removes the folder, and those above it that held nothing else. The screen a delete returns to can be such a folder. |
| B3 | A folder or a file in a list is named to a screen reader with its kind: "Folder docs", "File guide.md". | The icon that tells them apart is not read. |
| B4 | The upload is the one request made with `XMLHttpRequest`. | `fetch` cannot say how much of a body has been sent. Its failures are the same `ApiError`. |
| B5 | The file field is emptied after each choice, so that files add up. The browser's own "No file chosen" beside it is not shown: the list under the field says what is chosen. | The two contradicted each other. |
| B6 | What was fetched of a repository is forgotten after an upload or a delete in it. | An index or a metadata file can change with any of them. |
| B7 | A screen inside the shell that is given an address it cannot read says that nothing is there, inside the shell (`NothingHere`). The page for an address no route answers (`NotFoundScreen`) has no shell. | Two `main` landmarks otherwise. |
| B8 | The lint refuses text written into a property that is read out (`aria-label`, `title`, `alt`, `placeholder`, `label`, `hint`). | Left open by plan 9: UI-4 is about every text a person meets. |
| B9 | A button that is busy keeps the keyboard: it is marked `aria-disabled` and ignores a press. | A disabled button loses focus. Left open by plan 9. |
| B10 | A download link is made only of an `http` or `https` address. | It is the one thing from the API that the UI makes into a link out of itself. |
| B11 | The texts of every screen of this plan are added to `messages/en.json` in Task 2. | One file, typed as a whole: a screen's task then changes no shared file. |

## Global Constraints

- **A colour is written in `src/styles/tokens.css` and nowhere else.** Components use the utilities of `globals.css`.
- **Text a person reads or hears is in `messages/en.json`.** No literal text in markup or in a property that is read out (ESLint refuses both from Task 2 on).
- **What comes from the API is text.** A name or a path goes into an address through `lib/paths.ts`, never by joining strings in a screen.
- **Nothing is loaded from, or sent to, another origin.**
- **The Next.js server never calls the backend.** Data is fetched in the browser.
- **What a caller may not do is not offered** (UI-2); the server is still what decides.
- **Status is never colour alone. Every control has a name, and everything works by keyboard.**
- **Formatting:** Prettier, 100 columns, LF line endings. ESLint and `tsc` are clean after every task.
- **This plan adds no dependency, no migration, no backend code and no setting.** The one backend file it touches is a test.

**Working directories:** run `pnpm` commands in `frontend/`, `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A name that is markup, or made of an address's own characters** (`<img onerror>`, a space, `#`, `?`, `%`, a `%` that encodes nothing): shown as text, one segment of an address, read back as it was; an address from the API that is not a web address (Tasks 1, 3, 4 and 7).
2. **A caller who may not:** no upload and no delete is offered; the form's address typed by hand says no; a visitor with anonymous access; a group, a proxy and a Docker repository, which take no upload (Tasks 1, 3, 5 and 7).
3. **A slip before something is destroyed:** Cancel has the keyboard, a folder's name must be typed exactly and is shown as written, a delete the format refuses, a folder delete that fails or leaves files behind, the folder being gone afterwards (Tasks 2, 3 and 7).
4. **An upload that does not go through:** refused at a field, refused for no field, no answer, stopped by the person, pressed twice (Tasks 1, 5 and 7).
5. **Lists that are long, empty or gone:** a folder of more entries than one request brings, pages of results, a page number that is none, nothing found, a checksum that is none (Tasks 3 and 4).

---

### Task 1: Addresses, formats and the requests of the screens

**Files:**
- Create: `frontend/src/lib/format.ts`, `frontend/src/lib/paths.ts`, `frontend/src/lib/api/upload.ts`, `frontend/src/lib/content.ts`
- Modify: `frontend/src/lib/api/client.ts`, `frontend/src/lib/api/types.ts`
- Test: `frontend/src/test/xhr.ts`, `frontend/src/lib/lib.test.ts`

**Interfaces:**
- Consumes: `api`, `ApiError`, `API_PREFIX` of `lib/api/client.ts`; `allows(session, permission)` of `lib/session/rules.ts`; the generated `schema.d.ts`.
- Produces:
  - `lib/format.ts`: `formatBytes(bytes) -> string`, `relativeTime(moment: Date, now: Date) -> string`, `exactTime(moment: Date) -> string`, `readChecksum(typed) -> { kind: "md5" | "sha1" | "sha256" | "sha512"; value } | null`.
  - `lib/paths.ts`: `browseHref(repository, folder?, file?)`, `fileHref(repository, path)`, `componentHref(repository, id)`, `uploadHref(repository, directory?)`, `searchHref(wanted)`, all returning `Route`; `split(path) -> { folder, name }`, `parentOf(folder) -> string | null`; `parseBrowse(pathname) -> { repository, folder } | null`, `parseComponent(pathname) -> { repository, id } | null`, `parseUpload(pathname) -> { repository } | null`; `httpAddress(address) -> string | null`.
  - `lib/api/client.ts` now also exports `REQUEST_ID`, `csrfHeader() -> Record<string, string>`, `errorOf(status, body, requestId) -> ApiError`.
  - `lib/api/types.ts`: `Entry`, `Listing`, `AssetView`, `ComponentRef`, `ComponentDetail`, `UsageView`, `SearchResult`, `Uploaded`, `FolderDeleted`.
  - `lib/api/upload.ts`: `upload<T>(path, form: FormData, { onProgress?, signal? }) -> Promise<T>`, `Sent = { sent, total }`. A stop rejects with a `DOMException` named `AbortError`.
  - `lib/content.ts`: `FOLDER_AT_ONCE`, `RESULTS_AT_ONCE`, `may(session, repository, "add" | "edit" | "delete")`, `takesUploads(session, repository)`, `useRepositories()`, `useRepository(name)`, `useFolder(repository, folder)` (an infinite query), `useAsset(repository, path)`, `useComponent(repository, id)`, `Wanted`, `useSearch(wanted, page)`, `forget(client, repository)`, `useDeleteAsset(repository)`, `useDeleteComponent(repository)`, `deleteFolder(repository, folder, { onProgress?, signal? }) -> Promise<{ deleted, skipped, finished }>`, `FolderProgress`.
  - For tests: `mockUploads() -> FakeUpload[]`; a `FakeUpload` has `method`, `url`, `headers`, `parts`, `aborted`, and `progress(loaded, total)`, `answer(status, body, headers?)`, `fail()`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/test/xhr.ts`:

```ts
import { vi } from "vitest";

/** One upload the UI started, as a test looks at it and answers it. */
export class FakeUpload {
  method = "";
  url = "";
  headers: Record<string, string> = {};
  /** The parts of the form that was sent: its name, and a text or a file's name. */
  parts: [string, string][] = [];
  status = 0;
  responseText = "";
  aborted = false;
  upload: { onprogress: ((event: unknown) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  private answered: Record<string, string> = {};

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  getResponseHeader(name: string): string | null {
    return this.answered[name] ?? null;
  }

  send(form: FormData): void {
    this.parts = Array.from(form.entries()).map(([name, value]) => [
      name,
      typeof value === "string" ? value : `file:${value.name}`,
    ]);
    sent.push(this);
  }

  abort(): void {
    this.aborted = true;
    this.onabort?.();
  }

  /** So much of the body has gone out. */
  progress(loaded: number, total: number): void {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }

  /** The API answers. */
  answer(status: number, body: unknown, headers: Record<string, string> = {}): void {
    this.status = status;
    this.responseText = typeof body === "string" ? body : JSON.stringify(body);
    this.answered = headers;
    this.onload?.();
  }

  /** No answer comes at all. */
  fail(): void {
    this.onerror?.();
  }
}

let sent: FakeUpload[] = [];

/** Stands in for the browser's uploader. What the UI sends is in the list it returns. */
export function mockUploads(): FakeUpload[] {
  sent = [];
  vi.stubGlobal("XMLHttpRequest", FakeUpload);
  return sent;
}
```

Create `frontend/src/lib/lib.test.ts`:

```ts
import { describe, expect, test, vi } from "vitest";

import { setCsrfToken } from "@/lib/api/client";
import type { RepositoryView, SessionInfo } from "@/lib/api/types";
import { upload } from "@/lib/api/upload";
import { failure, mockApi } from "@/test/api";
import { ADMIN, NOBODY, VISITOR } from "@/test/render";
import { mockUploads } from "@/test/xhr";

import { deleteFolder, may, takesUploads } from "./content";
import { exactTime, formatBytes, readChecksum, relativeTime } from "./format";
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file fails and none of its tests runs: `Failed to resolve import "./format" from "src/lib/lib.test.ts"`. The other 342 tests pass.

- [ ] **Step 3: Implement**

Create `frontend/src/lib/format.ts`:

```ts
/** How a size, a time and a checksum are written for a person. No React here. */

const UNITS = ["B", "KiB", "MiB", "GiB", "TiB"] as const;

/** A size in binary units: `0 B`, `1.5 KiB`, `2.4 MiB`. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  // Whole bytes are whole. Above that, one decimal until the number has three digits.
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${UNITS[unit]}`;
}

const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** How long ago, in the UI's language: "3 days ago", "just now". */
export function relativeTime(moment: Date, now: Date): string {
  const seconds = Math.round((moment.getTime() - now.getTime()) / 1000);
  const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [unit, size] of STEPS) {
    if (Math.abs(seconds) >= size) return format.format(Math.trunc(seconds / size), unit);
  }
  return "just now";
}

/** The exact time, in the reader's own zone: "Oct 12, 2026, 10:15 AM". */
export function exactTime(moment: Date): string {
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(moment);
}

export const CHECKSUMS = { 32: "md5", 40: "sha1", 64: "sha256", 128: "sha512" } as const;
export type ChecksumKind = (typeof CHECKSUMS)[keyof typeof CHECKSUMS];

/**
 * Which checksum a pasted text is, by its length, and the text as the API takes it.
 * Tools print them in either case, with spaces around, or with the name in front
 * (`sha256:9f86...`). Null if it is none.
 */
export function readChecksum(typed: string): { kind: ChecksumKind; value: string } | null {
  const value = typed
    .trim()
    .toLowerCase()
    .replace(/^(md5|sha1|sha256|sha512):/, "");
  if (!/^[0-9a-f]+$/.test(value)) return null;
  const kind = CHECKSUMS[value.length as keyof typeof CHECKSUMS];
  return kind ? { kind, value } : null;
}
```

Create `frontend/src/lib/paths.ts`:

```ts
/**
 * The addresses of the browsing screens, made and read in one place.
 *
 * A repository's name and a path come from the API and may hold anything a file name
 * can: a space, a `#`, a `%`, an `@`. Each segment is encoded on its way into an
 * address and decoded on its way out, so nothing in a name is ever read as part of the
 * address itself.
 */
import type { Route } from "next";

const BROWSE = "/browse";
const COMPONENTS = "/components";
const UPLOAD = "/upload";
const SEARCH = "/search";

const segments = (path: string) => path.split("/").filter((segment) => segment !== "");
const encoded = (path: string) => segments(path).map(encodeURIComponent).join("/");

function withQuery(base: string, query: Record<string, string | undefined>): Route {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value) search.set(name, value);
  }
  const text = search.toString();
  return (text ? `${base}?${text}` : base) as Route;
}

/** A folder of a repository, and a file chosen in it. An empty folder is the root. */
export function browseHref(repository: string, folder = "", file?: string): Route {
  const inside = encoded(folder);
  const base = `${BROWSE}/${encodeURIComponent(repository)}${inside ? `/${inside}` : ""}`;
  return withQuery(base, { file });
}

/** A file, by its whole path: its folder, with the file chosen. */
export function fileHref(repository: string, path: string): Route {
  const { folder, name } = split(path);
  return browseHref(repository, folder, name);
}

export function componentHref(repository: string, id: string): Route {
  return `${COMPONENTS}/${encodeURIComponent(repository)}/${encodeURIComponent(id)}` as Route;
}

export function uploadHref(repository: string, directory?: string): Route {
  return withQuery(`${UPLOAD}/${encodeURIComponent(repository)}`, { directory });
}

export function searchHref(wanted: Record<string, string | undefined>): Route {
  return withQuery(SEARCH, wanted);
}

/**
 * An address the API gave, if a link may lead to it: one of `http` or `https`. A file's
 * download address is built from the installation's base URL, which is a setting, and
 * it is the one thing from the API that the UI makes into a link out of itself.
 */
export function httpAddress(address: string | null | undefined): string | null {
  if (!address) return null;
  try {
    const { protocol } = new URL(address);
    return protocol === "http:" || protocol === "https:" ? address : null;
  } catch {
    return null; // not an address at all
  }
}

/** A path as its folder and its last name. */
export function split(path: string): { folder: string; name: string } {
  const at = path.lastIndexOf("/");
  return at < 0
    ? { folder: "", name: path }
    : { folder: path.slice(0, at), name: path.slice(at + 1) };
}

/** The folder above, or null at the root. */
export function parentOf(folder: string): string | null {
  return folder === "" ? null : split(folder).folder;
}

/** The decoded segments of an address after a prefix, or null if they are not ours. */
function after(pathname: string, prefix: string): string[] | null {
  if (pathname !== prefix && !pathname.startsWith(`${prefix}/`)) return null;
  try {
    return segments(pathname.slice(prefix.length)).map(decodeURIComponent);
  } catch {
    return null; // a `%` that encodes nothing
  }
}

export function parseBrowse(pathname: string): { repository: string; folder: string } | null {
  const [repository, ...folders] = after(pathname, BROWSE) ?? [];
  return repository ? { repository, folder: folders.join("/") } : null;
}

export function parseComponent(pathname: string): { repository: string; id: string } | null {
  const found = after(pathname, COMPONENTS);
  const [repository, id] = found ?? [];
  return found?.length === 2 && repository && id ? { repository, id } : null;
}

export function parseUpload(pathname: string): { repository: string } | null {
  const found = after(pathname, UPLOAD);
  const [repository] = found ?? [];
  return found?.length === 1 && repository ? { repository } : null;
}
```

Change `frontend/src/lib/api/client.ts`:

```diff
@@ -5,7 +5,7 @@
  */
 
 export const API_PREFIX = "/api/v1";
-const REQUEST_ID = "X-Request-ID";
+export const REQUEST_ID = "X-Request-ID";
 const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
 
 export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
@@ -49,6 +49,11 @@ export function setCsrfToken(token: string | null): void {
   csrfToken = token;
 }
 
+/** The header that goes with a request that changes something, if there is a session. */
+export function csrfHeader(): Record<string, string> {
+  return csrfToken === null ? {} : { "X-CSRF-Token": csrfToken };
+}
+
 function address(path: string, query?: Query): string {
   const search = new URLSearchParams();
   for (const [name, value] of Object.entries(query ?? {})) {
@@ -70,19 +75,23 @@ function details(value: unknown): ErrorDetail[] {
   }));
 }
 
+/** The error an answer that is not a success stands for, whatever its body is. */
+export function errorOf(status: number, body: unknown, requestId: string | null): ApiError {
+  const sent = isRecord(body) && isRecord(body.error) ? body.error : null;
+  if (sent === null || typeof sent.code !== "string" || typeof sent.message !== "string") {
+    return new ApiError(status, "unexpected_answer", "", [], requestId);
+  }
+  return new ApiError(status, sent.code, sent.message, details(sent.details), requestId);
+}
+
 async function failure(response: Response): Promise<ApiError> {
-  const requestId = response.headers.get(REQUEST_ID);
   let body: unknown = null;
   try {
     body = await response.json();
   } catch {
     // Not JSON: a gateway's own page, or nothing at all.
   }
-  const sent = isRecord(body) && isRecord(body.error) ? body.error : null;
-  if (sent === null || typeof sent.code !== "string" || typeof sent.message !== "string") {
-    return new ApiError(response.status, "unexpected_answer", "", [], requestId);
-  }
-  return new ApiError(response.status, sent.code, sent.message, details(sent.details), requestId);
+  return errorOf(response.status, body, response.headers.get(REQUEST_ID));
 }
 
 export type RequestOptions = { query?: Query; body?: unknown; signal?: AbortSignal };
@@ -94,7 +103,7 @@ export async function request<T>(
 ): Promise<T> {
   const headers: Record<string, string> = { Accept: "application/json" };
   if (options.body !== undefined) headers["Content-Type"] = "application/json";
-  if (UNSAFE.has(method) && csrfToken !== null) headers["X-CSRF-Token"] = csrfToken;
+  if (UNSAFE.has(method)) Object.assign(headers, csrfHeader());
 
   let response: Response;
   try {
```

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -6,6 +6,17 @@ type Schemas = components["schemas"];
 export type SessionInfo = Schemas["SessionInfo"];
 export type UserSummary = Schemas["UserSummary"];
 export type RepositoryView = Schemas["RepositoryView"];
+/** One thing in a folder: a folder, or a file with its size and when it changed. */
+export type Entry = Schemas["Entry"];
+/** A folder's entries, and the cursor for those that follow. */
+export type Listing = Schemas["Listing"];
+export type AssetView = Schemas["AssetView"];
+export type ComponentRef = Schemas["ComponentRef"];
+export type ComponentDetail = Schemas["ComponentDetail"];
+export type UsageView = Schemas["UsageView"];
+export type SearchResult = Schemas["Result"];
+export type Uploaded = Schemas["Uploaded"];
+export type FolderDeleted = Schemas["FolderDeleted"];
 
 /** A page of a list, as every list endpoint answers. */
 export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
```

Create `frontend/src/lib/api/upload.ts`:

```ts
import { API_PREFIX, ApiError, csrfHeader, errorOf, REQUEST_ID } from "./client";

export type Sent = { sent: number; total: number };

export type UploadOptions = {
  /** Called as the body goes out. `fetch` cannot say how much has been sent. */
  onProgress?: (progress: Sent) => void;
  /** Stops the upload. The promise then rejects with an `AbortError`. */
  signal?: AbortSignal;
};

/**
 * Sends a form with files to the API. It is the one request that is not made with
 * `fetch`: an artifact can be gigabytes, and whoever sends one wants to see it go.
 * Failures are the same `ApiError` as everywhere else.
 */
export function upload<T>(path: string, form: FormData, options: UploadOptions = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_PREFIX}${path}`);
    request.setRequestHeader("Accept", "application/json");
    for (const [name, value] of Object.entries(csrfHeader())) request.setRequestHeader(name, value);

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.({ sent: event.loaded, total: event.total });
    };
    request.onerror = () => reject(new ApiError(0, "network_error", ""));
    request.onabort = () => reject(new DOMException("The upload was stopped.", "AbortError"));
    request.onload = () => {
      const requestId = request.getResponseHeader(REQUEST_ID);
      let body: unknown = null;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        // Not JSON: a gateway's own page, or nothing at all.
      }
      if (request.status >= 200 && request.status < 300 && body !== null) resolve(body as T);
      else if (request.status >= 200 && request.status < 300) {
        reject(new ApiError(request.status, "unexpected_answer", "", [], requestId));
      } else reject(errorOf(request.status, body, requestId));
    };

    if (options.signal?.aborted) {
      reject(new DOMException("The upload was stopped.", "AbortError"));
      return;
    }
    options.signal?.addEventListener("abort", () => request.abort(), { once: true });
    request.send(form);
  });
}
```

Create `frontend/src/lib/content.ts`:

```ts
"use client";

/** What the repositories hold, asked of the content API: the requests of the browsing screens. */
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  AssetView,
  ComponentDetail,
  FolderDeleted,
  Listing,
  Page,
  RepositoryView,
  SearchResult,
  SessionInfo,
} from "@/lib/api/types";
import { allows } from "@/lib/session/rules";

const CONTENT = "content";
// As many entries of a folder as one request asks for. More come with "Show more".
export const FOLDER_AT_ONCE = 100;
export const RESULTS_AT_ONCE = 50;
// The formats whose hosted repositories take an upload through the API.
const UPLOADABLE = new Set(["raw", "maven", "npm", "pypi"]);

const at = (repository: string) => `/content/${encodeURIComponent(repository)}`;

/** Whether to offer a caller something that needs this action on a repository. */
export function may(
  session: SessionInfo | undefined,
  repository: Pick<RepositoryView, "format" | "name">,
  action: "add" | "edit" | "delete",
): boolean {
  if (!session) return false;
  return allows(session, `repository:${repository.format}:${repository.name}:${action}`);
}

/** Whether to offer an upload to this repository to this caller. */
export function takesUploads(
  session: SessionInfo | undefined,
  repository: RepositoryView,
): boolean {
  if (repository.type !== "hosted" || !UPLOADABLE.has(repository.format)) return false;
  return may(session, repository, "add") || may(session, repository, "edit");
}

export function useRepositories() {
  return useQuery({
    queryKey: [CONTENT, "repositories"],
    queryFn: () => api.get<Page<RepositoryView>>("/content", { query: { limit: 200 } }),
  });
}

export function useRepository(name: string) {
  return useQuery({
    queryKey: [CONTENT, "repository", name],
    queryFn: () => api.get<RepositoryView>(at(name)),
    enabled: name !== "",
  });
}

/** A folder's entries, a piece at a time. `enabled` is false for a group, which has none. */
export function useFolder(repository: string, folder: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: [CONTENT, "tree", repository, folder],
    queryFn: ({ pageParam }) =>
      api.get<Listing>(`${at(repository)}/tree`, {
        query: { path: folder, after: pageParam || undefined, limit: FOLDER_AT_ONCE },
      }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next ?? undefined,
    enabled,
  });
}

export function useAsset(repository: string, path: string | null) {
  return useQuery({
    queryKey: [CONTENT, "asset", repository, path],
    queryFn: () => api.get<AssetView>(`${at(repository)}/asset`, { query: { path } }),
    enabled: path !== null,
  });
}

export function useComponent(repository: string, id: string | null) {
  return useQuery({
    queryKey: [CONTENT, "component", repository, id],
    queryFn: () =>
      api.get<ComponentDetail>(`${at(repository)}/components/${encodeURIComponent(id ?? "")}`),
    enabled: id !== null,
  });
}

/** What a search is asked for: the API's own parameters, each a text or absent. */
export type Wanted = Partial<
  Record<
    | "q"
    | "format"
    | "repository"
    | "namespace"
    | "name"
    | "version"
    | "md5"
    | "sha1"
    | "sha256"
    | "sha512",
    string
  >
>;

export function useSearch(wanted: Wanted, page: number) {
  return useQuery({
    queryKey: ["search", wanted, page],
    queryFn: () =>
      api.get<Page<SearchResult>>("/search", {
        query: { ...wanted, limit: RESULTS_AT_ONCE, offset: (page - 1) * RESULTS_AT_ONCE },
      }),
  });
}

/** After something was stored or deleted, nothing that was fetched of the repository is true. */
export function forget(client: QueryClient, repository: string): Promise<void> {
  client.removeQueries({ queryKey: [CONTENT, "asset", repository] });
  client.removeQueries({ queryKey: [CONTENT, "component", repository] });
  void client.invalidateQueries({ queryKey: ["search"] });
  return client.invalidateQueries({ queryKey: [CONTENT, "tree", repository] });
}

export function useDeleteAsset(repository: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => api.delete<void>(`${at(repository)}/asset`, { query: { path } }),
    onSuccess: () => forget(client, repository),
  });
}

export function useDeleteComponent(repository: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.delete<void>(`${at(repository)}/components/${encodeURIComponent(id)}`),
    onSuccess: () => forget(client, repository),
  });
}

export type FolderProgress = { deleted: number; skipped: number };

/**
 * Deletes everything under a folder, in the pieces the API does it in. `onProgress` is
 * told after each piece. It stops between pieces when `signal` says so, and then says
 * how far it got.
 */
export async function deleteFolder(
  repository: string,
  folder: string,
  options: { onProgress?: (progress: FolderProgress) => void; signal?: AbortSignal } = {},
): Promise<FolderProgress & { finished: boolean }> {
  const done = { deleted: 0, skipped: 0 };
  let after: string | null = "";
  while (after !== null) {
    if (options.signal?.aborted) return { ...done, finished: false };
    const piece: FolderDeleted = await api.delete<FolderDeleted>(`${at(repository)}/tree`, {
      query: { path: folder, after: after || undefined },
    });
    done.deleted += piece.deleted;
    done.skipped += piece.skipped;
    options.onProgress?.({ ...done });
    after = piece.next;
  }
  return { ...done, finished: true };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 402 passed in 14 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): addresses, formats and the requests of the browsing screens"
```

---

### Task 2: The components the screens are made of, and their texts

**Files:**
- Create: `frontend/src/components/ui/breadcrumbs.tsx`, `notifications.tsx`, `inputs.tsx`, `details.tsx` (all in `frontend/src/components/ui/`)
- Modify: `frontend/src/components/ui/button.tsx`, `states.tsx`, `field.tsx`, `panel.tsx`, `confirm-dialog.tsx`
- Modify: `frontend/messages/en.json`, `frontend/eslint.config.mjs`, `frontend/src/app/providers.tsx`, `frontend/src/test/render.tsx`
- Test: `frontend/src/test/lint.test.ts`, `frontend/src/components/ui/more.test.tsx`
- Test (modify): `frontend/src/components/ui/ui.test.tsx`

**Interfaces:**
- Consumes: `formatBytes`, `relativeTime`, `exactTime` of Task 1; `CopyButton`, `AppLink`, `Button`, `TextField` of plan 9.
- Produces:
  - `Breadcrumbs({ label, crumbs: { name, href }[] })`, `Crumb`.
  - `NotificationsProvider`, `useNotify() -> (text: string) => void`. The region is `role="region"`, `aria-live="polite"`, named "Notifications"; a notice leaves after 6 seconds or when dismissed. `Providers` and the tests' `renderUi` both wrap in it.
  - `SelectField({ label, hint?, error?, choices: { value, label }[], ...select })`, `CheckboxField({ label, hint?, ...input })`, `FilePicker({ label, hint?, error?, multiple?, accept?, files: File[], onChange(files) })`.
  - `Facts`, `Fact({ name, copy?, mono?, children })`, `Time({ value })`, `Snippet({ label, text })`, `Pager({ page, pages, hrefFor })`, `Progress({ label, value, max })`.
  - `Button`: `busy` now sets `aria-disabled` and ignores a press, and no longer disables.
  - `EmptyState({ ..., page? })`: with `page`, its title is an `h1`.
  - `TextField({ ..., plainLabel? })`, `PageHeader({ ..., named? })`, `ConfirmDialog({ ..., mustType? })`: see B1.
  - `messages/en.json`: the groups `notifications`, `time`, `pager`, `files`, `searchBox`, `browse`, `component`, `search`, `upload`, the items `nav.items.search` and `nav.items.upload`, and `confirm.typeToConfirm`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/test/lint.test.ts`:

```ts
// @vitest-environment node
import { ESLint } from "eslint";
import { expect, test } from "vitest";

const eslint = new ESLint();
// The two rules that keep text out of the source. What else the lint says is not asked here.
const RULES = ["react/jsx-no-literals", "no-restricted-syntax"];
const SLOW = 60_000; // the lint reads its whole configuration for the first file

/** Which of them a screen with this markup breaks, as the project's own lint finds it. */
async function broken(markup: string): Promise<string[]> {
  const source = `export function Sample({ said }: { said: string }) {\n  return ${markup};\n}\n`;
  const [result] = await eslint.lintText(source, { filePath: "src/screens/sample.tsx" });
  const found = (result?.messages ?? []).map((message) => message.ruleId ?? message.message);
  return found.filter((rule) => RULES.includes(rule));
}

// What a person reads or hears is in messages/en.json (UI-4): the lint holds it there.
test(
  "text written into markup is refused",
  async () => {
    expect(await broken("<p>Hello</p>")).toEqual(["react/jsx-no-literals"]);
    expect(await broken("<p>{said}</p>")).toEqual([]);
  },
  SLOW,
);

test.each([
  '<button aria-label="Close" />',
  '<abbr title="Mebibyte">{said}</abbr>',
  '<img alt="A diagram" src="/a.svg" />',
  '<input placeholder="Search" />',
  '<input aria-label={"Search"} />',
  "<input aria-label={`Search ${said}`} />",
  '<progress aria-valuetext="Half" />',
])(
  "text written into a property that is read out is refused: %s",
  async (markup) => {
    expect(await broken(markup)).toEqual(["no-restricted-syntax"]);
  },
  SLOW,
);

test.each([
  "<button aria-label={said} />",
  '<button type="button" className="p-4" aria-hidden="true" role="status" />',
  '<a href="/search" aria-current="page">{said}</a>',
  '<input aria-keyshortcuts="/" name="q" />',
])(
  "what nobody reads is let be: %s",
  async (markup) => {
    expect(await broken(markup)).toEqual([]);
  },
  SLOW,
);
```

Change `frontend/src/components/ui/ui.test.tsx`:

```diff
@@ -44,7 +44,11 @@ describe("a button", () => {
 
     expect(pressed).not.toHaveBeenCalled();
     expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
-    expect(screen.getByRole("button")).toBeDisabled();
+    expect(screen.getByRole("button")).toHaveAttribute("aria-disabled", "true");
+    // It keeps the keyboard: a button disabled outright drops focus to the page.
+    expect(screen.getByRole("button")).toHaveFocus();
+    await user.keyboard("{Enter}");
+    expect(pressed).not.toHaveBeenCalled();
   });
 
   test("can be a link that looks like one", async () => {
```

Create `frontend/src/components/ui/more.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 8 tests fail and 1 file does not load. In `lint.test.ts`, the seven of "text written into a property that is read out is refused" (the lint finds nothing). In `ui.test.tsx`, "cannot be pressed again while what it started is under way, and says so" (the button is disabled, and has no `aria-disabled`). `more.test.tsx` fails with `Failed to resolve import "./breadcrumbs"`.

- [ ] **Step 3: Implement**

Change `frontend/eslint.config.mjs`:

```diff
@@ -2,6 +2,11 @@ import { defineConfig, globalIgnores } from "eslint/config";
 import nextVitals from "eslint-config-next/core-web-vitals";
 import nextTs from "eslint-config-next/typescript";
 
+// The properties whose value a person reads or hears.
+const READ =
+  "/^(aria-label|aria-description|aria-valuetext|aria-roledescription|title|alt|placeholder|label|hint)$/";
+const FROM_MESSAGES = "Text a person reads or hears comes from messages/en.json (UI-4).";
+
 const eslintConfig = defineConfig([
   ...nextVitals,
   ...nextTs,
@@ -11,6 +16,15 @@ const eslintConfig = defineConfig([
     ignores: ["src/**/*.test.tsx", "src/test/**"],
     rules: {
       "react/jsx-no-literals": ["error", { noStrings: true, ignoreProps: true }],
+      // That rule cannot tell a property that is read out from a class name: this one can.
+      "no-restricted-syntax": [
+        "error",
+        { selector: `JSXAttribute[name.name=${READ}] > Literal`, message: FROM_MESSAGES },
+        {
+          selector: `JSXAttribute[name.name=${READ}] > JSXExpressionContainer > :matches(Literal, TemplateLiteral)`,
+          message: FROM_MESSAGES,
+        },
+      ],
     },
   },
   globalIgnores([
```

Change `frontend/messages/en.json`:

```diff
@@ -15,7 +15,9 @@
       "administration": "Administration"
     },
     "items": {
-      "repositories": "Repositories"
+      "repositories": "Repositories",
+      "search": "Search",
+      "upload": "Upload"
     }
   },
   "theme": {
@@ -76,7 +78,8 @@
     },
     "emptyTitle": "No repositories",
     "empty": "There is no repository you can browse. An administrator creates repositories and says who may use them.",
-    "more": "Showing {shown} of {total}."
+    "more": "Showing {shown} of {total}.",
+    "browse": "Browse {name}"
   },
   "copy": {
     "label": "Copy {what}",
@@ -99,7 +102,8 @@
     "fallback": "Something went wrong."
   },
   "confirm": {
-    "cancel": "Cancel"
+    "cancel": "Cancel",
+    "typeToConfirm": "Type {name} to go on"
   },
   "notFound": {
     "title": "There is nothing at this address",
@@ -110,5 +114,196 @@
     "title": "This page stopped working",
     "body": "Something in the page itself failed. Loading it again usually helps.",
     "reload": "Load the page again"
+  },
+  "notifications": {
+    "label": "Notifications",
+    "dismiss": "Dismiss"
+  },
+  "time": {
+    "never": "Never"
+  },
+  "pager": {
+    "label": "Pages",
+    "previous": "Previous",
+    "next": "Next",
+    "position": "Page {page} of {pages}"
+  },
+  "files": {
+    "orDrop": "or drop files here",
+    "chosen": "Chosen for {label}",
+    "remove": "Take out {name}"
+  },
+  "searchBox": {
+    "label": "Search components",
+    "placeholder": "Search  ( / )"
+  },
+  "browse": {
+    "kind": "{format} repository, {type}",
+    "kindProxy": "{format} repository, {type}. What is here is what has been fetched through it.",
+    "path": "Path",
+    "searchIn": "Search this repository",
+    "offline": "This repository is offline: package clients are refused. It can still be browsed here.",
+    "entriesOf": "What is in {folder}",
+    "columns": {
+      "name": "Name",
+      "size": "Size",
+      "modified": "Changed"
+    },
+    "folderNamed": "Folder {name}",
+    "fileNamed": "File {name}",
+    "showMore": "Show more",
+    "emptyTitle": "Nothing here yet",
+    "empty": "This repository holds no file.",
+    "emptyProxy": "Nothing has been fetched through this proxy yet. What it holds is what was asked of it.",
+    "noFolderTitle": "No such folder",
+    "noFolder": "There is nothing at {folder} in this repository.",
+    "toTop": "Go to the top of {repository}",
+    "uploadHere": "Upload here",
+    "membersTitle": "Members",
+    "membersIntro": "A group holds nothing of its own. It answers from these repositories, in this order. Those you may not browse are not listed.",
+    "noMembers": "None that you may browse.",
+    "detailsOf": "Details of {name}",
+    "closeDetails": "Close the details",
+    "facts": {
+      "path": "Path",
+      "size": "Size",
+      "type": "Type",
+      "sha256": "SHA-256",
+      "sha1": "SHA-1",
+      "md5": "MD5",
+      "sha512": "SHA-512",
+      "blobStore": "Blob store",
+      "storedBy": "Stored by",
+      "created": "Stored",
+      "modified": "Changed",
+      "lastDownloaded": "Last downloaded",
+      "component": "Part of"
+    },
+    "download": "Download",
+    "delete": "Delete",
+    "deleteFileTitle": "Delete {name}?",
+    "deleteFileBody": "The file is removed as its format's own client would remove it. It cannot be brought back.",
+    "deleted": "Deleted {name}.",
+    "deleteFolder": "Delete folder",
+    "deleteFolderTitle": "Delete the folder {name}?",
+    "deleteFolderBody": "Every file under {folder} is deleted. It cannot be brought back.",
+    "deletedSoFar": "{deleted, plural, one {# file deleted so far} other {# files deleted so far}}…",
+    "folderDeleted": "Deleted {deleted, plural, one {# file} other {# files}} under {name}.{skipped, plural, =0 {} one { # file is kept by the format.} other { # files are kept by the format.}}",
+    "folderStopped": "Stopped. {deleted, plural, one {# file} other {# files}} under {name} had been deleted."
+  },
+  "component": {
+    "path": "Path",
+    "about": "What it is",
+    "usage": "Use it",
+    "noUsage": "A file of this kind has no command to copy. Its files have their own addresses.",
+    "files": "Files",
+    "facts": {
+      "repository": "Repository",
+      "format": "Format",
+      "namespace": "Group",
+      "name": "Name",
+      "version": "Version",
+      "created": "Stored",
+      "modified": "Changed"
+    },
+    "columns": {
+      "path": "Path",
+      "size": "Size",
+      "modified": "Changed"
+    },
+    "delete": "Delete this version",
+    "deleteTitle": "Delete {name}?",
+    "deleteBody": "{count, plural, one {Its file is} other {Its # files are}} deleted, as the format's own client would delete the version. It cannot be brought back.",
+    "deleted": "Deleted {name}."
+  },
+  "search": {
+    "title": "Search",
+    "intro": "Components in every repository you can browse.",
+    "fields": {
+      "q": "Words",
+      "format": "Format",
+      "repository": "Repository",
+      "namespace": "Group",
+      "name": "Name",
+      "version": "Version",
+      "checksum": "Checksum of a file"
+    },
+    "hints": {
+      "q": "Each word must be in the name, the group, the version or the description. * stands for anything.",
+      "checksum": "MD5, SHA-1, SHA-256 or SHA-512: its length says which."
+    },
+    "any": "Any",
+    "submit": "Search",
+    "notAChecksum": "A checksum is 32, 40, 64 or 128 hexadecimal digits.",
+    "results": "Results",
+    "found": "{total, plural, one {# component} other {# components}} found.",
+    "noneTitle": "Nothing found",
+    "none": "No component you can browse matches. Try fewer words, or * for part of a name.",
+    "columns": {
+      "name": "Name",
+      "namespace": "Group",
+      "version": "Version",
+      "repository": "Repository",
+      "format": "Format",
+      "modified": "Changed"
+    }
+  },
+  "upload": {
+    "title": "Upload",
+    "titleTo": "Upload to {repository}",
+    "path": "Path",
+    "chooserIntro": "The repositories you can upload to.",
+    "nowhereTitle": "Nowhere to upload to",
+    "nowhere": "There is no hosted repository you may add to. A proxy and a group take no upload, and a Docker image is pushed with a container client.",
+    "intro": {
+      "raw": "Files, stored under a directory by their own names.",
+      "maven": "An artifact, stored where its coordinates say. Checksums and metadata follow by themselves.",
+      "npm": "A package tarball, as npm pack writes it. Its package.json says what it is.",
+      "pypi": "Wheels and source distributions. Each one's name says its project and version."
+    },
+    "fields": {
+      "directory": "Directory",
+      "files": "Files",
+      "tarball": "Tarball",
+      "artifactFile": "Artifact",
+      "group": "Group",
+      "artifact": "Artifact name",
+      "version": "Version",
+      "packaging": "Packaging",
+      "pom": "POM",
+      "generatePom": "Write a POM if the version has none",
+      "classifier": "Classifier",
+      "extraFile": "File",
+      "tag": "Tag",
+      "summary": "Summary",
+      "requiresPython": "Requires Python",
+      "keywords": "Keywords"
+    },
+    "hints": {
+      "directory": "Where in the repository the files go. Empty is its root.",
+      "packaging": "What the POM that is written says: jar, war, pom.",
+      "pom": "Optional. Whatever it is called, it is stored as the version's POM.",
+      "generatePom": "A build that depends on an artifact without a POM warns, or fails.",
+      "classifier": "What sets this file apart: sources, javadoc.",
+      "tag": "The dist-tag the version gets.",
+      "requiresPython": "For example >=3.9. Installers then offer the files only to such a Python.",
+      "files": {
+        "raw": "Any files.",
+        "maven": "The file's own name does not matter. What it is (jar, war) is read from its end.",
+        "npm": "One .tgz file.",
+        "pypi": ".whl, .tar.gz or .zip."
+      }
+    },
+    "extraLegend": "Another file of this version",
+    "addExtra": "Add another file",
+    "removeExtra": "Remove",
+    "submit": "Upload",
+    "stop": "Stop",
+    "sending": "{sent} of {total} sent",
+    "stored": "{count, plural, one {# file stored} other {# files stored}}",
+    "notHereTitle": "Nothing can be uploaded here",
+    "notHosted": "Only a hosted repository takes an upload. A proxy holds what its remote has, and a group holds nothing of its own.",
+    "notDocker": "An image is pushed with a container client, not uploaded.",
+    "notAllowed": "You do not have permission to add to this repository."
   }
 }
```

Change `frontend/src/components/ui/button.tsx`:

```diff
@@ -59,9 +59,13 @@ export function Button({
     <button
       type={type ?? "button"}
       className={classes}
-      disabled={disabled || busy}
+      disabled={disabled}
+      // Busy, it cannot be pressed, but it keeps the keyboard: a button that is
+      // disabled outright drops focus to the page.
+      aria-disabled={busy || undefined}
       aria-busy={busy || undefined}
       {...rest}
+      onClick={busy ? (event) => event.preventDefault() : rest.onClick}
     >
       {busy ? <Spinner /> : null}
       {children}
```

Change `frontend/src/components/ui/states.tsx`:

```diff
@@ -43,15 +43,19 @@ export function EmptyState({
   title,
   children,
   action,
+  page = false,
 }: {
   title: string;
   children?: ReactNode;
   action?: ReactNode;
+  /** It is all there is on the page, so its title is the page's heading. */
+  page?: boolean;
 }) {
+  const Heading = page ? "h1" : "h2";
   return (
     <div className="flex flex-col items-center gap-3 p-10 text-center">
       <Inbox aria-hidden="true" className="size-10 text-neon-magenta" />
-      <h2 className="text-lg font-semibold text-fg uppercase">{title}</h2>
+      <Heading className="text-lg font-semibold text-fg uppercase">{title}</Heading>
       {children ? <p className="max-w-prose text-fg-muted">{children}</p> : null}
       {action}
     </div>
```

Change `frontend/src/components/ui/field.tsx`:

```diff
@@ -11,17 +11,29 @@ export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> &
   hint?: string;
   /** What is wrong with what was typed. It replaces the hint. */
   error?: string | null;
+  /** The label has a name in it that must be read exactly: it is not put in capitals. */
+  plainLabel?: boolean;
 };
 
 /** A labelled input. Its hint and its error are read out with it. */
-export function TextField({ label, hint, error, className, ...input }: TextFieldProps) {
+export function TextField({
+  label,
+  hint,
+  error,
+  plainLabel = false,
+  className,
+  ...input
+}: TextFieldProps) {
   const id = useId();
   const hintId = `${id}-hint`;
   const errorId = `${id}-error`;
   const described = error ? errorId : hint ? hintId : undefined;
   return (
     <div className={cn("flex flex-col gap-1.5", className)}>
-      <label htmlFor={id} className="label-caps text-fg-muted">
+      <label
+        htmlFor={id}
+        className={cn("text-fg-muted", plainLabel ? "text-sm font-medium" : "label-caps")}
+      >
         {label}
       </label>
       <input
```

Change `frontend/src/components/ui/panel.tsx`:

```diff
@@ -15,16 +15,29 @@ export function Panel({ className, children, ...rest }: HTMLAttributes<HTMLDivEl
 export function PageHeader({
   title,
   intro,
+  named = false,
   children,
 }: {
   title: string;
   intro?: string;
+  /**
+   * The title has a name in it that someone chose (a repository, a version). Names
+   * tell capitals from small letters, so it is shown as it is written.
+   */
+  named?: boolean;
   children?: ReactNode;
 }) {
   return (
     <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
       <div className="min-w-0">
-        <h1 className="text-2xl font-semibold tracking-wide text-fg uppercase">{title}</h1>
+        <h1
+          className={cn(
+            "text-2xl font-semibold text-fg",
+            named ? "break-words" : "tracking-wide uppercase",
+          )}
+        >
+          {title}
+        </h1>
         {intro ? <p className="mt-1 text-fg-muted">{intro}</p> : null}
       </div>
       {children ? <div className="flex flex-wrap gap-2">{children}</div> : null}
```

Change `frontend/src/components/ui/confirm-dialog.tsx`:

```diff
@@ -2,9 +2,10 @@
 
 import { AlertDialog } from "radix-ui";
 import { useTranslations } from "next-intl";
-import { useRef, type ReactNode } from "react";
+import { useRef, useState, type ReactNode } from "react";
 
 import { Button } from "./button";
+import { TextField } from "./field";
 
 export type ConfirmDialogProps = {
   open: boolean;
@@ -18,6 +19,11 @@ export type ConfirmDialogProps = {
   onConfirm: () => void;
   /** The action is under way: the dialog stays, and its button says so. */
   busy?: boolean;
+  /**
+   * For what takes much with it (a folder, a repository): this must be typed, exactly,
+   * before the button that does it can be pressed.
+   */
+  mustType?: string;
 };
 
 /**
@@ -32,13 +38,22 @@ export function ConfirmDialog({
   confirmLabel,
   onConfirm,
   busy = false,
+  mustType,
 }: ConfirmDialogProps) {
   const t = useTranslations("confirm");
+  const [typed, setTyped] = useState("");
+  const allowed = mustType === undefined || typed === mustType;
   // What had the keyboard when the dialog opened. Radix gives focus back to a trigger
   // of its own, and this dialog is opened by whatever its screen chooses.
   const opener = useRef<HTMLElement | null>(null);
   return (
-    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
+    <AlertDialog.Root
+      open={open}
+      onOpenChange={(next) => {
+        if (!next) setTyped(""); // the next time, it is typed again
+        onOpenChange(next);
+      }}
+    >
       <AlertDialog.Portal>
         <AlertDialog.Overlay className="fixed inset-0 z-40 bg-page/80" />
         <AlertDialog.Content
@@ -52,12 +67,24 @@ export function ConfirmDialog({
           }}
           className="bevel fixed top-1/2 left-1/2 z-50 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 border border-bad bg-panel p-6"
         >
-          <AlertDialog.Title className="text-lg font-semibold text-fg uppercase">
+          {/* Not in capitals: it names what goes, and a name is shown as it is written. */}
+          <AlertDialog.Title className="text-lg font-semibold break-words text-fg">
             {title}
           </AlertDialog.Title>
           <AlertDialog.Description asChild>
             <div className="mt-2 text-fg-muted">{children}</div>
           </AlertDialog.Description>
+          {mustType !== undefined ? (
+            <TextField
+              className="mt-4"
+              label={t("typeToConfirm", { name: mustType })}
+              plainLabel
+              autoComplete="off"
+              spellCheck={false}
+              value={typed}
+              onChange={(event) => setTyped(event.target.value)}
+            />
+          ) : null}
           <div className="mt-6 flex flex-wrap justify-end gap-3">
             <AlertDialog.Cancel asChild>
               <Button>{t("cancel")}</Button>
@@ -65,6 +92,7 @@ export function ConfirmDialog({
             <Button
               variant="danger"
               busy={busy}
+              disabled={!allowed}
               onClick={(event) => {
                 event.preventDefault();
                 onConfirm();
```

Create `frontend/src/components/ui/breadcrumbs.tsx`:

```tsx
import { ChevronRight } from "lucide-react";
import type { Route } from "next";

import { AppLink } from "./link";

export type Crumb = { name: string; href: Route };

/**
 * Where one is, as the way there: each part a link, the last one marked as the present
 * place. `label` names the list for a screen reader.
 */
export function Breadcrumbs({ label, crumbs }: { label: string; crumbs: Crumb[] }) {
  return (
    <nav aria-label={label} className="mb-4">
      <ol className="flex flex-wrap items-center gap-1 font-mono text-sm">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={crumb.href} className="flex min-w-0 items-center gap-1">
              {index > 0 ? (
                <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-fg-subtle" />
              ) : null}
              <AppLink
                href={crumb.href}
                aria-current={last ? "page" : undefined}
                className={
                  last
                    ? "rounded-sm px-1 break-all text-ink-cyan"
                    : "rounded-sm px-1 break-all text-fg-muted underline-offset-4 hover:text-fg hover:underline"
                }
              >
                {crumb.name}
              </AppLink>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
```

Create `frontend/src/components/ui/notifications.tsx`:

```tsx
"use client";

import { CircleCheck, X } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Notice = { id: number; text: string };

const NotifyContext = createContext<((text: string) => void) | null>(null);

// Long enough to read a sentence, and to reach it with a screen reader.
const STAYS_FOR = 6000;

/**
 * Says that something was done: "Deleted app-1.0.jar". After a delete, the thing that
 * was acted on is gone, so there is nowhere beside it to say so. A notice is read out
 * by a screen reader and goes by itself. What failed is not said here: a failure stays
 * on its screen until it is dealt with.
 */
export function NotificationsProvider({ children }: { children: ReactNode }) {
  const t = useTranslations("notifications");
  const [notices, setNotices] = useState<Notice[]>([]);
  const next = useRef(1);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setNotices((shown) => shown.filter((notice) => notice.id !== id));
  }, []);

  const notify = useCallback(
    (text: string) => {
      const id = next.current++;
      setNotices((shown) => [...shown, { id, text }]);
      timers.current.set(
        id,
        window.setTimeout(() => dismiss(id), STAYS_FOR),
      );
    },
    [dismiss],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const region = useMemo(
    () => (
      // Always in the page, so that what appears in it is announced. A region of its
      // own, with a name: a screen reader can go to it, and it is not mistaken for
      // the status of whatever screen is under it.
      <div
        role="region"
        aria-live="polite"
        aria-label={t("label")}
        className="fixed right-4 bottom-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {notices.map((notice) => (
          <div
            key={notice.id}
            className="bevel flex items-start gap-3 border border-ok bg-panel px-4 py-3 shadow-glow-sm"
          >
            <CircleCheck aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-ink-ok" />
            <p className="min-w-0 flex-1 text-sm break-words text-fg">{notice.text}</p>
            <button
              type="button"
              aria-label={t("dismiss")}
              onClick={() => dismiss(notice.id)}
              className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-fg-muted hover:text-fg"
            >
              <X aria-hidden="true" className="size-4" />
            </button>
          </div>
        ))}
      </div>
    ),
    [notices, dismiss, t],
  );

  return (
    <NotifyContext.Provider value={notify}>
      {children}
      {region}
    </NotifyContext.Provider>
  );
}

/** A function that says, for a few seconds, that something was done. */
export function useNotify(): (text: string) => void {
  const notify = useContext(NotifyContext);
  if (notify === null) throw new Error("useNotify is used outside NotificationsProvider");
  return notify;
}
```

Create `frontend/src/components/ui/inputs.tsx`:

```tsx
"use client";

import { FileUp, X } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useId,
  useState,
  type DragEvent,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
} from "react";

import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";

/** The inputs a form has besides a line of text: a choice, a tick, and files. */

export type Choice = { value: string; label: string };

/** One of several, as the browser's own list: it works with every keyboard and reader. */
export function SelectField({
  label,
  choices,
  className,
  ...select
}: Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> & { label: string; choices: Choice[] }) {
  const id = useId();
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="label-caps text-fg-muted">
        {label}
      </label>
      <select
        id={id}
        className="min-h-10 rounded-sm border border-line-strong bg-field px-3 py-2 text-fg hover:border-neon-cyan focus:shadow-glow-sm"
        {...select}
      >
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Yes or no, with what it means beside it. */
export function CheckboxField({
  label,
  hint,
  className,
  ...input
}: Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type"> & { label: string; hint?: string }) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <input
        id={id}
        type="checkbox"
        aria-describedby={hint ? hintId : undefined}
        className="mt-1 size-4 shrink-0 accent-primary"
        {...input}
      />
      <div className="min-w-0">
        <label htmlFor={id} className="text-fg">
          {label}
        </label>
        {hint ? (
          <p id={hintId} className="text-sm text-fg-subtle">
            {hint}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export type FilePickerProps = {
  label: string;
  hint?: string;
  error?: string | null;
  /** Several files, or one. With one, choosing again replaces it. */
  multiple?: boolean;
  /** What the browser's own dialog offers first: `.tgz`, `.whl,.tar.gz,.zip`. */
  accept?: string;
  files: File[];
  onChange: (files: File[]) => void;
};

/**
 * Files to send: chosen with the browser's own dialog, or dropped here. The input is the
 * real one, so the keyboard and a screen reader use it as any file input; what was
 * chosen is listed under it, each with a way to take it out again.
 */
export function FilePicker({
  label,
  hint,
  error,
  multiple = false,
  accept,
  files,
  onChange,
}: FilePickerProps) {
  const t = useTranslations("files");
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  const [over, setOver] = useState(false);

  function take(taken: FileList | null) {
    const added = Array.from(taken ?? []);
    if (added.length === 0) return;
    onChange(multiple ? [...files, ...added] : added.slice(0, 1));
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setOver(false);
    take(event.dataTransfer.files);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="label-caps text-fg-muted">
        {label}
      </label>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn(
          "flex flex-wrap items-center gap-3 rounded-sm border border-dashed bg-field px-4 py-4",
          "focus-within:shadow-glow-sm",
          error ? "border-bad" : over ? "border-neon-cyan bg-raised" : "border-line-strong",
        )}
      >
        <FileUp aria-hidden="true" className="size-6 shrink-0 text-neon-cyan" />
        <input
          id={id}
          type="file"
          multiple={multiple}
          accept={accept}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          // The same file can be chosen again after it was taken out. The input is so
          // always empty, and the browser's own "No file chosen" beside it would deny the
          // list below: its text is not shown, only its button.
          value=""
          onChange={(event) => take(event.target.files)}
          className="min-w-0 flex-1 text-sm text-transparent file:mr-3 file:rounded-sm file:border file:border-line-strong file:bg-panel file:px-3 file:py-1.5 file:text-fg"
        />
        <span className="text-sm text-fg-subtle">{t("orDrop")}</span>
      </div>
      {error ? (
        <p id={`${id}-error`} className="text-sm text-ink-bad">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-sm text-fg-subtle">
          {hint}
        </p>
      ) : null}
      {files.length > 0 ? (
        <ul aria-label={t("chosen", { label })} className="flex flex-col gap-1">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="flex items-center gap-2 rounded-sm bg-raised px-3 py-1.5 text-sm"
            >
              <span className="min-w-0 flex-1 font-mono break-all text-fg">{file.name}</span>
              <span className="shrink-0 text-fg-muted">{formatBytes(file.size)}</span>
              <button
                type="button"
                aria-label={t("remove", { name: file.name })}
                onClick={() => onChange(files.filter((_, at) => at !== index))}
                className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-fg-muted hover:text-ink-bad"
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
```

Create `frontend/src/components/ui/details.tsx`:

```tsx
"use client";

import type { Route } from "next";
import { useTranslations } from "next-intl";
import { useSyncExternalStore, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { exactTime, relativeTime } from "@/lib/format";

import { CopyButton } from "./copy-button";
import { AppLink } from "./link";

/** What is said of one thing: names and their values, a time, a piece of code, pages. */

/** A list of names and values, such as a file's size, type and checksums. */
export function Facts({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm", className)}>
      {children}
    </dl>
  );
}

/** One name and its value. With `copy`, the value can be copied: a checksum, an address. */
export function Fact({
  name,
  copy,
  mono = false,
  children,
}: {
  name: string;
  copy?: string;
  mono?: boolean;
  children: ReactNode;
}) {
  return (
    <>
      <dt className="label-caps pt-1 text-fg-subtle">{name}</dt>
      <dd className="flex min-w-0 items-start gap-1 text-fg">
        <span className={cn("min-w-0 flex-1 break-all", mono && "font-mono text-xs leading-6")}>
          {children}
        </span>
        {copy ? <CopyButton text={copy} what={name} className="-my-1" /> : null}
      </dd>
    </>
  );
}

// A minute is as fine as "3 minutes ago" gets.
function subscribe(tick: () => void): () => void {
  const timer = window.setInterval(tick, 60_000);
  return () => window.clearInterval(timer);
}
const minute = () => Math.floor(Date.now() / 60_000);

/**
 * A time, as a person reads it and as a log needs it: how long ago, with the exact time
 * in the reader's own zone on hover, and read out in place of the short form.
 */
export function Time({ value }: { value: string | null | undefined }) {
  const t = useTranslations("time");
  const now = useSyncExternalStore(subscribe, minute, () => 0);
  if (!value) return <span className="text-fg-subtle">{t("never")}</span>;
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return <span>{value}</span>;
  const exact = exactTime(moment);
  return (
    <time dateTime={value} title={exact}>
      <span aria-hidden="true">{relativeTime(moment, new Date(now * 60_000))}</span>
      <span className="sr-only">{exact}</span>
    </time>
  );
}

/** Text to copy and paste as it stands: a dependency, a command. */
export function Snippet({ label, text }: { label: string; text: string }) {
  return (
    <figure className="rounded-sm border border-line bg-field">
      <figcaption className="flex items-center justify-between gap-2 border-b border-line px-3 py-1">
        <span className="label-caps text-fg-muted">{label}</span>
        <CopyButton text={text} what={label} />
      </figcaption>
      {/* Reachable by keyboard, since it may scroll sideways. */}
      <pre
        tabIndex={0}
        aria-label={label}
        className="overflow-x-auto p-3 font-mono text-xs leading-5 text-fg"
      >
        {text}
      </pre>
    </figure>
  );
}

/** Numbered pages of a list that has a total: where one is, and the way on and back. */
export function Pager({
  page,
  pages,
  hrefFor,
}: {
  page: number;
  pages: number;
  hrefFor: (page: number) => Route;
}) {
  const t = useTranslations("pager");
  if (pages <= 1) return null;
  const link =
    "label-caps rounded-sm border border-line-strong px-3 py-1.5 text-fg hover:border-neon-cyan";
  const idle = "label-caps rounded-sm border border-line px-3 py-1.5 text-fg-subtle";
  return (
    <nav aria-label={t("label")} className="flex items-center justify-between gap-3 px-4 py-3">
      {page > 1 ? (
        <AppLink href={hrefFor(page - 1)} rel="prev" className={link}>
          {t("previous")}
        </AppLink>
      ) : (
        <span aria-disabled="true" className={idle}>
          {t("previous")}
        </span>
      )}
      <span aria-current="page" className="text-sm text-fg-muted">
        {t("position", { page, pages })}
      </span>
      {page < pages ? (
        <AppLink href={hrefFor(page + 1)} rel="next" className={link}>
          {t("next")}
        </AppLink>
      ) : (
        <span aria-disabled="true" className={idle}>
          {t("next")}
        </span>
      )}
    </nav>
  );
}

/** How much of something is done, as a bar and as words. */
export function Progress({ label, value, max }: { label: string; value: number; max: number }) {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const shown = new Intl.NumberFormat("en", { style: "percent" }).format(percent / 100);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between gap-3 text-sm text-fg-muted">
        <span>{label}</span>
        <span className="font-mono">{shown}</span>
      </div>
      <progress
        aria-label={label}
        value={value}
        max={max || 1}
        className="h-2 w-full overflow-hidden rounded-sm accent-primary"
      />
    </div>
  );
}
```

Change `frontend/src/app/providers.tsx`:

```diff
@@ -6,6 +6,7 @@ import { NextIntlClientProvider } from "next-intl";
 import type { ReactNode } from "react";
 
 import { ThemeProvider } from "@/components/theme-provider";
+import { NotificationsProvider } from "@/components/ui/notifications";
 import { createQueryClient } from "@/lib/query";
 
 import messages from "../../messages/en.json";
@@ -30,7 +31,9 @@ export function Providers({ nonce, children }: { nonce?: string; children: React
     // that the server and the browser would write a date the same way.
     <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
       <QueryClientProvider client={getClient()}>
-        <ThemeProvider>{children}</ThemeProvider>
+        <ThemeProvider>
+          <NotificationsProvider>{children}</NotificationsProvider>
+        </ThemeProvider>
       </QueryClientProvider>
     </NextIntlClientProvider>
   );
```

Change `frontend/src/test/render.tsx`:

```diff
@@ -4,6 +4,7 @@ import { NextIntlClientProvider } from "next-intl";
 import type { ReactElement } from "react";
 
 import { ThemeProvider } from "@/components/theme-provider";
+import { NotificationsProvider } from "@/components/ui/notifications";
 import type { SessionInfo } from "@/lib/api/types";
 import { createQueryClient } from "@/lib/query";
 import { SESSION_KEY } from "@/lib/session/session";
@@ -56,7 +57,9 @@ export function renderUi(ui: ReactElement, options: { session?: SessionInfo } =
   const result = render(
     <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
       <QueryClientProvider client={client}>
-        <ThemeProvider>{ui}</ThemeProvider>
+        <ThemeProvider>
+          <NotificationsProvider>{ui}</NotificationsProvider>
+        </ThemeProvider>
       </QueryClientProvider>
     </NextIntlClientProvider>,
   );
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 435 passed in 16 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding. The new lint rule finds nothing in the code of plan 9.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): the components of the browsing screens, and their texts"
```

---

### Task 3: Browsing a repository, and a component's page

**Files:**
- Create: `frontend/src/screens/browse.tsx`, `frontend/src/screens/component.tsx`
- Modify: `frontend/src/screens/not-found.tsx`, `frontend/src/screens/home.tsx`
- Test: `frontend/src/screens/browse.test.tsx`
- Test (modify): `frontend/src/screens/screens.test.tsx`

**Interfaces:**
- Consumes: everything Tasks 1 and 2 produce; `useSession` of plan 9; `usePathname`, `useSearchParams`, `useRouter` of `next/navigation` (mocked in tests by `src/test/setup.ts`, set with `navigation.at(address)`).
- Produces: `BrowseScreen()`, which reads `/browse/<repository>/<folders...>` and `?file=`; `ComponentScreen()`, which reads `/components/<repository>/<id>`; `NothingHere()` and `NotFoundScreen()` in `screens/not-found.tsx` (B7). The home screen's repository names are links to `browseHref(name)`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/browse.test.tsx`:

```tsx
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
    await expectAccessible();
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
    at(`/browse/releases/${VERSION}?file=app-1.0.jar`);
    const details = await screen.findByRole("region", { name: "Details of app-1.0.jar" });

    await user.click(await within(details).findByRole("button", { name: "Delete" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );

    expect(await within(details).findByRole("alert")).toHaveTextContent(
      "They go with its last version.",
    );
    expect(navigation.router.replace).not.toHaveBeenCalled();
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
```

Change `frontend/src/screens/screens.test.tsx`:

```diff
@@ -276,6 +276,10 @@ describe("the home screen", () => {
       "npmjs",
       "all",
     ]);
+    expect(within(rows[0] as HTMLElement).getByRole("link", { name: "releases" })).toHaveAttribute(
+      "href",
+      "/browse/releases",
+    );
     expect(rows[0]).toHaveTextContent("Hosted");
     expect(rows[0]).toHaveTextContent("Online");
     expect(rows[1]).toHaveTextContent("Proxy");
@@ -361,7 +365,11 @@ describe("an address with nothing at it", () => {
   test("says so, and leads home", async () => {
     renderUi(<NotFoundScreen />);
 
-    expect(screen.getByRole("heading", { name: "There is nothing at this address" })).toBeVisible();
+    // The page's one heading: a screen reader's list of headings starts with it.
+    expect(
+      screen.getByRole("heading", { level: 1, name: "There is nothing at this address" }),
+    ).toBeVisible();
+    expect(screen.getAllByRole("main")).toHaveLength(1);
     expect(screen.getByRole("link", { name: "Go to the repositories" })).toHaveAttribute(
       "href",
       "/",
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 2 tests fail and 1 file does not load. In `screens.test.tsx`: "lists the repositories a caller may browse" (the name is no link) and "says so, and leads home" (the heading is of level 2). `browse.test.tsx` fails with `Failed to resolve import "./component"`.

- [ ] **Step 3: Implement**

Change `frontend/src/screens/not-found.tsx`:

```diff
@@ -6,20 +6,29 @@ import { Button } from "@/components/ui/button";
 import { AppLink } from "@/components/ui/link";
 import { EmptyState } from "@/components/ui/states";
 
-export function NotFoundScreen() {
+/** What a screen of the shell shows at an address that is nothing's. */
+export function NothingHere() {
   const t = useTranslations("notFound");
+  return (
+    <EmptyState
+      page
+      title={t("title")}
+      action={
+        <Button asChild variant="primary">
+          <AppLink href="/">{t("home")}</AppLink>
+        </Button>
+      }
+    >
+      {t("body")}
+    </EmptyState>
+  );
+}
+
+/** The whole page for an address no route answers: it has no shell around it. */
+export function NotFoundScreen() {
   return (
     <main className="flex min-h-dvh items-center justify-center px-4">
-      <EmptyState
-        title={t("title")}
-        action={
-          <Button asChild variant="primary">
-            <AppLink href="/">{t("home")}</AppLink>
-          </Button>
-        }
-      >
-        {t("body")}
-      </EmptyState>
+      <NothingHere />
     </main>
   );
 }
```

Change `frontend/src/screens/home.tsx`:

```diff
@@ -5,11 +5,13 @@ import { useTranslations } from "next-intl";
 
 import { StatusTag } from "@/components/ui/alert";
 import { CopyButton } from "@/components/ui/copy-button";
+import { AppLink } from "@/components/ui/link";
 import { PageHeader, Panel } from "@/components/ui/panel";
 import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
 import { Table, Td, Th } from "@/components/ui/table";
 import { api } from "@/lib/api/client";
 import type { Page, RepositoryView } from "@/lib/api/types";
+import { browseHref } from "@/lib/paths";
 
 // As many as one request may ask for. An installation has tens of repositories.
 const AT_ONCE = 200;
@@ -27,7 +29,14 @@ function Rows({ repositories }: { repositories: RepositoryView[] }) {
     <tbody>
       {repositories.map((repository) => (
         <tr key={repository.name} className="hover:bg-raised">
-          <Td className="font-mono font-medium break-all">{repository.name}</Td>
+          <Td>
+            <AppLink
+              href={browseHref(repository.name)}
+              className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
+            >
+              {repository.name}
+            </AppLink>
+          </Td>
           <Td>{repository.format}</Td>
           <Td>{isKnownType(repository.type) ? t(`types.${repository.type}`) : repository.type}</Td>
           <Td>
```

Create `frontend/src/screens/browse.tsx`:

```tsx
"use client";

import { Download, File, Folder, Search, Trash2, Upload, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Breadcrumbs, type Crumb } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Time } from "@/components/ui/details";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { isApiError } from "@/lib/api/client";
import type { Entry, RepositoryView } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import {
  deleteFolder,
  forget,
  may,
  takesUploads,
  useAsset,
  useDeleteAsset,
  useFolder,
  useRepository,
  type FolderProgress,
} from "@/lib/content";
import { formatBytes } from "@/lib/format";
import {
  browseHref,
  componentHref,
  httpAddress,
  parentOf,
  parseBrowse,
  searchHref,
  split,
  uploadHref,
} from "@/lib/paths";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

const TYPES = ["hosted", "proxy", "group"] as const;

function useTypeName(): (type: string) => string {
  const t = useTranslations("home");
  return (type) =>
    (TYPES as readonly string[]).includes(type) ? t(`types.${type as "hosted"}`) : type;
}

/** A group holds nothing of its own: what it shows is who is behind it. */
function Members({ repository }: { repository: RepositoryView }) {
  const t = useTranslations("browse");
  const members = repository.members ?? [];
  return (
    <Panel className="p-6">
      <h2 className="mb-2 text-lg font-semibold text-fg uppercase">{t("membersTitle")}</h2>
      <p className="mb-4 text-fg-muted">{t("membersIntro")}</p>
      {members.length === 0 ? (
        <p className="text-fg-muted">{t("noMembers")}</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {members.map((member) => (
            <li key={member}>
              <AppLink
                href={browseHref(member)}
                className="font-mono text-ink-cyan underline-offset-4 hover:underline"
              >
                {member}
              </AppLink>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

function Entries({
  repository,
  folder,
  entries,
  chosen,
}: {
  repository: string;
  folder: string;
  entries: Entry[];
  chosen: string | null;
}) {
  const t = useTranslations("browse");
  return (
    <Table caption={t("entriesOf", { folder: folder || repository })}>
      <thead>
        <tr>
          <Th>{t("columns.name")}</Th>
          <Th className="text-right">{t("columns.size")}</Th>
          <Th>{t("columns.modified")}</Th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => {
          const isFolder = entry.kind === "folder";
          const current = !isFolder && entry.name === chosen;
          const Icon = isFolder ? Folder : File;
          return (
            // A name can be a file and a folder at once: the kind tells the two apart.
            <tr
              key={`${entry.kind}:${entry.name}`}
              className={cn("hover:bg-raised", current && "bg-raised")}
            >
              <Td>
                <AppLink
                  href={
                    isFolder
                      ? browseHref(repository, entry.path)
                      : browseHref(repository, folder, entry.name)
                  }
                  aria-label={t(isFolder ? "folderNamed" : "fileNamed", { name: entry.name })}
                  aria-current={current ? "true" : undefined}
                  scroll={false}
                  className={cn(
                    "flex items-center gap-2 rounded-sm font-mono break-all underline-offset-4 hover:underline",
                    current ? "text-ink-cyan" : "text-fg",
                  )}
                >
                  <Icon
                    aria-hidden="true"
                    className={cn("size-4 shrink-0", isFolder ? "text-neon-acid" : "text-fg-muted")}
                  />
                  {entry.name}
                </AppLink>
              </Td>
              <Td className="text-right font-mono whitespace-nowrap text-fg-muted">
                {entry.size === null || entry.size === undefined ? "" : formatBytes(entry.size)}
              </Td>
              <Td className="whitespace-nowrap text-fg-muted">
                {entry.modified ? <Time value={entry.modified} /> : null}
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

/** Everything the API says of one file, and what can be done with it. */
function FileDetails({
  repository,
  folder,
  name,
}: {
  repository: RepositoryView;
  folder: string;
  name: string;
}) {
  const t = useTranslations("browse");
  const router = useRouter();
  const notify = useNotify();
  const session = useSession();
  const path = folder ? `${folder}/${name}` : name;
  const asset = useAsset(repository.name, path);
  const remove = useDeleteAsset(repository.name);
  const [asking, setAsking] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);

  // Whoever chose the file by keyboard is taken to what they asked for.
  useEffect(() => heading.current?.focus(), [path]);

  const close = browseHref(repository.name, folder);
  const file = asset.data;
  const download = httpAddress(file?.download);
  return (
    <Panel role="region" aria-label={t("detailsOf", { name })} className="p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <h2
          ref={heading}
          tabIndex={-1}
          className="min-w-0 font-mono text-base font-semibold break-all text-fg outline-none"
        >
          {name}
        </h2>
        <AppLink
          href={close}
          scroll={false}
          aria-label={t("closeDetails")}
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-sm text-fg-muted hover:text-fg"
        >
          <X aria-hidden="true" className="size-4" />
        </AppLink>
      </div>
      {asset.isError ? (
        <ErrorState error={asset.error} onRetry={() => void asset.refetch()} />
      ) : !file ? (
        <LoadingState className="p-4" />
      ) : (
        <>
          <Facts>
            <Fact name={t("facts.path")} copy={file.path} mono>
              {file.path}
            </Fact>
            <Fact name={t("facts.size")}>{formatBytes(file.size)}</Fact>
            <Fact name={t("facts.type")}>{file.content_type}</Fact>
            <Fact name={t("facts.sha256")} copy={file.sha256} mono>
              {file.sha256}
            </Fact>
            <Fact name={t("facts.sha1")} copy={file.sha1} mono>
              {file.sha1}
            </Fact>
            <Fact name={t("facts.md5")} copy={file.md5} mono>
              {file.md5}
            </Fact>
            <Fact name={t("facts.sha512")} copy={file.sha512} mono>
              {file.sha512}
            </Fact>
            <Fact name={t("facts.blobStore")}>{file.blob_store}</Fact>
            <Fact name={t("facts.storedBy")}>{file.created_by}</Fact>
            <Fact name={t("facts.created")}>
              <Time value={file.created} />
            </Fact>
            <Fact name={t("facts.modified")}>
              <Time value={file.modified} />
            </Fact>
            <Fact name={t("facts.lastDownloaded")}>
              <Time value={file.last_downloaded} />
            </Fact>
            {file.component ? (
              <Fact name={t("facts.component")}>
                <AppLink
                  href={componentHref(repository.name, file.component.id)}
                  className="text-ink-cyan underline-offset-4 hover:underline"
                >
                  {[file.component.namespace, file.component.name, file.component.version]
                    .filter(Boolean)
                    .join(" : ")}
                </AppLink>
              </Fact>
            ) : null}
          </Facts>
          <div className="mt-5 flex flex-wrap gap-2">
            {download ? (
              <Button asChild variant="primary" size="sm">
                <a href={download}>
                  <Download aria-hidden="true" className="size-4" />
                  {t("download")}
                </a>
              </Button>
            ) : null}
            {may(session.data, repository, "delete") ? (
              <Button size="sm" onClick={() => setAsking(true)}>
                <Trash2 aria-hidden="true" className="size-4" />
                {t("delete")}
              </Button>
            ) : null}
          </div>
          {remove.isError ? <ErrorState error={remove.error} className="mt-4" /> : null}
          <ConfirmDialog
            open={asking}
            onOpenChange={setAsking}
            title={t("deleteFileTitle", { name })}
            confirmLabel={t("delete")}
            busy={remove.isPending}
            onConfirm={() =>
              remove.mutate(file.path, {
                onSuccess: () => {
                  notify(t("deleted", { name }));
                  router.replace(close, { scroll: false });
                },
                onSettled: () => setAsking(false),
              })
            }
          >
            {t("deleteFileBody")}
          </ConfirmDialog>
        </>
      )}
    </Panel>
  );
}

/** Deleting everything under a folder: asked for by name, done in pieces, and stoppable. */
function DeleteFolder({ repository, folder }: { repository: string; folder: string }) {
  const t = useTranslations("browse");
  const router = useRouter();
  const notify = useNotify();
  const client = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [progress, setProgress] = useState<FolderProgress | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const stop = useRef<AbortController | null>(null);
  const name = split(folder).name;

  async function run() {
    stop.current = new AbortController();
    setFailure(null);
    setProgress({ deleted: 0, skipped: 0 });
    try {
      const done = await deleteFolder(repository, folder, {
        onProgress: setProgress,
        signal: stop.current.signal,
      });
      await forget(client, repository);
      setAsking(false);
      notify(
        done.finished
          ? t("folderDeleted", { name, deleted: done.deleted, skipped: done.skipped })
          : t("folderStopped", { name, deleted: done.deleted }),
      );
      if (done.finished && done.skipped === 0) {
        router.replace(browseHref(repository, parentOf(folder) ?? ""));
      }
    } catch (error) {
      await forget(client, repository);
      setFailure(error);
    } finally {
      setProgress(null);
    }
  }

  return (
    <>
      <Button size="sm" onClick={() => setAsking(true)}>
        <Trash2 aria-hidden="true" className="size-4" />
        {t("deleteFolder")}
      </Button>
      <ConfirmDialog
        open={asking}
        onOpenChange={(open) => {
          if (!open) stop.current?.abort(); // closing it stops after the piece under way
          setAsking(open);
        }}
        title={t("deleteFolderTitle", { name })}
        confirmLabel={t("deleteFolder")}
        mustType={name}
        busy={progress !== null}
        onConfirm={() => void run()}
      >
        <p>{t("deleteFolderBody", { folder })}</p>
        {progress ? (
          <p role="status" className="mt-3 text-fg">
            {t("deletedSoFar", { deleted: progress.deleted })}
          </p>
        ) : null}
        {failure ? <ErrorState error={failure} className="mt-3" /> : null}
      </ConfirmDialog>
    </>
  );
}

function FolderView({
  repository,
  folder,
  file,
}: {
  repository: RepositoryView;
  folder: string;
  file: string | null;
}) {
  const t = useTranslations("browse");
  const session = useSession();
  const listing = useFolder(repository.name, folder);
  const entries = listing.data?.pages.flatMap((page) => page.items) ?? [];
  const uploads = takesUploads(session.data, repository);
  const missing = isApiError(listing.error) && listing.error.status === 404;

  return (
    <div
      className={cn(
        "grid items-start gap-6",
        file !== null && "lg:grid-cols-[minmax(0,1fr)_26rem]",
      )}
    >
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap gap-2">
          {uploads ? (
            <Button asChild size="sm">
              <AppLink href={uploadHref(repository.name, folder || undefined)}>
                <Upload aria-hidden="true" className="size-4" />
                {t("uploadHere")}
              </AppLink>
            </Button>
          ) : null}
          {folder !== "" && may(session.data, repository, "delete") && !missing ? (
            <DeleteFolder repository={repository.name} folder={folder} />
          ) : null}
        </div>
        {listing.isError ? (
          missing ? (
            <Panel>
              {/* Deleting the last file of a folder ends here: the folder went with it. */}
              <EmptyState
                title={t("noFolderTitle")}
                action={
                  <Button asChild>
                    <AppLink href={browseHref(repository.name)}>
                      {t("toTop", { repository: repository.name })}
                    </AppLink>
                  </Button>
                }
              >
                {t("noFolder", { folder })}
              </EmptyState>
            </Panel>
          ) : (
            <ErrorState error={listing.error} onRetry={() => void listing.refetch()} />
          )
        ) : listing.isPending ? (
          <Panel>
            <LoadingState />
          </Panel>
        ) : entries.length === 0 ? (
          <Panel>
            <EmptyState
              title={t("emptyTitle")}
              action={
                uploads ? (
                  <Button asChild variant="primary">
                    <AppLink href={uploadHref(repository.name)}>{t("uploadHere")}</AppLink>
                  </Button>
                ) : undefined
              }
            >
              {repository.type === "proxy" ? t("emptyProxy") : t("empty")}
            </EmptyState>
          </Panel>
        ) : (
          <Panel>
            <Entries repository={repository.name} folder={folder} entries={entries} chosen={file} />
            {listing.hasNextPage ? (
              <div className="p-3">
                <Button
                  size="sm"
                  busy={listing.isFetchingNextPage}
                  onClick={() => void listing.fetchNextPage()}
                >
                  {t("showMore")}
                </Button>
              </div>
            ) : null}
          </Panel>
        )}
      </div>
      {file !== null ? <FileDetails repository={repository} folder={folder} name={file} /> : null}
    </div>
  );
}

/**
 * A repository, one folder at a time: the way there as breadcrumbs, the folder's
 * entries, and beside them the details of a file that was chosen.
 */
export function BrowseScreen() {
  const t = useTranslations("browse");
  const typeName = useTypeName();
  const where = parseBrowse(usePathname());
  const file = useSearchParams().get("file");
  const repository = useRepository(where?.repository ?? "");

  if (where === null) return <NothingHere />;
  if (repository.isError) {
    return <ErrorState error={repository.error} onRetry={() => void repository.refetch()} />;
  }
  if (!repository.data) return <LoadingState />;

  const found = repository.data;
  const crumbs: Crumb[] = [{ name: found.name, href: browseHref(found.name) }];
  where.folder.split("/").forEach((segment, index, all) => {
    if (segment)
      crumbs.push({
        name: segment,
        href: browseHref(found.name, all.slice(0, index + 1).join("/")),
      });
  });

  return (
    <>
      <PageHeader
        named
        title={found.name}
        intro={t(found.type === "proxy" ? "kindProxy" : "kind", {
          format: found.format,
          type: typeName(found.type),
        })}
      >
        <Button asChild size="sm" variant="ghost">
          <AppLink href={searchHref({ repository: found.name })}>
            <Search aria-hidden="true" className="size-4" />
            {t("searchIn")}
          </AppLink>
        </Button>
      </PageHeader>
      {found.online ? null : (
        <Alert tone="warning" className="mb-4">
          {t("offline")}
        </Alert>
      )}
      <Breadcrumbs label={t("path")} crumbs={crumbs} />
      {found.type === "group" ? (
        <Members repository={found} />
      ) : (
        <FolderView repository={found} folder={where.folder} file={file} />
      )}
    </>
  );
}
```

Create `frontend/src/screens/component.tsx`:

```tsx
"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Snippet, Time } from "@/components/ui/details";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { may, useComponent, useDeleteComponent, useRepository } from "@/lib/content";
import { formatBytes } from "@/lib/format";
import { browseHref, componentHref, fileHref, parseComponent } from "@/lib/paths";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

/** A package version: what it is, its files, and how to use it from a build or a shell. */
export function ComponentScreen() {
  const t = useTranslations("component");
  const router = useRouter();
  const notify = useNotify();
  const session = useSession();
  const where = parseComponent(usePathname());
  const repository = useRepository(where?.repository ?? "");
  const component = useComponent(where?.repository ?? "", where?.id ?? null);
  const remove = useDeleteComponent(where?.repository ?? "");
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  const failed = repository.isError ? repository : component.isError ? component : null;
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  if (!repository.data || !component.data) return <LoadingState />;

  const found = component.data;
  const title = found.version ? `${found.name} ${found.version}` : found.name;
  return (
    <>
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: where.repository, href: browseHref(where.repository) },
          { name: title, href: componentHref(where.repository, found.id) },
        ]}
      />
      <PageHeader named title={title}>
        {may(session.data, repository.data, "delete") ? (
          <Button size="sm" onClick={() => setAsking(true)}>
            <Trash2 aria-hidden="true" className="size-4" />
            {t("delete")}
          </Button>
        ) : null}
      </PageHeader>
      {remove.isError ? <ErrorState error={remove.error} className="mb-4" /> : null}
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Panel className="p-5">
          <h2 className="mb-3 text-lg font-semibold text-fg uppercase">{t("about")}</h2>
          <Facts>
            <Fact name={t("facts.repository")}>
              <AppLink
                href={browseHref(where.repository)}
                className="font-mono text-ink-cyan underline-offset-4 hover:underline"
              >
                {where.repository}
              </AppLink>
            </Fact>
            <Fact name={t("facts.format")}>{repository.data.format}</Fact>
            {found.namespace ? (
              <Fact name={t("facts.namespace")} copy={found.namespace} mono>
                {found.namespace}
              </Fact>
            ) : null}
            <Fact name={t("facts.name")} copy={found.name} mono>
              {found.name}
            </Fact>
            {found.version ? (
              <Fact name={t("facts.version")} copy={found.version} mono>
                {found.version}
              </Fact>
            ) : null}
            <Fact name={t("facts.created")}>
              <Time value={found.created} />
            </Fact>
            <Fact name={t("facts.modified")}>
              <Time value={found.modified} />
            </Fact>
          </Facts>
        </Panel>
        <Panel className="p-5">
          <h2 className="mb-3 text-lg font-semibold text-fg uppercase">{t("usage")}</h2>
          {found.usage.length === 0 ? (
            <p className="text-fg-muted">{t("noUsage")}</p>
          ) : (
            <div className="flex flex-col gap-3">
              {found.usage.map((snippet) => (
                <Snippet key={snippet.label} label={snippet.label} text={snippet.text} />
              ))}
            </div>
          )}
        </Panel>
      </div>
      <Panel className="mt-6">
        <h2 className="px-4 pt-4 text-lg font-semibold text-fg uppercase">{t("files")}</h2>
        <Table caption={t("files")}>
          <thead>
            <tr>
              <Th>{t("columns.path")}</Th>
              <Th className="text-right">{t("columns.size")}</Th>
              <Th>{t("columns.modified")}</Th>
            </tr>
          </thead>
          <tbody>
            {found.files.map((file) => (
              <tr key={file.path} className="hover:bg-raised">
                <Td>
                  <AppLink
                    href={fileHref(where.repository, file.path)}
                    className="font-mono break-all text-fg underline-offset-4 hover:underline"
                  >
                    {file.path}
                  </AppLink>
                </Td>
                <Td className="text-right font-mono whitespace-nowrap text-fg-muted">
                  {file.size === null || file.size === undefined ? "" : formatBytes(file.size)}
                </Td>
                <Td className="whitespace-nowrap text-fg-muted">
                  {file.modified ? <Time value={file.modified} /> : null}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Panel>
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("deleteTitle", { name: title })}
        confirmLabel={t("delete")}
        busy={remove.isPending}
        onConfirm={() =>
          remove.mutate(found.id, {
            onSuccess: () => {
              notify(t("deleted", { name: title }));
              router.replace(browseHref(where.repository));
            },
            onSettled: () => setAsking(false),
          })
        }
      >
        {t("deleteBody", { count: found.files.length })}
      </ConfirmDialog>
    </>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 462 passed in 17 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): browsing a repository, and a component's page"
```

---

### Task 4: Search

**Files:**
- Create: `frontend/src/components/search-box.tsx`, `frontend/src/screens/search.tsx`
- Test: `frontend/src/screens/search.test.tsx`

**Interfaces:**
- Consumes: `useSearch`, `useRepositories`, `RESULTS_AT_ONCE`, `Wanted` of `lib/content.ts`; `readChecksum`; `searchHref`, `componentHref`, `browseHref`; `Pager`, `Time`, `SelectField`, `TextField`.
- Produces: `SearchScreen()`, which reads `q`, `format`, `repository`, `namespace`, `name`, `version`, `checksum` and `page` from the address and writes them there when the form is sent; `SearchBox({ className? })`, a `role="search"` form named "Search components" that takes the keyboard at `/` and sends to `/search?q=`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/search.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file does not load: `Failed to resolve import "./search" from "src/screens/search.test.tsx"`. The other 462 tests pass.

- [ ] **Step 3: Implement**

Create `frontend/src/components/search-box.tsx`:

```tsx
"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { cn } from "@/lib/cn";
import { searchHref } from "@/lib/paths";

const KEY = "/";

/** Whether a key press is someone typing into something, and so not a shortcut. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * Search, on every screen: finding a package is what most visitors come for. `/` takes
 * the keyboard here from anywhere that is not itself a place to type.
 */
export function SearchBox({ className }: { className?: string }) {
  const t = useTranslations("searchBox");
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== KEY || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTyping(event.target)) return;
      event.preventDefault();
      input.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    router.push(searchHref({ q: text.trim() }));
  }

  return (
    <form
      role="search"
      aria-label={t("label")}
      onSubmit={submit}
      className={cn("relative", className)}
    >
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle"
      />
      <input
        ref={input}
        type="search"
        name="q"
        aria-label={t("label")}
        aria-keyshortcuts={KEY}
        placeholder={t("placeholder")}
        value={text}
        onChange={(event) => setText(event.target.value)}
        className="min-h-10 w-full rounded-sm border border-line-strong bg-field py-2 pr-3 pl-9 text-sm text-fg placeholder:text-fg-subtle hover:border-neon-cyan focus:shadow-glow-sm"
      />
    </form>
  );
}
```

Create `frontend/src/screens/search.tsx`:

```tsx
"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Pager, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { RESULTS_AT_ONCE, useRepositories, useSearch, type Wanted } from "@/lib/content";
import { readChecksum } from "@/lib/format";
import { browseHref, componentHref, searchHref } from "@/lib/paths";

// What the address carries. A checksum is one field: its length says which it is.
const FIELDS = ["q", "format", "repository", "namespace", "name", "version", "checksum"] as const;
type Field = (typeof FIELDS)[number];
type Values = Record<Field, string>;

function valuesOf(search: URLSearchParams): Values {
  return Object.fromEntries(FIELDS.map((field) => [field, search.get(field) ?? ""])) as Values;
}

/** The API's parameters for what was typed, or null if the checksum is not one. */
function wantedOf(values: Values): Wanted | null {
  const wanted: Wanted = {};
  for (const field of ["q", "format", "repository", "namespace", "name", "version"] as const) {
    const value = values[field].trim();
    if (value) wanted[field] = value;
  }
  if (values.checksum.trim()) {
    const checksum = readChecksum(values.checksum);
    if (checksum === null) return null;
    wanted[checksum.kind] = checksum.value;
  }
  return wanted;
}

function Results({ wanted, page, values }: { wanted: Wanted; page: number; values: Values }) {
  const t = useTranslations("search");
  const results = useSearch(wanted, page);
  if (results.isError) {
    return <ErrorState error={results.error} onRetry={() => void results.refetch()} />;
  }
  if (!results.data) {
    return (
      <Panel>
        <LoadingState />
      </Panel>
    );
  }
  const { items, total } = results.data;
  if (total === 0) {
    return (
      <Panel>
        <EmptyState title={t("noneTitle")}>{t("none")}</EmptyState>
      </Panel>
    );
  }
  return (
    <Panel>
      <p role="status" className="px-4 pt-4 text-sm text-fg-muted">
        {t("found", { total })}
      </p>
      <Table caption={t("results")}>
        <thead>
          <tr>
            <Th>{t("columns.name")}</Th>
            <Th>{t("columns.namespace")}</Th>
            <Th>{t("columns.version")}</Th>
            <Th>{t("columns.repository")}</Th>
            <Th>{t("columns.format")}</Th>
            <Th>{t("columns.modified")}</Th>
          </tr>
        </thead>
        <tbody>
          {items.map((found) => (
            <tr key={`${found.repository}:${found.id}`} className="hover:bg-raised">
              <Td>
                <AppLink
                  href={componentHref(found.repository, found.id)}
                  className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                >
                  {found.name}
                </AppLink>
              </Td>
              <Td className="font-mono break-all text-fg-muted">{found.namespace}</Td>
              <Td className="font-mono break-all">{found.version}</Td>
              <Td>
                <AppLink
                  href={browseHref(found.repository)}
                  className="font-mono break-all underline-offset-4 hover:underline"
                >
                  {found.repository}
                </AppLink>
              </Td>
              <Td>{found.format}</Td>
              <Td className="whitespace-nowrap text-fg-muted">
                <Time value={found.modified} />
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <Pager
        page={page}
        pages={Math.ceil(total / RESULTS_AT_ONCE)}
        hrefFor={(target) =>
          searchHref({ ...values, page: target > 1 ? String(target) : undefined })
        }
      />
    </Panel>
  );
}

/**
 * Finding components. What is searched for is in the address, so a search can be
 * shared and the back button returns to the one before.
 */
export function SearchScreen() {
  const t = useTranslations("search");
  const router = useRouter();
  const search = useSearchParams();
  const asked = valuesOf(search);
  // The form starts from the address, and is its own until it is sent.
  const [values, setValues] = useState<Values>(asked);
  const [seen, setSeen] = useState(search.toString());
  if (seen !== search.toString()) {
    setSeen(search.toString());
    setValues(asked);
  }
  const repositories = useRepositories();
  const page = Math.max(1, Number.parseInt(search.get("page") ?? "1", 10) || 1);
  const wanted = wantedOf(asked);
  const typedChecksum = values.checksum.trim() !== "" && readChecksum(values.checksum) === null;

  const set = (field: Field) => (event: { target: { value: string } }) =>
    setValues((was) => ({ ...was, [field]: event.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (typedChecksum) return;
    router.push(
      searchHref(Object.fromEntries(FIELDS.map((field) => [field, values[field].trim()]))),
    );
  }

  const held = repositories.data?.items ?? [];
  const formats = Array.from(new Set(held.map((repository) => repository.format))).sort();
  const any = { value: "", label: t("any") };
  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="mb-6 p-5">
        <form
          role="search"
          aria-label={t("title")}
          onSubmit={submit}
          className="flex flex-col gap-4"
          noValidate
        >
          <TextField
            label={t("fields.q")}
            hint={t("hints.q")}
            type="search"
            value={values.q}
            onChange={set("q")}
          />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <SelectField
              label={t("fields.format")}
              value={values.format}
              onChange={set("format")}
              choices={[any, ...formats.map((format) => ({ value: format, label: format }))]}
            />
            <SelectField
              label={t("fields.repository")}
              value={values.repository}
              onChange={set("repository")}
              choices={[
                any,
                ...held
                  .filter((repository) => repository.type !== "group")
                  .map((repository) => ({ value: repository.name, label: repository.name })),
              ]}
            />
            <TextField
              label={t("fields.namespace")}
              value={values.namespace}
              onChange={set("namespace")}
            />
            <TextField label={t("fields.name")} value={values.name} onChange={set("name")} />
            <TextField
              label={t("fields.version")}
              value={values.version}
              onChange={set("version")}
            />
            <TextField
              label={t("fields.checksum")}
              hint={t("hints.checksum")}
              error={typedChecksum ? t("notAChecksum") : null}
              spellCheck={false}
              value={values.checksum}
              onChange={set("checksum")}
            />
          </div>
          <div>
            <Button type="submit" variant="primary">
              <Search aria-hidden="true" className="size-4" />
              {t("submit")}
            </Button>
          </div>
        </form>
      </Panel>
      {wanted === null ? (
        <Alert tone="warning">{t("notAChecksum")}</Alert>
      ) : (
        <Results wanted={wanted} page={page} values={asked} />
      )}
    </>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 477 passed in 18 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): search, on its screen and from every screen"
```

---

### Task 5: Upload

**Files:**
- Create: `frontend/src/screens/upload.tsx`
- Test: `frontend/src/screens/upload.test.tsx`

**Interfaces:**
- Consumes: `upload`, `Sent` of `lib/api/upload.ts`; `takesUploads`, `forget`, `useRepository`, `useRepositories`; `parseUpload`, `uploadHref`, `fileHref`, `browseHref`; `FilePicker`, `CheckboxField`, `TextField`, `Progress`, `Breadcrumbs`; `mockUploads` in tests.
- Produces: `UploadScreen()`, which reads `/upload/<repository>` and `?directory=` and sends one multipart form to `POST /content/<repository>/upload`, with the parts the API of plan 8c names (`file`, `directory`; `group`, `artifact`, `version`, `packaging`, `generate_pom`, `pom`, `file.<classifier>`; `tag`; `summary`, `requires_python`, `keywords`); `UploadChooserScreen()`, the hosted repositories the caller may add to.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/upload.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file does not load: `Failed to resolve import "./upload" from "src/screens/upload.test.tsx"`. The other 477 tests pass.

- [ ] **Step 3: Implement**

Create `frontend/src/screens/upload.tsx`:

```tsx
"use client";

import { Plus, Upload as UploadIcon, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useSearchParams } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { Alert } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckboxField, FilePicker } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import type { RepositoryView, Uploaded } from "@/lib/api/types";
import { upload, type Sent } from "@/lib/api/upload";
import { forget, takesUploads, useRepositories, useRepository } from "@/lib/content";
import { formatBytes } from "@/lib/format";
import { browseHref, fileHref, parseUpload, uploadHref } from "@/lib/paths";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

/** What the API refused, by the name of the field or the part it refused it at. */
type Refusals = Record<string, string>;

function refusalsOf(error: unknown): Refusals {
  if (!isApiError(error) || error.code !== "validation_error") return {};
  return Object.fromEntries(
    error.details.filter((detail) => detail.field).map((detail) => [detail.field, detail.message]),
  );
}

// The fields and parts the form has a place for. What the API refuses elsewhere is
// shown whole.
const PLACED = new Set([
  "directory",
  "group",
  "artifact",
  "version",
  "packaging",
  "tag",
  "summary",
  "requires_python",
  "keywords",
  "file",
  "pom",
]);

/** A form's own state: text fields by the API's names, and files by the part they go in. */
type Extra = { id: number; classifier: string; files: File[] };

/** The form of one format. It gives back the parts to send, or null if something is missing. */
function useUploadForm(repository: RepositoryView, directory: string) {
  const [fields, setFields] = useState<Record<string, string>>({
    directory,
    packaging: "jar",
    tag: "latest",
  });
  const [generatePom, setGeneratePom] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [pom, setPom] = useState<File[]>([]);
  const [extras, setExtras] = useState<Extra[]>([]);
  const nextId = useRef(1);

  const set = (name: string) => (event: { target: { value: string } }) =>
    setFields((was) => ({ ...was, [name]: event.target.value }));

  function body(): FormData {
    const form = new FormData();
    const put = (name: string) => {
      const value = (fields[name] ?? "").trim();
      if (value) form.append(name, value);
    };
    for (const file of files) form.append("file", file, file.name);
    switch (repository.format) {
      case "maven":
        ["group", "artifact", "version", "packaging"].forEach(put);
        form.append("generate_pom", generatePom ? "true" : "false");
        for (const file of pom) form.append("pom", file, file.name);
        for (const extra of extras) {
          for (const file of extra.files)
            form.append(`file.${extra.classifier.trim()}`, file, file.name);
        }
        break;
      case "npm":
        put("tag");
        break;
      case "pypi":
        ["summary", "requires_python", "keywords"].forEach(put);
        break;
      default:
        put("directory");
    }
    return form;
  }

  function reset() {
    setFiles([]);
    setPom([]);
    setExtras([]);
  }

  return {
    fields,
    set,
    generatePom,
    setGeneratePom,
    files,
    setFiles,
    pom,
    setPom,
    extras,
    addExtra: () =>
      setExtras((was) => [...was, { id: nextId.current++, classifier: "", files: [] }]),
    changeExtra: (id: number, change: Partial<Extra>) =>
      setExtras((was) => was.map((extra) => (extra.id === id ? { ...extra, ...change } : extra))),
    removeExtra: (id: number) => setExtras((was) => was.filter((extra) => extra.id !== id)),
    body,
    reset,
    size: [...files, ...pom, ...extras.flatMap((extra) => extra.files)].reduce(
      (sum, file) => sum + file.size,
      0,
    ),
    hasFile: files.length > 0 || pom.length > 0 || extras.some((extra) => extra.files.length > 0),
  };
}

function Stored({ repository, stored }: { repository: string; stored: Uploaded }) {
  const t = useTranslations("upload");
  return (
    <Alert tone="success" title={t("stored", { count: stored.files.length })}>
      <ul className="mt-1 flex flex-col gap-1">
        {stored.files.map((file) => (
          <li key={file.path}>
            <AppLink
              href={fileHref(repository, file.path)}
              className="font-mono break-all text-ink-cyan underline-offset-4 hover:underline"
            >
              {file.path}
            </AppLink>
          </li>
        ))}
      </ul>
    </Alert>
  );
}

function UploadForm({ repository, directory }: { repository: RepositoryView; directory: string }) {
  const t = useTranslations("upload");
  const client = useQueryClient();
  const form = useUploadForm(repository, directory);
  const [sent, setSent] = useState<Sent | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [stored, setStored] = useState<Uploaded | null>(null);
  const stop = useRef<AbortController | null>(null);
  const refused = refusalsOf(failure);
  // A refusal that names a field is shown at the field. Anything else is shown whole.
  const unplaced =
    failure !== null &&
    !Object.keys(refused).some((field) => PLACED.has(field) || field.startsWith("file."));

  async function submit(event: FormEvent) {
    event.preventDefault();
    stop.current = new AbortController();
    setFailure(null);
    setStored(null);
    setSent({ sent: 0, total: form.size });
    try {
      const done = await upload<Uploaded>(
        `/content/${encodeURIComponent(repository.name)}/upload`,
        form.body(),
        { onProgress: setSent, signal: stop.current.signal },
      );
      setStored(done);
      form.reset();
      await forget(client, repository.name);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setFailure(error);
    } finally {
      setSent(null);
    }
  }

  const { fields, set } = form;
  const maven = repository.format === "maven";
  return (
    <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
      {repository.format === "raw" ? (
        <TextField
          label={t("fields.directory")}
          hint={t("hints.directory")}
          spellCheck={false}
          value={fields.directory ?? ""}
          error={refused.directory}
          onChange={set("directory")}
        />
      ) : null}
      {maven ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <TextField
              label={t("fields.group")}
              spellCheck={false}
              required
              value={fields.group ?? ""}
              error={refused.group}
              onChange={set("group")}
            />
            <TextField
              label={t("fields.artifact")}
              spellCheck={false}
              required
              value={fields.artifact ?? ""}
              error={refused.artifact}
              onChange={set("artifact")}
            />
            <TextField
              label={t("fields.version")}
              spellCheck={false}
              required
              value={fields.version ?? ""}
              error={refused.version}
              onChange={set("version")}
            />
          </div>
          <TextField
            label={t("fields.packaging")}
            hint={t("hints.packaging")}
            spellCheck={false}
            value={fields.packaging ?? ""}
            error={refused.packaging}
            onChange={set("packaging")}
          />
        </>
      ) : null}
      <FilePicker
        label={
          maven
            ? t("fields.artifactFile")
            : t(repository.format === "npm" ? "fields.tarball" : "fields.files")
        }
        hint={t(`hints.files.${repository.format as "raw" | "maven" | "npm" | "pypi"}`)}
        multiple={repository.format === "raw" || repository.format === "pypi"}
        accept={
          repository.format === "npm"
            ? ".tgz,.tar.gz"
            : repository.format === "pypi"
              ? ".whl,.tar.gz,.zip"
              : undefined
        }
        files={form.files}
        error={refused.file}
        onChange={form.setFiles}
      />
      {maven ? (
        <>
          <FilePicker
            label={t("fields.pom")}
            hint={t("hints.pom")}
            accept=".pom,.xml"
            files={form.pom}
            error={refused.pom}
            onChange={form.setPom}
          />
          <CheckboxField
            label={t("fields.generatePom")}
            hint={t("hints.generatePom")}
            checked={form.generatePom}
            onChange={(event) => form.setGeneratePom(event.target.checked)}
          />
          {form.extras.map((extra) => (
            <fieldset
              key={extra.id}
              className="flex flex-col gap-3 rounded-sm border border-line p-4"
            >
              <legend className="label-caps px-1 text-fg-muted">{t("extraLegend")}</legend>
              <div className="flex items-end gap-3">
                <TextField
                  className="flex-1"
                  label={t("fields.classifier")}
                  hint={t("hints.classifier")}
                  spellCheck={false}
                  value={extra.classifier}
                  error={refused[`file.${extra.classifier.trim()}`]}
                  onChange={(event) =>
                    form.changeExtra(extra.id, { classifier: event.target.value })
                  }
                />
                <Button size="sm" variant="ghost" onClick={() => form.removeExtra(extra.id)}>
                  <X aria-hidden="true" className="size-4" />
                  {t("removeExtra")}
                </Button>
              </div>
              <FilePicker
                label={t("fields.extraFile")}
                files={extra.files}
                onChange={(files) => form.changeExtra(extra.id, { files })}
              />
            </fieldset>
          ))}
          <div>
            <Button size="sm" onClick={form.addExtra}>
              <Plus aria-hidden="true" className="size-4" />
              {t("addExtra")}
            </Button>
          </div>
        </>
      ) : null}
      {repository.format === "npm" ? (
        <TextField
          label={t("fields.tag")}
          hint={t("hints.tag")}
          spellCheck={false}
          value={fields.tag ?? ""}
          error={refused.tag}
          onChange={set("tag")}
        />
      ) : null}
      {repository.format === "pypi" ? (
        <div className="grid gap-4 sm:grid-cols-3">
          <TextField
            label={t("fields.summary")}
            value={fields.summary ?? ""}
            error={refused.summary}
            onChange={set("summary")}
          />
          <TextField
            label={t("fields.requiresPython")}
            hint={t("hints.requiresPython")}
            spellCheck={false}
            value={fields.requires_python ?? ""}
            error={refused.requires_python}
            onChange={set("requires_python")}
          />
          <TextField
            label={t("fields.keywords")}
            value={fields.keywords ?? ""}
            error={refused.keywords}
            onChange={set("keywords")}
          />
        </div>
      ) : null}
      {sent ? (
        <Progress
          label={t("sending", { sent: formatBytes(sent.sent), total: formatBytes(sent.total) })}
          value={sent.sent}
          max={sent.total}
        />
      ) : null}
      {unplaced ? <ErrorState error={failure} /> : null}
      {stored ? <Stored repository={repository.name} stored={stored} /> : null}
      <div className="flex flex-wrap gap-3">
        <Button type="submit" variant="primary" busy={sent !== null} disabled={!form.hasFile}>
          <UploadIcon aria-hidden="true" className="size-4" />
          {t("submit")}
        </Button>
        {sent ? <Button onClick={() => stop.current?.abort()}>{t("stop")}</Button> : null}
      </div>
    </form>
  );
}

/** Uploading to one repository, with the fields its format needs. */
export function UploadScreen() {
  const t = useTranslations("upload");
  const session = useSession();
  const where = parseUpload(usePathname());
  const directory = useSearchParams().get("directory") ?? "";
  const repository = useRepository(where?.repository ?? "");

  if (where === null) return <NothingHere />;
  if (repository.isError) {
    return <ErrorState error={repository.error} onRetry={() => void repository.refetch()} />;
  }
  if (!repository.data) return <LoadingState />;
  const found = repository.data;
  return (
    <div className="mx-auto max-w-3xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: found.name, href: browseHref(found.name) },
          { name: t("title"), href: uploadHref(found.name) },
        ]}
      />
      <PageHeader
        named
        title={t("titleTo", { repository: found.name })}
        intro={t(`intro.${found.format as "raw"}`)}
      />
      {takesUploads(session.data, found) ? (
        <Panel className="p-6">
          <UploadForm repository={found} directory={directory} />
        </Panel>
      ) : (
        <Alert tone="warning" title={t("notHereTitle")}>
          {t(
            found.type !== "hosted"
              ? "notHosted"
              : found.format === "docker"
                ? "notDocker"
                : "notAllowed",
          )}
        </Alert>
      )}
    </div>
  );
}

/** Where to upload to: the hosted repositories this caller may add to. */
export function UploadChooserScreen() {
  const t = useTranslations("upload");
  const session = useSession();
  const repositories = useRepositories();
  if (repositories.isError) {
    return <ErrorState error={repositories.error} onRetry={() => void repositories.refetch()} />;
  }
  const open = (repositories.data?.items ?? []).filter((repository) =>
    takesUploads(session.data, repository),
  );
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title={t("title")} intro={t("chooserIntro")} />
      <Panel>
        {!repositories.data ? (
          <LoadingState />
        ) : open.length === 0 ? (
          <EmptyState title={t("nowhereTitle")}>{t("nowhere")}</EmptyState>
        ) : (
          <ul className="flex flex-col">
            {open.map((repository) => (
              <li key={repository.name} className="border-b border-line last:border-b-0">
                <AppLink
                  href={uploadHref(repository.name)}
                  className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-raised"
                >
                  <span className="font-mono font-medium break-all text-ink-cyan">
                    {repository.name}
                  </span>
                  <span className="label-caps text-fg-muted">{repository.format}</span>
                </AppLink>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 494 passed in 19 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): upload, with the form each format needs"
```

---

### Task 6: The routes, the navigation and the search box in the shell

**Files:**
- Create: `frontend/src/app/(shell)/browse/[repository]/[[...path]]/page.tsx`, `frontend/src/app/(shell)/components/[repository]/[id]/page.tsx`, `frontend/src/app/(shell)/search/page.tsx`, `frontend/src/app/(shell)/upload/page.tsx`, `frontend/src/app/(shell)/upload/[repository]/page.tsx`
- Modify: `frontend/src/app/titles.ts`, `frontend/src/lib/navigation.ts`, `frontend/src/components/app-shell.tsx`
- Test (modify): `frontend/src/app/titles.test.ts`, `frontend/src/lib/navigation.test.ts`, `frontend/src/components/shell.test.tsx`

**Interfaces:**
- Consumes: the five screens of Tasks 3 to 5; `SearchBox`.
- Produces: the addresses `/browse/<repository>/<folders...>`, `/components/<repository>/<id>`, `/search`, `/upload`, `/upload/<repository>`, each with a title; `namedByRepository(wording?)` in `app/titles.ts`, which returns a route's `generateMetadata`; `NavItem.under`, the addresses that are part of an item; the navigation items `repositories`, `search`, `upload`.

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/app/titles.test.ts`:

```diff
@@ -1,7 +1,12 @@
 import { expect, test } from "vitest";
 
 import { metadata as password } from "./(shell)/account/password/page";
+import { generateMetadata as browse } from "./(shell)/browse/[repository]/[[...path]]/page";
+import { generateMetadata as component } from "./(shell)/components/[repository]/[id]/page";
 import { metadata as home } from "./(shell)/page";
+import { metadata as search } from "./(shell)/search/page";
+import { generateMetadata as uploadTo } from "./(shell)/upload/[repository]/page";
+import { metadata as upload } from "./(shell)/upload/page";
 import { metadata as signIn } from "./login/page";
 import { metadata as notFound } from "./not-found";
 import { TITLES } from "./titles";
@@ -9,14 +14,33 @@ import { TITLES } from "./titles";
 // Each route names its page (WCAG 2.4.2). Next.js writes the route's title again at
 // every navigation, so it is the route that has to say it, not the screen.
 test("each screen has a title of its own", () => {
-  expect([home.title, signIn.title, password.title, notFound.title]).toEqual([
+  expect([
+    home.title,
+    signIn.title,
+    password.title,
+    notFound.title,
+    search.title,
+    upload.title,
+  ]).toEqual([
     "Repositories",
     "Sign in",
     "Change password",
     "There is nothing at this address",
+    "Search",
+    "Upload",
   ]);
 });
 
+test("a screen about one repository is titled by it, as the address names it", async () => {
+  const at = (repository: string) => ({ params: Promise.resolve({ repository }) });
+
+  expect(await browse(at("releases"))).toEqual({ title: "releases" });
+  expect(await component(at("my%20files"))).toEqual({ title: "my files" });
+  expect(await uploadTo(at("releases"))).toEqual({ title: "Upload to releases" });
+  expect(await uploadTo(at("$&"))).toEqual({ title: "Upload to $&" });
+  expect(await browse(at("%E0%A4%A"))).toEqual({ title: "%E0%A4%A" }); // no address of ours
+});
+
 test("a title is the screen, then the product", () => {
   expect(TITLES).toEqual({ default: "MegooArti", template: "%s · MegooArti" });
 });
```

Change `frontend/src/lib/navigation.test.ts`:

```diff
@@ -71,6 +71,31 @@ describe("the navigation as it is", () => {
     }
     expect(NAVIGATION[0]?.items[0]).toMatchObject({ key: "repositories", href: "/", icon: Boxes });
   });
+
+  test("leads to the repositories, to search and to upload, whoever is asking", () => {
+    const [browse] = visible(NAVIGATION, NOBODY);
+
+    expect(browse?.items.map((entry) => [entry.key, entry.href])).toEqual([
+      ["repositories", "/"],
+      ["search", "/search"],
+      ["upload", "/upload"],
+    ]);
+  });
+
+  test("marks the repositories while one is browsed, and a component of one is shown", () => {
+    const current = (pathname: string) =>
+      NAVIGATION.flatMap((area) => area.items)
+        .filter((entry) => isCurrent(entry, pathname))
+        .map((entry) => entry.key);
+
+    expect(current("/")).toEqual(["repositories"]);
+    expect(current("/browse/releases/com/acme")).toEqual(["repositories"]);
+    expect(current("/components/releases/0190-c0")).toEqual(["repositories"]);
+    expect(current("/search")).toEqual(["search"]);
+    expect(current("/upload/releases")).toEqual(["upload"]);
+    expect(current("/browser")).toEqual([]); // an address that only begins the same
+    expect(current("/account/password")).toEqual([]);
+  });
 });
 
 describe("where the visitor is", () => {
```

Change `frontend/src/components/shell.test.tsx`:

```diff
@@ -47,6 +47,38 @@ describe("the shell", () => {
     await expectAccessible();
   });
 
+  test("leads to the repositories, to search and to upload", () => {
+    navigation.at("/browse/releases/com");
+    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
+    const [wide] = screen.getAllByRole("navigation", { name: "Main" });
+    const links = within(wide as HTMLElement).getAllByRole("link");
+
+    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
+      ["Repositories", "/"],
+      ["Search", "/search"],
+      ["Upload", "/upload"],
+    ]);
+    // Browsing a repository is being among the repositories.
+    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null, null]);
+  });
+
+  test("has the search box in its header, and in the navigation of a narrow window", async () => {
+    const user = userEvent.setup();
+    renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
+    const boxes = within(screen.getByRole("banner")).getAllByRole("search", {
+      name: "Search components",
+      hidden: true,
+    });
+
+    expect(boxes).toHaveLength(2); // one is shown, by the width of the window
+    expect(boxes[0]).toHaveClass("hidden", "md:block");
+    expect(boxes[1]).toHaveClass("md:hidden");
+    expect(boxes[1]?.closest("#narrow-navigation")).not.toBeNull();
+
+    await user.type(within(boxes[0] as HTMLElement).getByRole("searchbox"), "guava{Enter}");
+    expect(navigation.router.push).toHaveBeenCalledWith("/search?q=guava");
+  });
+
   test("shows no area that has nothing in it", () => {
     renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
 
@@ -86,6 +118,7 @@ describe("the shell", () => {
     );
 
     expect(screen.queryByRole("navigation")).toBeNull();
+    expect(screen.queryByRole("search")).toBeNull(); // nothing can be searched for yet
     expect(screen.queryByRole("button", { name: "Open the navigation" })).toBeNull();
     expect(screen.getByRole("button", { name: "Account of Ada Admin" })).toBeVisible();
   });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 4 tests fail and 1 file does not load. In `navigation.test.ts`: "leads to the repositories, to search and to upload, whoever is asking" and "marks the repositories while one is browsed, and a component of one is shown". In `shell.test.tsx`: "leads to the repositories, to search and to upload" and "has the search box in its header, and in the navigation of a narrow window". `titles.test.ts` fails with `Failed to resolve import "./(shell)/browse/[repository]/[[...path]]/page"`.

- [ ] **Step 3: Implement**

Change `frontend/src/app/titles.ts`:

```diff
@@ -1,3 +1,5 @@
+import type { Metadata } from "next";
+
 import messages from "../../messages/en.json";
 
 /** How a page is titled: the screen, then the product. A route gives the screen. */
@@ -5,3 +7,20 @@ export const TITLES = {
   default: messages.app.name,
   template: messages.app.title.replace("{screen}", "%s"),
 };
+
+/**
+ * The title of a screen about one repository: `wording` with the repository's name, as
+ * the address has it. A route exports what this returns as its `generateMetadata`.
+ */
+export function namedByRepository(wording = "{repository}") {
+  return async ({ params }: { params: Promise<{ repository: string }> }): Promise<Metadata> => {
+    const { repository } = await params;
+    let name = repository;
+    try {
+      name = decodeURIComponent(repository);
+    } catch {
+      // Not an address of ours: the screen says so.
+    }
+    return { title: wording.replace("{repository}", () => name) };
+  };
+}
```

Create `frontend/src/app/(shell)/browse/[repository]/[[...path]]/page.tsx`:

```tsx
import { namedByRepository } from "@/app/titles";
import { BrowseScreen } from "@/screens/browse";

export const generateMetadata = namedByRepository();

export default function Page() {
  return <BrowseScreen />;
}
```

Create `frontend/src/app/(shell)/components/[repository]/[id]/page.tsx`:

```tsx
import { namedByRepository } from "@/app/titles";
import { ComponentScreen } from "@/screens/component";

export const generateMetadata = namedByRepository();

export default function Page() {
  return <ComponentScreen />;
}
```

Create `frontend/src/app/(shell)/search/page.tsx`:

```tsx
import type { Metadata } from "next";

import { SearchScreen } from "@/screens/search";

import messages from "../../../../messages/en.json";

export const metadata: Metadata = { title: messages.search.title };

export default function Page() {
  return <SearchScreen />;
}
```

Create `frontend/src/app/(shell)/upload/page.tsx`:

```tsx
import type { Metadata } from "next";

import { UploadChooserScreen } from "@/screens/upload";

import messages from "../../../../messages/en.json";

export const metadata: Metadata = { title: messages.upload.title };

export default function Page() {
  return <UploadChooserScreen />;
}
```

Create `frontend/src/app/(shell)/upload/[repository]/page.tsx`:

```tsx
import { namedByRepository } from "@/app/titles";
import { UploadScreen } from "@/screens/upload";

import messages from "../../../../../messages/en.json";

export const generateMetadata = namedByRepository(messages.upload.titleTo);

export default function Page() {
  return <UploadScreen />;
}
```

Change `frontend/src/lib/navigation.ts`:

```diff
@@ -2,14 +2,14 @@
  * The navigation, as data. A screen is put into the navigation by adding an item here,
  * with the permission its API needs: the item is then shown only to those who hold it.
  */
-import { Boxes, type LucideIcon } from "lucide-react";
+import { Boxes, Search, Upload, type LucideIcon } from "lucide-react";
 import type { Route } from "next";
 
 import type { SessionInfo } from "@/lib/api/types";
 import { allows } from "@/lib/session/rules";
 
 export type AreaKey = "browse" | "administration";
-export type ItemKey = "repositories";
+export type ItemKey = "repositories" | "search" | "upload";
 
 export type NavItem = {
   /** Its name is the message `nav.items.<key>`. */
@@ -18,6 +18,8 @@ export type NavItem = {
   icon: LucideIcon;
   /** What a caller must hold to be shown it. Without one, everybody is. */
   permission?: string;
+  /** Other addresses that are part of it: the screens it leads to. */
+  under?: string[];
 };
 
 export type NavArea = {
@@ -26,9 +28,16 @@ export type NavArea = {
   items: NavItem[];
 };
 
-// Browsing first, then administration (UI-2). Plan 10 adds its screens to both.
+// Browsing first, then administration (UI-2).
 export const NAVIGATION: readonly NavArea[] = [
-  { key: "browse", items: [{ key: "repositories", href: "/", icon: Boxes }] },
+  {
+    key: "browse",
+    items: [
+      { key: "repositories", href: "/", icon: Boxes, under: ["/browse", "/components"] },
+      { key: "search", href: "/search", icon: Search },
+      { key: "upload", href: "/upload", icon: Upload },
+    ],
+  },
   { key: "administration", items: [] },
 ];
 
@@ -46,6 +55,7 @@ export function visible(areas: readonly NavArea[], session: SessionInfo): NavAre
 
 /** Whether an item is where the visitor is: its own address, or anything under it. */
 export function isCurrent(item: NavItem, pathname: string): boolean {
-  if (item.href === "/") return pathname === "/";
-  return pathname === item.href || pathname.startsWith(`${item.href}/`);
+  const within = (address: string) => pathname === address || pathname.startsWith(`${address}/`);
+  if ((item.under ?? []).some(within)) return true;
+  return item.href === "/" ? pathname === "/" : within(item.href);
 }
```

Change `frontend/src/components/app-shell.tsx`:

```diff
@@ -5,6 +5,7 @@ import { useTranslations } from "next-intl";
 import { usePathname } from "next/navigation";
 import { useState, type ReactNode } from "react";
 
+import { SearchBox } from "@/components/search-box";
 import { ThemeSwitch } from "@/components/theme-switch";
 import { AppLink } from "@/components/ui/link";
 import { UserMenu } from "@/components/user-menu";
@@ -97,6 +98,7 @@ export function AppShell({
             </nav>
           ) : null}
           <div className="ml-auto flex items-center gap-2">
+            {bare ? null : <SearchBox className="hidden w-56 md:block xl:w-72" />}
             <ThemeSwitch />
             <UserMenu session={session} />
             {areas.length > 0 ? (
@@ -122,8 +124,9 @@ export function AppShell({
             id="narrow-navigation"
             aria-label={t("mainNavigation")}
             hidden={!open}
-            className="border-t border-line px-4 py-4 lg:hidden"
+            className="flex flex-col gap-4 border-t border-line px-4 py-4 lg:hidden"
           >
+            <SearchBox className="md:hidden" />
             <Navigation areas={areas} onNavigate={() => setOpen(false)} />
           </nav>
         ) : null}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 499 passed in 19 files.

Run: `pnpm lint && pnpm typecheck`
Expected: no finding. `pnpm typecheck` runs `next typegen` first, which writes the types of the new routes: without it, `tsc` refuses `/search` and `/upload` as addresses.

Run: `pnpm build`
Expected: `Compiled successfully`, and the routes `/browse/[repository]/[[...path]]`, `/components/[repository]/[id]`, `/search`, `/upload` and `/upload/[repository]` in the list, each rendered for its request (`ƒ`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): the routes of the browsing screens, and search in the shell"
```

---

### Task 7: The screens in a real browser, and the documents

**Files:**
- Modify: `frontend/e2e/ui.spec.ts`, `backend/tests/test_ui_client.py`
- Modify: `README.md`, `docs/superpowers/specs/2026-10-12-frontend-design.md`

**Interfaces:**
- Consumes: the whole stack of `docker-compose.yml`, started by the `stack` fixture of `backend/tests/conftest.py` as the Compose project `megooarti-test`.
- Produces: 17 more browser tests, between "an address with nothing at it says so" and "signing out ends the session": 35 in all, of which the docker suite now expects at least 34 to be reported as passed.

- [ ] **Step 1: Write the browser tests**

The tests follow each other in one browser, as those of plan 9 do: each starts where the one before it ended. What an administrator sets up (a repository, anonymous access) is done through the API, whose screens come with later plans.

Change `frontend/e2e/ui.spec.ts`:

```diff
@@ -9,6 +9,11 @@ import { expect, test, type BrowserContext, type Page } from "@playwright/test";
 const INITIAL_PASSWORD = process.env.MEGOOARTI_INITIAL_PASSWORD ?? "";
 const PASSWORD = "chosen-in-the-browser-test";
 const REPOSITORY = "browser-test-files";
+const RELEASES = "browser-test-releases";
+const GROUP = "browser-test-all";
+// A name with what an address gives a meaning to: a space, a fragment, an escape.
+const ODD = "a b#c%.txt";
+const UPLOADS = "**/api/v1/content/*/upload";
 
 test.describe.configure({ mode: "serial" });
 
@@ -47,17 +52,35 @@ async function expectAccessible() {
   expect(found).toEqual([]);
 }
 
-/** The same check in each mode, leaving the page in the dark one. */
-async function expectAccessibleInBothModes() {
+/**
+ * The same check in each mode, leaving the page in the dark one. `ready` waits for
+ * what the screen fetches, so that it is the screen that is checked and not its loading.
+ */
+async function expectAccessibleInBothModes(ready: () => Promise<void> = async () => {}) {
   for (const mode of ["light", "dark"] as const) {
     await page.evaluate((chosen) => localStorage.setItem("megooarti-theme", chosen), mode);
     await page.reload();
     await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
+    await ready();
     expect(await shownMode()).toBe(mode);
     await expectAccessible();
   }
 }
 
+/** What an administrator sets up through the API: its screens come with plan 10c. */
+async function asAdministrator(method: "post" | "put", address: string, data: unknown) {
+  const session = await (await page.request.get("/api/v1/auth/session")).json();
+  const answer = await page.request[method](address, {
+    headers: { "X-CSRF-Token": session.csrf_token },
+    data,
+  });
+  expect(answer.ok(), `${method} ${address}: ${answer.status()}`).toBe(true);
+}
+
+const createRepository = (data: unknown) => asAdministrator("post", "/api/v1/repositories", data);
+const setAnonymousAccess = (enabled: boolean) =>
+  asAdministrator("put", "/api/v1/settings/anonymous-access", { enabled });
+
 async function signIn(password: string) {
   await page.getByLabel("User name").fill("admin");
   await page.getByLabel("Password").fill(password);
@@ -200,12 +223,7 @@ test("choosing a password leads on to the repositories, of which there are none
 });
 
 test("a repository made through the API is listed, and its address can be copied", async () => {
-  const session = await (await page.request.get("/api/v1/auth/session")).json();
-  const created = await page.request.post("/api/v1/repositories", {
-    headers: { "X-CSRF-Token": session.csrf_token },
-    data: { name: REPOSITORY, format: "raw", type: "hosted" },
-  });
-  expect(created.status()).toBe(201);
+  await createRepository({ name: REPOSITORY, format: "raw", type: "hosted" });
 
   await page.reload();
   const row = page.getByRole("row", { name: new RegExp(REPOSITORY) });
@@ -281,6 +299,360 @@ test("an address with nothing at it says so", async () => {
   await expect(page).toHaveURL(/\/$/);
 });
 
+test("a repository is entered from the list, and is empty to begin with", async () => {
+  await page.getByRole("link", { name: REPOSITORY, exact: true }).click();
+
+  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}$`));
+  const title = page.getByRole("heading", { level: 1, name: REPOSITORY });
+  await expect(title).toBeVisible();
+  // A name tells capitals from small letters: it is not put in capitals as other titles are.
+  await expect(title).toHaveCSS("text-transform", "none");
+  await expect(page).toHaveTitle(`${REPOSITORY} · MegooArti`);
+  await expect(page.getByRole("heading", { name: "Nothing here yet" })).toBeVisible();
+  // Browsing a repository is being among the repositories.
+  await expect(
+    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
+  ).toHaveAttribute("aria-current", "page");
+});
+
+test("files are uploaded through the UI, which shows them going and says what was stored", async () => {
+  await page.getByRole("link", { name: "Upload here" }).first().click();
+  await expect(page).toHaveURL(new RegExp(`/upload/${REPOSITORY}$`));
+  await expect(page).toHaveTitle(`Upload to ${REPOSITORY} · MegooArti`);
+  const send = page.getByRole("button", { name: "Upload" });
+  await expect(send).toBeDisabled(); // there is nothing to send yet
+
+  await page.getByLabel("Directory").fill("docs/v1");
+  await page.getByLabel("Files").setInputFiles([
+    { name: "guide.md", mimeType: "text/markdown", buffer: Buffer.from("# Guide\n") },
+    { name: ODD, mimeType: "text/plain", buffer: Buffer.from("odd name") },
+  ]);
+  // The answer is held back for a moment, so that what is shown meanwhile can be seen.
+  await page.route(UPLOADS, async (route) => {
+    await new Promise((resolve) => setTimeout(resolve, 1000));
+    await route.continue();
+  });
+  // The list under the field says what is chosen. The browser's own words beside its
+  // button ("No file chosen", always, as the field is emptied to take more) are not shown.
+  await expect(
+    page.getByRole("list", { name: "Chosen for Files" }).getByRole("listitem"),
+  ).toHaveCount(2);
+  await expect(page.getByLabel("Files")).toHaveCSS("color", "rgba(0, 0, 0, 0)");
+  await send.click();
+
+  await expect(page.getByRole("progressbar")).toBeVisible();
+  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
+  await expect(page.getByText("2 files stored")).toBeVisible();
+  await expect(page.getByRole("progressbar")).toHaveCount(0);
+  await page.unroute(UPLOADS);
+});
+
+test("a file with a name full of an address's own characters is found, and downloads as it was sent", async () => {
+  await page.getByRole("link", { name: `docs/v1/${ODD}` }).click();
+  const details = page.getByRole("region", { name: `Details of ${ODD}` });
+
+  await expect(details.getByText("text/plain")).toBeVisible();
+  await expect(details.getByText("8 B")).toBeVisible();
+  expect(new URL(page.url()).pathname).toBe(`/browse/${REPOSITORY}/docs/v1`);
+  expect(new URL(page.url()).searchParams.get("file")).toBe(ODD);
+  // The folder is still there beside it, with the file marked.
+  await expect(page.getByRole("link", { name: `File ${ODD}` })).toHaveAttribute(
+    "aria-current",
+    "true",
+  );
+
+  const address = await details.getByRole("link", { name: "Download" }).getAttribute("href");
+  const downloaded = await page.request.get(address ?? "");
+  expect(await downloaded.text()).toBe("odd name");
+
+  await details.getByRole("button", { name: "Copy SHA-256" }).click();
+  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^[0-9a-f]{64}$/);
+});
+
+test("a folder is reached through the ones above it by keyboard, and the path leads back", async () => {
+  await page.goto(`/browse/${REPOSITORY}`);
+  await page.getByRole("link", { name: "Folder docs" }).focus();
+  await page.keyboard.press("Enter");
+  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}/docs$`));
+  await page.getByRole("link", { name: "Folder v1" }).focus();
+  await page.keyboard.press("Enter");
+
+  await expect(
+    page.getByRole("table", { name: "What is in docs/v1" }).getByRole("row"),
+  ).toHaveCount(3);
+  await page.getByRole("link", { name: "File guide.md" }).focus();
+  await page.keyboard.press("Enter");
+  const details = page.getByRole("region", { name: "Details of guide.md" });
+  // The keyboard is taken to what was asked for.
+  await expect(details.getByRole("heading", { name: "guide.md" })).toBeFocused();
+  await expect(details.getByText("text/markdown")).toBeVisible();
+
+  // The back button closes the details: the file that is chosen is in the address.
+  await page.goBack();
+  await expect(details).toHaveCount(0);
+  await page.getByRole("navigation", { name: "Path" }).getByRole("link", { name: "docs" }).click();
+  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}/docs$`));
+  await expect(page.getByRole("link", { name: "Folder v1" })).toBeVisible();
+});
+
+test("the browse screen meets WCAG 2.1 AA in both modes", async () => {
+  await page.goto(`/browse/${REPOSITORY}/docs/v1?file=guide.md`);
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByText("text/markdown")).toBeVisible();
+  });
+});
+
+test("the upload screen meets WCAG 2.1 AA in both modes", async () => {
+  await createRepository({ name: RELEASES, format: "maven", type: "hosted" });
+  await page.goto(`/upload/${RELEASES}`);
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByLabel("Artifact", { exact: true })).toBeAttached();
+  });
+});
+
+test("a Maven upload that is refused says why at its field, and goes through once it is put right", async () => {
+  await page.getByLabel("Group", { exact: true }).fill("com.acme");
+  await page.getByLabel("Artifact name").fill("app");
+  await page.getByLabel("Version", { exact: true }).fill("2.0-SNAPSHOT");
+  await page.getByLabel("Artifact", { exact: true }).setInputFiles({
+    name: "build-output.jar",
+    mimeType: "application/java-archive",
+    buffer: Buffer.from("PK jar"),
+  });
+  await page.getByRole("button", { name: "Add another file" }).click();
+  await page.getByLabel("Classifier").fill("sources");
+  await page.getByLabel("File", { exact: true }).setInputFiles({
+    name: "s.jar",
+    mimeType: "application/java-archive",
+    buffer: Buffer.from("PK sources"),
+  });
+  await page.getByRole("button", { name: "Upload" }).click();
+
+  const version = page.getByLabel("Version", { exact: true });
+  await expect(version).toHaveAttribute("aria-invalid", "true");
+  await expect(page.getByText("A snapshot is deployed by a build")).toBeVisible();
+
+  // What was chosen is still chosen: only the version is typed again.
+  await version.fill("1.0");
+  await page.getByRole("button", { name: "Upload" }).click();
+
+  await expect(page.getByText("3 files stored")).toBeVisible();
+  for (const stored of ["app-1.0.jar", "app-1.0-sources.jar", "app-1.0.pom"]) {
+    await expect(page.getByRole("link", { name: `com/acme/app/1.0/${stored}` })).toBeVisible();
+  }
+});
+
+test("a component's page says what it is and how to use it, ready to copy", async () => {
+  await page.getByRole("link", { name: "com/acme/app/1.0/app-1.0.jar" }).click();
+  const details = page.getByRole("region", { name: "Details of app-1.0.jar" });
+  await details.getByRole("link", { name: "com.acme : app : 1.0" }).click();
+
+  await expect(page.getByRole("heading", { level: 1, name: "app 1.0" })).toBeVisible();
+  await expect(page).toHaveTitle(`${RELEASES} · MegooArti`);
+  await expect(page.getByRole("table", { name: "Files" }).getByRole("row")).toHaveCount(4);
+  await expect(page.getByText('implementation("com.acme:app:1.0")')).toBeVisible();
+
+  await page.getByRole("button", { name: "Copy Maven" }).click();
+  const copied = await page.evaluate(() => navigator.clipboard.readText());
+  expect(copied).toContain("<groupId>com.acme</groupId>");
+  expect(copied).toContain("<artifactId>app</artifactId>");
+  expect(copied).toContain("<version>1.0</version>");
+});
+
+test("the component screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByText('implementation("com.acme:app:1.0")')).toBeVisible();
+  });
+});
+
+test("search is one key away on every screen, and finds by words and by a file's checksum", async () => {
+  await page.goto("/");
+  await expect(page.getByRole("heading", { level: 1, name: "Repositories" })).toBeVisible();
+  await page.keyboard.press("/");
+  await expect(page.getByRole("searchbox", { name: "Search components" })).toBeFocused();
+  await page.keyboard.type("app");
+  await page.keyboard.press("Enter");
+
+  await expect(page).toHaveURL(/\/search\?q=app$/);
+  await expect(page).toHaveTitle("Search · MegooArti");
+  await expect(page.getByText("1 component found.")).toBeVisible();
+  const results = page.getByRole("table", { name: "Results" });
+  await expect(results.getByRole("row").nth(1)).toContainText("com.acme");
+
+  // A checksum, of any of the four kinds, is one field: here the SHA-1 of the jar.
+  const asset = await page.request.get(
+    `/api/v1/content/${RELEASES}/asset?path=com/acme/app/1.0/app-1.0.jar`,
+  );
+  const { sha1 } = await asset.json();
+  const form = page.getByRole("search", { name: "Search", exact: true });
+  await form.getByLabel("Words").fill("");
+  await form.getByLabel("Checksum of a file").fill(sha1);
+  await form.getByRole("button", { name: "Search" }).click();
+  await expect(page).toHaveURL(new RegExp(`/search\\?checksum=${sha1}$`));
+  await expect(results.getByRole("link", { name: "app", exact: true })).toBeVisible();
+
+  await form.getByLabel("Checksum of a file").fill("");
+  await form.getByLabel("Words").fill("no-such-thing-anywhere");
+  await form.getByLabel("Words").press("Enter");
+  await expect(page.getByRole("heading", { name: "Nothing found" })).toBeVisible();
+
+  // What was searched for is in the address: the back button returns to the search before.
+  await page.goBack();
+  await expect(form.getByLabel("Checksum of a file")).toHaveValue(sha1);
+  await results.getByRole("link", { name: "app", exact: true }).click();
+  await expect(page.getByRole("heading", { level: 1, name: "app 1.0" })).toBeVisible();
+});
+
+test("the search screen meets WCAG 2.1 AA in both modes", async () => {
+  await page.goto("/search?q=app");
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByText("1 component found.")).toBeVisible();
+  });
+});
+
+test("on a narrow screen a file's details come under its folder, and nothing overflows", async () => {
+  await page.setViewportSize({ width: 375, height: 700 });
+  await page.goto(`/browse/${RELEASES}/com/acme/app/1.0?file=app-1.0-sources.jar`);
+  const details = page.getByRole("region", { name: "Details of app-1.0-sources.jar" });
+  await expect(details.getByText("application/java-archive")).toBeVisible();
+
+  const table = page.getByRole("table", { name: "What is in com/acme/app/1.0" });
+  const [above, below] = [await table.boundingBox(), await details.boundingBox()];
+  expect(below?.y ?? 0).toBeGreaterThan((above?.y ?? 0) + (above?.height ?? 0) - 1);
+  // A checksum is 128 characters without a space in it: it breaks, and widens nothing.
+  const overflow = await page.evaluate(
+    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
+  );
+  expect(overflow).toBeLessThanOrEqual(0);
+
+  // The search box is in the navigation, where there is room for it.
+  await expect(page.getByRole("searchbox", { name: "Search components" })).toHaveCount(0);
+  await page.getByRole("button", { name: "Open the navigation" }).click();
+  await expect(page.getByRole("searchbox", { name: "Search components" })).toBeVisible();
+  await page.getByRole("button", { name: "Close the navigation" }).click();
+  await page.setViewportSize({ width: 1280, height: 720 });
+});
+
+test("a visitor who may only look is offered a download, and nothing that changes anything", async ({
+  browser,
+  baseURL,
+}) => {
+  await setAnonymousAccess(true);
+  const fresh = await browser.newContext({ baseURL, colorScheme: "dark" });
+  const visitor = await fresh.newPage();
+  await visitor.goto(`/browse/${REPOSITORY}/docs/v1?file=guide.md`);
+  const details = visitor.getByRole("region", { name: "Details of guide.md" });
+
+  await expect(details.getByText("text/markdown")).toBeVisible();
+  await expect(details.getByRole("link", { name: "Download" })).toBeVisible();
+  await expect(details.getByRole("button", { name: "Delete" })).toHaveCount(0);
+  await expect(visitor.getByRole("button", { name: "Delete folder" })).toHaveCount(0);
+  await expect(visitor.getByRole("link", { name: "Upload here" })).toHaveCount(0);
+  await expect(visitor.getByRole("link", { name: "Sign in" })).toBeVisible();
+
+  // The address of the form can be typed all the same. The screen says no, as the API would.
+  await visitor.goto(`/upload/${REPOSITORY}`);
+  await expect(
+    visitor.getByText("You do not have permission to add to this repository."),
+  ).toBeVisible();
+  await expect(visitor.getByRole("button", { name: "Upload" })).toHaveCount(0);
+  await visitor.goto("/upload");
+  await expect(visitor.getByRole("heading", { name: "Nowhere to upload to" })).toBeVisible();
+
+  await setAnonymousAccess(false);
+  await visitor.goto(`/browse/${REPOSITORY}`);
+  await expect(visitor).toHaveURL(/\/login\?next=/);
+  await fresh.close();
+});
+
+test("a group shows who is behind it, and takes no upload", async () => {
+  await createRepository({
+    name: GROUP,
+    format: "raw",
+    type: "group",
+    group: { members: [REPOSITORY] },
+  });
+  await page.goto(`/browse/${GROUP}`);
+
+  await expect(page.getByRole("heading", { name: "Members" })).toBeVisible();
+  await expect(page.getByRole("link", { name: "Upload here" })).toHaveCount(0);
+  await page.goto(`/upload/${GROUP}`);
+  await expect(page.getByText("Only a hosted repository takes an upload.")).toBeVisible();
+
+  await page.goto(`/browse/${GROUP}`);
+  await page.getByRole("main").getByRole("link", { name: REPOSITORY, exact: true }).click();
+  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}$`));
+  await expect(page.getByRole("link", { name: "Folder docs" })).toBeVisible();
+});
+
+test("a file is deleted only after asking, and the screen says that it is gone", async () => {
+  await page.goto(`/browse/${REPOSITORY}/docs/v1?file=guide.md`);
+  const details = page.getByRole("region", { name: "Details of guide.md" });
+  const opener = details.getByRole("button", { name: "Delete" });
+  await opener.click();
+  const dialog = page.getByRole("alertdialog", { name: "Delete guide.md?" });
+
+  // Asked, and answered no: nothing happens, and the keyboard is back where it was.
+  await dialog.getByRole("button", { name: "Cancel" }).click();
+  await expect(dialog).toHaveCount(0);
+  await expect(opener).toBeFocused();
+  await expect(page.getByRole("link", { name: "File guide.md" })).toBeVisible();
+
+  await opener.click();
+  await dialog.getByRole("button", { name: "Delete" }).click();
+
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    "Deleted guide.md.",
+  );
+  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}/docs/v1$`));
+  await expect(page.getByRole("link", { name: "File guide.md" })).toHaveCount(0);
+  await expect(page.getByRole("link", { name: `File ${ODD}` })).toBeVisible();
+});
+
+test("a folder is deleted only by whoever types its name", async () => {
+  await page.getByRole("button", { name: "Delete folder" }).click();
+  const dialog = page.getByRole("alertdialog", { name: "Delete the folder v1?" });
+  const confirm = dialog.getByRole("button", { name: "Delete folder" });
+
+  await expect(dialog).toContainText("Every file under docs/v1 is deleted.");
+  await expect(confirm).toBeDisabled();
+  // What is to be typed is shown as it is to be typed.
+  await expect(dialog.getByText("Type v1 to go on")).toHaveCSS("text-transform", "none");
+  await expect(dialog.getByRole("heading")).toHaveCSS("text-transform", "none");
+  await dialog.getByLabel("Type v1 to go on").fill("V1");
+  await expect(confirm).toBeDisabled();
+  await dialog.getByLabel("Type v1 to go on").fill("v1");
+  await confirm.click();
+
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    "Deleted 1 file under v1.",
+  );
+  // The folder above held nothing else, so it went too: the screen says so, and leads on.
+  await expect(page).toHaveURL(new RegExp(`/browse/${REPOSITORY}/docs$`));
+  await expect(page.getByRole("heading", { name: "No such folder" })).toBeVisible();
+  await page.getByRole("link", { name: `Go to the top of ${REPOSITORY}` }).click();
+  await expect(page.getByRole("heading", { name: "Nothing here yet" })).toBeVisible();
+});
+
+test("a version is deleted from its page, and is then not found", async () => {
+  await page.goto("/search?q=app");
+  await page
+    .getByRole("table", { name: "Results" })
+    .getByRole("link", { name: "app", exact: true })
+    .click();
+  await page.getByRole("button", { name: "Delete this version" }).click();
+  const dialog = page.getByRole("alertdialog", { name: "Delete app 1.0?" });
+  await expect(dialog).toContainText("Its 3 files are deleted");
+  await dialog.getByRole("button", { name: "Delete this version" }).click();
+
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    "Deleted app 1.0.",
+  );
+  await expect(page).toHaveURL(new RegExp(`/browse/${RELEASES}$`));
+  await page.goto("/search?q=app");
+  await expect(page.getByRole("heading", { name: "Nothing found" })).toBeVisible();
+});
+
 test("signing out ends the session, and signing in again returns to where one was going", async () => {
   await page.getByRole("button", { name: /^Account of/ }).click();
   await page.getByRole("menuitem", { name: "Sign out" }).click();
@@ -330,10 +702,11 @@ test("through all of it, nothing was asked of another host, and the browser had
 
   expect(requested.length).toBeGreaterThan(50);
   expect(elsewhere).toEqual([]);
-  // The two complaints there should be: the browser itself logs the sign-in that was
-  // refused (401) and the address that had nothing at it (404). Anything else, such as
-  // something the content security policy stopped, fails this.
-  const unexpected = complaints.filter((text) => !/status of 40[14]/.test(text));
+  // The complaints there should be: the browser itself logs the sign-in that was refused
+  // (401), the address and the folder that had nothing at them (404), and the upload that
+  // was refused (422). Anything else, such as something the content security policy
+  // stopped, fails this.
+  const unexpected = complaints.filter((text) => !/status of (401|404|422)/.test(text));
   // In particular not of the site the return paths named. (Its name is in the query of
   // addresses that were asked for, which is as far as it got.)
   expect(requested.filter((address) => new URL(address).hostname.includes("evil"))).toEqual([]);
```

Change `backend/tests/test_ui_client.py`:

```diff
@@ -98,7 +98,7 @@ def test_the_ui_in_a_real_browser(stack):
     said = f"exit {result.returncode}\n{result.stdout[-6000:]}\n{result.stderr[-2000:]}"
     assert result.returncode == 0, said
     passed = re.search(r"(\d+) passed", result.stdout)
-    assert passed is not None and int(passed[1]) >= 17, said
+    assert passed is not None and int(passed[1]) >= 34, said
     assert not re.search(r"\d+ (failed|skipped|did not run)", result.stdout), said
 
 
```

- [ ] **Step 2: Run them**

Run (in `backend/`): `uv run pytest -m docker tests/test_ui_client.py -q`
Expected: 11 passed. It builds the images, starts a fresh stack and runs Playwright against it; this takes a few minutes. Should the browser test fail, what Playwright said is in the failure.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e backend/tests/test_ui_client.py
git commit -m "test(frontend): browsing, search, upload and delete in a real browser"
```

- [ ] **Step 4: Bring the documents up to date**

Change `README.md`:

```diff
@@ -863,11 +863,36 @@ curl -u alice 'https://repo.example.com/api/v1/search?sha1=2ef7bde608ce5404e97d5
 
 ## The web UI
 
-The UI is at the root of the installation's address. For now it has the foundation
-every screen will stand on, and three screens: signing in, changing your password,
-and the repositories you may browse. Browsing, search, upload and administration
-follow.
-
+The UI is at the root of the installation's address. It has what a person who uses
+the repositories needs: browsing them, search, upload and delete. Administration
+(users, roles, repositories, blob stores) is done through the API for now, and its
+screens follow.
+
+- **Browsing.** A repository opens one folder at a time, with the way there as a path
+  above it. Choosing a file shows everything known of it beside the folder: its size,
+  type and four checksums (each with a button that copies it), who stored it and when,
+  and a download link. Every folder and file has an address of its own, so a link to
+  one can be shared. A group lists its members. A proxy shows what has been fetched
+  through it so far.
+- **A component's page** says what a package version is, lists its files, and gives
+  what to paste into a build or a shell to use it (for Maven, the dependency for
+  Maven and for Gradle), each with a copy button.
+- **Search** is a box in the header of every screen: press `/` to reach it. The
+  results page filters by format, repository, group, name and version, and by a
+  file's checksum: paste an MD5, SHA-1, SHA-256 or SHA-512, and its length says which
+  it is. A search is in the address, so it can be shared and gone back to.
+- **Upload** is offered for a hosted Raw, Maven, npm or PyPI repository to whoever
+  may add to it, from the repository ("Upload here") and from the navigation. The
+  form has the fields the format needs. Files are chosen or dropped onto it. It shows
+  how much has been sent, and can be stopped. What the server refuses is said at the
+  field it is about. A Docker image is pushed with a container client.
+- **Delete** is offered to whoever may delete in the repository. A file or one
+  version is deleted after a question. A folder is deleted, with everything under
+  it, only after its name is typed. Each is removed as the format's own client would
+  remove it, so the indexes stay right.
+- **What you may not do is not offered.** Without the permission to add there is no
+  upload, without the permission to delete no delete. The server decides in every
+  case: the screens only leave out what it would refuse.
 - **Signing in** uses the session cookie the API sets. It is marked `Secure`, so a
   browser keeps it over HTTPS, and over plain HTTP only on the machine itself
   (`localhost`). If you reach the UI over plain HTTP at another name or address,
@@ -1011,13 +1036,16 @@ at port 3000, without an API beside it.
 - **Tests in a real browser** are in `frontend/e2e/`. They are run by
   `uv run pytest -m docker` in `backend/`, which starts a fresh stack for them: they
   begin with the first sign-in of a new installation. They sign in, change the
-  password, use every screen by keyboard, check each screen against WCAG 2.1 AA in
-  both modes, and fail if the browser asked anything of another host or reported a
-  violation of the content security policy.
+  password, upload through the forms, browse, search and delete, use every screen by
+  keyboard, check each screen against WCAG 2.1 AA in both modes, and fail if the
+  browser asked anything of another host or reported a violation of the content
+  security policy.
 - **A colour is written in one file**, `src/styles/tokens.css`, once for each mode. A
   test fails on a colour anywhere else, and another computes the contrast of every
   text tone on every surface.
-- **Text is in `messages/en.json`.** ESLint refuses text written into markup.
+- **Text is in `messages/en.json`.** ESLint refuses text written into markup, or into
+  a property that is read out (`aria-label`, `title`, `alt`, `placeholder`, and the
+  `label` and `hint` of the UI's own fields).
 - **The API's types are generated.** `frontend/openapi.json` is a copy of the
   backend's API document, and a backend test fails when it is out of date. After a
   change to the API:
```

Change `docs/superpowers/specs/2026-10-12-frontend-design.md`:

```diff
@@ -234,10 +234,24 @@ Delivered as three plans.
 
 - **A folder's entries** are folders and files in the order the API gives them. A file shows its size and when it changed.
 - **A file's details** are everything the API says of it: size, content type, the four checksums (each with a copy button), blob store, who stored it and when, when it was last downloaded, the component it belongs to, and a download link.
-- **A proxy** is browsed for what it has cached, and says so. **A group** lists its members.
+- **A proxy** is browsed for what it has cached, and says so under its name. **A group** lists its members, those the caller may browse, each a link: the API refuses to list a group's own folders, as it holds none.
 - **Upload forms:** Raw has a directory (filled in from where the upload was started) and files. Maven has group, artifact, version, packaging, whether to write a POM, the artifact, an optional POM, and further files each with a classifier. npm has one tarball and a tag. PyPI has files, and optionally a summary, the Python it requires and keywords. A refusal by the API is put at the field it names.
 - **Names and paths are text.** A path is put into an address one segment at a time, each encoded; nothing from the API is put into the page as markup.
 
+#### Settled while building plan 10a
+
+| # | What | Why |
+| --- | --- | --- |
+| B1 | A name someone chose (a repository, a folder, a version) is never put in capitals: not in a screen's title, not in a dialog's title, and not in the label that asks for it to be typed. Titles that are the UI's own words stay in capitals. | Names tell capitals from small letters, and the name typed to confirm is compared exactly. A label that showed `V1` for `v1` asked for the wrong thing. |
+| B2 | A folder that is not there says so and leads to the top of its repository. | Folders are not things of their own: deleting the last file of one removes it, and the folders above it that held nothing else. The screen a delete returns to can therefore be such a folder. |
+| B3 | A folder or a file in a list is named to a screen reader with its kind: "Folder docs", "File guide.md". | The icon that tells them apart is not read. |
+| B4 | The upload is the one request made with `XMLHttpRequest`. | `fetch` cannot say how much of a body has been sent (S7). Its failures are the same `ApiError` as every other request's. |
+| B5 | The file field is emptied after each choice, so that files add up and one that was taken out can be chosen again. The browser's own "No file chosen" beside it is not shown: the list under the field says what is chosen. | The two contradicted each other. |
+| B6 | What was fetched of a repository is forgotten after an upload or a delete in it: its folders are asked for again, and its files' and components' details are dropped. | An index or a metadata file can change with any of them. |
+| B7 | A screen inside the shell that is given an address it cannot read says that nothing is there, inside the shell. The page for an address no route answers is a different one, with no shell. | Two `main` landmarks otherwise. |
+| B8 | The lint refuses text written into a property that is read out (`aria-label`, `title`, `alt`, `placeholder`, `label`, `hint`), as it refuses text in markup. | Left open by plan 9: UI-4 is about every text a person meets. |
+| B9 | A button that is busy keeps the keyboard: it is marked `aria-disabled` and ignores a press, where it used to be disabled. | A disabled button loses focus, and with it a keyboard user's place, each time something is sent. Left open by plan 9. |
+
 ### 12.3 Account and security (plan 10b, outline)
 
 A person's API tokens (create, with the secret shown once; revoke). Users (create, edit, disable, set a password, revoke tokens, delete). Roles (create, edit, delete; permissions as patterns, with help for writing them). Anonymous access (on or off).
```

- [ ] **Step 5: Run everything**

Run: `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: no finding, 499 passed, `Compiled successfully`.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: no finding; 2756 passed, 1 skipped.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: 35 passed.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-12-frontend-design.md
git commit -m "docs: the browsing screens of the web UI"
```
