/**
 * Permission patterns, as the rows of a form and back. No React here.
 *
 * A pattern is words joined by `:`, with `*` for any one word; a pattern shorter than
 * what is asked grants everything under it (`megooarti.security.permissions`). A row is
 * a pattern of one of the shapes the API uses, taken apart so that it can be chosen
 * from lists. A pattern of any other shape is a row typed by hand, and is kept as it is.
 */

export const ANY = "*";
/** What can be done to a repository's content. */
export const REPOSITORY_ACTIONS = ["browse", "read", "add", "edit", "delete"] as const;
/** The areas of administration the API has. */
export const ADMIN_AREAS = [
  "users",
  "roles",
  "tokens",
  "settings",
  "blobstores",
  "repositories",
  "security",
  "certificates",
  "audit",
  "selectors",
] as const;
export const ADMIN_ACTIONS = ["read", "write"] as const;
/** What a token that may only read is limited to. */
export const READ_ONLY = ["repository:*:*:browse", "repository:*:*:read"] as const;

const WORD = /^[A-Za-z0-9_.-]+$/;

/** Whether the server would take it as a pattern. */
export function isValidPattern(pattern: string): boolean {
  return pattern.split(":").every((part) => part === ANY || WORD.test(part));
}

export type Row =
  | { kind: "repository"; format: string; name: string; action: string }
  // Some of a repository: what a content selector matches in it (spec 10).
  | { kind: "selector"; selector: string; format: string; name: string; action: string }
  | { kind: "admin"; area: string; action: string }
  | { kind: "all" }
  | { kind: "typed"; text: string };

export type RowKind = Row["kind"];

const known = (values: readonly string[], value: string | undefined) =>
  value === ANY || (value !== undefined && values.includes(value));

/** The pattern a row stands for. A typed row is what was typed, without space around it. */
export function toPattern(row: Row): string {
  switch (row.kind) {
    case "repository":
      return `repository:${row.format}:${row.name}:${row.action}`;
    case "selector":
      return `selector:${row.selector}:${row.format}:${row.name}:${row.action}`;
    case "admin":
      return `admin:${row.area}:${row.action}`;
    case "all":
      return ANY;
    case "typed":
      return row.text.trim();
  }
}

/**
 * The row for a pattern. Only a pattern that a row would write is taken apart: any
 * other, though it may grant the same (`repository:maven` for `repository:maven:*:*`),
 * stays as it was written.
 */
export function fromPattern(pattern: string): Row {
  if (pattern === ANY) return { kind: "all" };
  const typed: Row = { kind: "typed", text: pattern };
  if (!isValidPattern(pattern)) return typed;
  const [about, second, third, fourth, fifth, ...more] = pattern.split(":");
  if (
    about === "selector" &&
    more.length === 0 &&
    second !== undefined &&
    third !== undefined &&
    fourth !== undefined &&
    fifth !== undefined &&
    known(REPOSITORY_ACTIONS, fifth)
  ) {
    return { kind: "selector", selector: second, format: third, name: fourth, action: fifth };
  }
  if (fifth !== undefined || second === undefined || third === undefined) return typed;
  if (about === "repository" && fourth !== undefined && known(REPOSITORY_ACTIONS, fourth)) {
    return { kind: "repository", format: second, name: third, action: fourth };
  }
  if (
    about === "admin" &&
    fourth === undefined &&
    known(ADMIN_AREAS, second) &&
    known(ADMIN_ACTIONS, third)
  ) {
    return { kind: "admin", area: second, action: third };
  }
  return typed;
}

/** A row of a kind, as it starts: the widest of its shape that only reads. */
export function startOf(kind: RowKind): Row {
  switch (kind) {
    case "repository":
      return { kind, format: ANY, name: ANY, action: "read" };
    case "selector":
      return { kind, selector: ANY, format: ANY, name: ANY, action: "read" };
    case "admin":
      return { kind, area: ANY, action: "read" };
    case "all":
      return { kind };
    case "typed":
      return { kind, text: "" };
  }
}
