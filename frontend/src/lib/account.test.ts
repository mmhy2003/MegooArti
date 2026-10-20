import type { Route } from "next";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import { endOfDay } from "@/lib/format";
import { ALPHABET, generatePassword } from "@/lib/passwords";
import {
  isAddressable,
  NEW_ROLE,
  pageHref,
  pageOf,
  parseRole,
  parseUser,
  roleHref,
  userHref,
  USERS,
} from "@/lib/paths";
import {
  fromPattern,
  isValidPattern,
  READ_ONLY,
  startOf,
  toPattern,
  type Row,
} from "@/lib/patterns";
import { SEARCH_KEY_STORAGE, searchKeyIsOn, setSearchKey } from "@/lib/preferences";
import { refusalsOf } from "@/lib/refusals";
import { grants } from "@/lib/session/permissions";
import { decide } from "@/lib/session/rules";
import { ADMIN, NOBODY, VISITOR } from "@/test/render";

describe("a permission pattern", () => {
  // As the backend takes them (megooarti.security.permissions.is_valid_pattern).
  test.each([
    ["*", true],
    ["admin:users:*", true],
    ["repository:maven:my.repo-1_x:read", true],
    ["repository:*:*:read", true],
    ["", false],
    ["admin::read", false],
    ["admin:us ers", false],
    ["admin:**", false],
    ["admin:use*", false],
    ["é", false],
  ])("%s is one: %s", (pattern, expected) => {
    expect(isValidPattern(pattern)).toBe(expected);
  });

  test.each<[string, Row]>([
    ["*", { kind: "all" }],
    [
      "repository:maven:releases:read",
      { kind: "repository", format: "maven", name: "releases", action: "read" },
    ],
    ["repository:*:*:browse", { kind: "repository", format: "*", name: "*", action: "browse" }],
    ["repository:npm:*:*", { kind: "repository", format: "npm", name: "*", action: "*" }],
    ["admin:users:write", { kind: "admin", area: "users", action: "write" }],
    ["admin:*:read", { kind: "admin", area: "*", action: "read" }],
    ["admin:*:*", { kind: "admin", area: "*", action: "*" }],
  ])("%s is taken apart into a row, and the row makes it again", (pattern, row) => {
    expect(fromPattern(pattern)).toEqual(row);
    expect(toPattern(row)).toBe(pattern);
  });

  // Each grants something, and is kept as it was written: nothing a role holds is
  // rewritten by opening it (A3).
  test.each([
    "repository:maven", // shorter: everything in every Maven repository
    "repository",
    "admin",
    "admin:users",
    "repository:maven:releases:publish", // an action this UI does not know
    "admin:jobs:read", // an area this UI does not know
    "admin:users:read:more",
    "*:users:read",
    "metrics:read",
  ])("%s is of no shape a row has, and stays as it was typed", (pattern) => {
    expect(fromPattern(pattern)).toEqual({ kind: "typed", text: pattern });
    expect(toPattern(fromPattern(pattern))).toBe(pattern);
  });

  test("what is no pattern at all is a typed row too, to be put right", () => {
    expect(fromPattern("not a pattern")).toEqual({ kind: "typed", text: "not a pattern" });
    expect(toPattern({ kind: "typed", text: "  admin:users  " })).toBe("admin:users");
  });

  test("a row starts as the widest of its shape that only reads", () => {
    expect(toPattern(startOf("repository"))).toBe("repository:*:*:read");
    expect(toPattern(startOf("admin"))).toBe("admin:*:read");
    expect(toPattern(startOf("all"))).toBe("*");
    expect(toPattern(startOf("typed"))).toBe("");
  });

  test("a token that may only read can browse and download, and nothing else", () => {
    const may = (permission: string) => READ_ONLY.some((pattern) => grants(pattern, permission));

    expect(may("repository:maven:releases:browse")).toBe(true);
    expect(may("repository:npm:own:read")).toBe(true);
    expect(may("repository:maven:releases:add")).toBe(false);
    expect(may("repository:maven:releases:delete")).toBe(false);
    expect(may("admin:users:read")).toBe(false);
  });
});

describe("a generated password", () => {
  afterEach(() => vi.restoreAllMocks());

  test("is twenty characters that are not mistaken for each other", () => {
    const password = generatePassword();

    expect(password).toHaveLength(20);
    expect(Array.from(password).every((character) => ALPHABET.includes(character))).toBe(true);
    for (const confusing of "0O1lI") expect(ALPHABET).not.toContain(confusing);
    expect(generatePassword(32)).toHaveLength(32);
  });

  test("is another one each time, from the browser's own randomness", () => {
    const random = vi.spyOn(crypto, "getRandomValues");

    const made = new Set(Array.from({ length: 50 }, () => generatePassword()));

    expect(made.size).toBe(50);
    expect(random).toHaveBeenCalled();
  });

  test("favours no letter: a byte that would is drawn again", () => {
    // 228 is the first byte past the last whole run of the alphabet (4 x 57): taken, it
    // would make the first letters likelier than the last.
    expect(ALPHABET).toHaveLength(57);
    const bytes = [228, 255, 0, 56, 57, 227];
    vi.spyOn(crypto, "getRandomValues").mockImplementation((array) => {
      (array as Uint8Array).set(
        Array.from({ length: (array as Uint8Array).length }, () => bytes.shift() ?? 1),
      );
      return array;
    });

    expect(generatePassword(4)).toBe(`${ALPHABET[0]}${ALPHABET[56]}${ALPHABET[0]}${ALPHABET[56]}`);
  });
});

describe("the day a token lasts until", () => {
  test("is the end of that day, where the person is", () => {
    expect(endOfDay("2031-05-17")).toBe(new Date("2031-05-17T23:59:59").toISOString());
  });

  test.each(["", "20261-01-01", "2031-02-31x", "not a day"])(
    "%s is no day, and is said to be none instead of failing",
    (typed) => {
      expect(endOfDay(typed)).toBeNull();
    },
  );
});

describe("the search key", () => {
  test("is on until it is turned off, and is kept in the browser", () => {
    expect(searchKeyIsOn()).toBe(true);

    setSearchKey(false);
    expect(searchKeyIsOn()).toBe(false);
    expect(window.localStorage.getItem(SEARCH_KEY_STORAGE)).toBe("off");

    setSearchKey(true);
    expect(searchKeyIsOn()).toBe(true);
    expect(window.localStorage.getItem(SEARCH_KEY_STORAGE)).toBeNull();
  });

  test("can be turned off where storage cannot be used: for as long as the page lives", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(searchKeyIsOn()).toBe(true);

    // Whoever needs the key left alone needs it whether or not the browser keeps things.
    expect(() => setSearchKey(false)).not.toThrow();
    expect(searchKeyIsOn()).toBe(false);
    setSearchKey(true);
    expect(searchKeyIsOn()).toBe(true);
    vi.restoreAllMocks();
  });

  test("tells the page when it changes", () => {
    const told = vi.fn();
    window.addEventListener("megooarti-preferences", told);

    setSearchKey(false);

    expect(told).toHaveBeenCalledOnce();
    window.removeEventListener("megooarti-preferences", told);
  });
});

describe("what the API refused of a form", () => {
  const refusal = (details: { field: string; message: string }[]) =>
    new ApiError(422, "validation_error", "The request is not valid.", details, null);

  test("is put at the form's own field, whatever the server calls the place", () => {
    const refused = refusalsOf(
      refusal([
        { field: "body.name", message: "Too long." },
        { field: "password", message: "Too short." },
        { field: "body.permissions.2", message: "Not a pattern." },
      ]),
      ["name", "password", "permissions"],
    );

    expect(refused).toEqual({
      at: { name: "Too long.", password: "Too short.", permissions: "Not a pattern." },
      elsewhere: false,
    });
  });

  test("says the first thing wrong with a field, and not the rest", () => {
    const refused = refusalsOf(
      refusal([
        { field: "body.permissions.0", message: "First." },
        { field: "body.permissions.3", message: "Second." },
      ]),
      ["permissions"],
    );

    expect(refused.at).toEqual({ permissions: "First." });
  });

  test("is said whole when it is about nothing the form has", () => {
    expect(refusalsOf(refusal([{ field: "body.colour", message: "?" }]), ["name"])).toEqual({
      at: {},
      elsewhere: true,
    });
    // A field whose name only begins the same is another field.
    expect(refusalsOf(refusal([{ field: "body.names", message: "?" }]), ["name"]).elsewhere).toBe(
      true,
    );
    expect(refusalsOf(refusal([]), ["name"]).elsewhere).toBe(true);
  });

  test("a failure of another kind is said whole, and no failure is nothing", () => {
    const conflict = new ApiError(409, "conflict", "A user named alice already exists.", [], null);

    expect(refusalsOf(conflict, ["username"])).toEqual({ at: {}, elsewhere: true });
    expect(refusalsOf(new Error("?"), ["username"]).elsewhere).toBe(true);
    expect(refusalsOf(null, ["username"])).toEqual({ at: {}, elsewhere: false });
  });
});

describe("the addresses of the account and security screens", () => {
  test("a user is addressed by its id, a role by its name, each as one segment", () => {
    expect(userHref("0190-aa")).toBe("/admin/users/0190-aa");
    expect(roleHref("deployers")).toBe("/admin/roles/deployers");
    // A role may be called "new": the form for a new one is where no name can be.
    expect(roleHref("new")).toBe("/admin/roles/new");
    expect(NEW_ROLE).toBe("/admin/roles/~new");
    expect(isAddressable("new")).toBe(true);
    expect(isAddressable(".")).toBe(false); // a browser takes these for folders
    expect(isAddressable("..")).toBe(false);
    expect(roleHref("odd/name?#")).toBe("/admin/roles/odd%2Fname%3F%23");

    expect(parseUser("/admin/users/0190-aa")).toEqual({ id: "0190-aa" });
    expect(parseRole("/admin/roles/odd%2Fname%3F%23")).toEqual({ name: "odd/name?#" });
  });

  test("an address that names none is not read as one", () => {
    expect(parseUser("/admin/users")).toBeNull();
    expect(parseUser("/admin/users/a/b")).toBeNull();
    expect(parseRole("/admin/roles/")).toBeNull();
    expect(parseRole("/admin/rolesx/a")).toBeNull();
    expect(parseRole("/admin/roles/%E0%A4%A")).toBeNull();
  });

  test("the first page of a list has no number in its address", () => {
    expect(pageHref(USERS, 1)).toBe("/admin/users");
    expect(pageHref(USERS, 3)).toBe("/admin/users?page=3");
    expect(pageHref("/account/tokens" as Route, 2)).toBe("/account/tokens?page=2");
  });

  test.each([
    ["", 1],
    ["page=1", 1],
    ["page=7", 7],
    ["page=0", 1],
    ["page=-2", 1],
    ["page=2x", 1],
    ["page=1.5", 1],
    ["page=99999999999999999999", 1],
  ])("the page of ?%s is %i", (query, page) => {
    expect(pageOf(new URLSearchParams(query))).toBe(page);
  });
});

describe("the preferences page", () => {
  test("is a visitor's too, though the rest of the account is not", () => {
    expect(decide(VISITOR, "/account/preferences")).toEqual({ show: true });
    expect(decide(VISITOR, "/account/tokens")).toEqual({
      show: false,
      goTo: "/login?next=%2Faccount%2Ftokens",
    });
    expect(decide(VISITOR, "/account/preferences-and-more").show).toBe(false);
    expect(decide(ADMIN, "/account/preferences")).toEqual({ show: true });
  });

  test("is not shown where nobody may be without signing in", () => {
    expect(decide(NOBODY, "/account/preferences")).toEqual({
      show: false,
      goTo: "/login?next=%2Faccount%2Fpreferences",
    });
  });
});
