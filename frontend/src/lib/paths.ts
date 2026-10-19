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
export const ACCOUNT_TOKENS = "/account/tokens" as Route;
export const PREFERENCES = "/account/preferences" as Route;
export const CONNECTED_APPS = "/account/connected-apps" as Route;
/** The consent page an application signing in with OAuth sends a person to. */
export const CONNECT = "/connect" as Route;
export const USERS = "/admin/users" as Route;
export const NEW_USER = "/admin/users/new" as Route;
export const ROLES = "/admin/roles" as Route;
// Where no role's name can be: a role may be called "new", and has `~` in no name.
export const NEW_ROLE = "/admin/roles/~new" as Route;
export const ANONYMOUS_ACCESS = "/admin/anonymous-access" as Route;
export const AUTHENTICATION = "/admin/authentication" as Route;
export const MANAGE_REPOSITORIES = "/admin/repositories" as Route;
// As for a role: a repository may be called "new", and has `~` in no name.
export const NEW_REPOSITORY = "/admin/repositories/~new" as Route;
export const BLOB_STORES = "/admin/blob-stores" as Route;
export const SYSTEM = "/admin/system" as Route;

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

/** A page of a list that has numbered pages. The first has no number in its address. */
export function pageHref(list: Route, page: number): Route {
  return withQuery(list, { page: page > 1 ? String(page) : undefined });
}

/** The page an address asks for: a whole number from 1, or 1 for anything else. */
export function pageOf(search: { get(name: string): string | null }): number {
  const asked = search.get("page") ?? "";
  return /^[1-9][0-9]{0,8}$/.test(asked) ? Number(asked) : 1;
}

export function userHref(id: string): Route {
  return `${USERS}/${encodeURIComponent(id)}` as Route;
}

/**
 * Whether something called this can have a page whose address ends in its name. A
 * browser takes `.` and `..` for the folder itself and the one above, however they are
 * written, so a name that is one of them has no address of its own.
 */
export function isAddressable(name: string): boolean {
  return name !== "." && name !== "..";
}

export function roleHref(name: string): Route {
  return `${ROLES}/${encodeURIComponent(name)}` as Route;
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

/** The settings of a repository, as an administrator sees them. */
export function repositorySettingsHref(name: string): Route {
  return `${MANAGE_REPOSITORIES}/${encodeURIComponent(name)}` as Route;
}

/** The one thing an address under a list names: a user's id, a role's name. Null if none. */
function one(pathname: string, list: string): string | null {
  const found = after(pathname, list);
  const [name] = found ?? [];
  return found?.length === 1 && name ? name : null;
}

/** The id of the user an address is about. `new` is the form for one that is not there yet. */
export function parseUser(pathname: string): { id: string } | null {
  const id = one(pathname, USERS);
  return id === null ? null : { id };
}

export function parseRole(pathname: string): { name: string } | null {
  const name = one(pathname, ROLES);
  return name === null ? null : { name };
}

/** The repository whose settings an address is about. */
export function parseRepositorySettings(pathname: string): { name: string } | null {
  const name = one(pathname, MANAGE_REPOSITORIES);
  return name === null ? null : { name };
}
