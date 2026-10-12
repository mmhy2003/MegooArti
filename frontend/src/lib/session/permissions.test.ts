import { expect, test } from "vitest";

import { anyGrants, grants, grantsSome, isValidPermission } from "./permissions";

// The cases of the backend's own tests (backend/tests/security/test_permissions.py):
// the two must agree, or the UI offers what the API refuses.
test.each([
  ["*", "admin:users:write", true],
  ["admin:users:*", "admin:users:write", true],
  ["admin:users:read", "admin:users:write", false],
  ["admin:users:write", "admin:users:write", true],
  ["repository:*:*:read", "repository:maven:releases:read", true],
  ["repository:*:*:read", "repository:maven:releases:delete", false],
  ["repository:maven", "repository:maven:releases:delete", true],
  ["repository:maven", "repository:npm:internal:read", false],
  ["admin", "admin:settings:write", true],
  ["repository:maven:releases:read:extra", "repository:maven:releases:read", false],
  ["admin:Users:read", "admin:users:read", false],
  ["*:users:read", "admin:users:read", true],
])("the pattern %s grants %s: %s", (pattern, permission, expected) => {
  expect(grants(pattern, permission)).toBe(expected);
});

test("one pattern that grants is enough, and none grants nothing", () => {
  expect(anyGrants(["admin:roles:read", "admin:users:*"], "admin:users:write")).toBe(true);
  expect(anyGrants(["admin:roles:read"], "admin:users:write")).toBe(false);
  expect(anyGrants([], "admin:users:read")).toBe(false);
});

// "Could this caller add to some repository?": a `?` stands for any value.
test.each([
  ["*", "repository:?:?:add", true],
  ["repository", "repository:?:?:add", true],
  ["repository:maven", "repository:?:?:add", true],
  ["repository:maven:releases:add", "repository:?:?:add", true],
  ["repository:*:*:add", "repository:?:?:add", true],
  ["repository:maven:releases:*", "repository:?:?:add", true],
  ["repository:*:*:read", "repository:?:?:add", false],
  ["repository:maven:releases:edit", "repository:?:?:add", false],
  ["admin:users:*", "repository:?:?:add", false],
  ["repository:maven:releases:add:more", "repository:?:?:add", false],
])("the pattern %s could grant %s: %s", (pattern, shape, expected) => {
  expect(grantsSome(pattern, shape)).toBe(expected);
});

test("a permission is plain words: no wildcard, nothing empty", () => {
  expect(isValidPermission("admin:users:read")).toBe(true);
  expect(isValidPermission("repository:maven:my.repo-1_x:read")).toBe(true);
  for (const odd of ["admin:*:read", "", "admin::read", "admin:us ers", "é"]) {
    expect(isValidPermission(odd)).toBe(false);
  }
});
