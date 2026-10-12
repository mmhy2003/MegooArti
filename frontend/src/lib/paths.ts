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
