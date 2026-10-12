// @vitest-environment node
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";
import { expect, test } from "vitest";

const unix = (text: string) => text.replaceAll("\r\n", "\n");

test("the API's types are those of the API document beside them", async () => {
  // openapi.json is the backend's own document, held up to date by a backend test.
  // The types are made from it with `pnpm gen:api`. If this fails, run that.
  const made = astToString(await openapiTS(pathToFileURL("openapi.json")));
  const committed = unix(readFileSync("src/lib/api/schema.d.ts", "utf8"));

  expect(committed.endsWith(unix(made))).toBe(true);
});

test("the document describes what the UI is written against", () => {
  const document = JSON.parse(readFileSync("openapi.json", "utf8"));

  for (const path of ["/api/v1/auth/session", "/api/v1/auth/login", "/api/v1/me/password"]) {
    expect(Object.keys(document.paths)).toContain(path);
  }
  expect(Object.keys(document.components.schemas)).toEqual(
    expect.arrayContaining(["SessionInfo", "RepositoryView"]),
  );
});
