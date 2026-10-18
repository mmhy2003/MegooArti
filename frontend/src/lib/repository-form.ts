/**
 * A repository as a form holds it, and as the API takes it. No React here.
 *
 * The form is one page that grows (S13): what it shows follows from the format and the
 * type. This module says which parts a combination has, what a form starts with, what
 * is wrong with it before the server is asked, and the body that is sent.
 */
import type { RepositoryCreate, RepositoryOut, RepositoryUpdate } from "@/lib/api/types";
import { isAddressable } from "@/lib/paths";

/** The formats the server has. Each can be hosted, a proxy or a group. */
export const FORMATS = [
  "raw",
  "maven",
  "npm",
  "pypi",
  "docker",
  "apt",
  "yum",
  "apk",
  "nuget",
] as const;
/** The formats whose indexes are signed: a key of their own, and a remote's keys for a proxy. */
export const SIGNED: ReadonlySet<string> = new Set(["apt", "yum", "apk"]);
export const TYPES = ["hosted", "proxy", "group"] as const;
export type RepositoryType = (typeof TYPES)[number];
export const DEPLOYMENT_POLICIES = ["allow_redeploy", "disable_redeploy", "read_only"] as const;
export const AUTH_TYPES = ["none", "basic", "bearer"] as const;
export const VERSION_POLICIES = ["release", "snapshot", "mixed"] as const;
export const LAYOUT_POLICIES = ["strict", "permissive"] as const;
/** The blob store a repository gets when none is chosen. */
export const DEFAULT_BLOB_STORE = "default";
/** The suite a hosted APT repository has when none is given: the server's own. */
export const DEFAULT_SUITE = "stable";
/** How many directories down a YUM repository's metadata may be. */
export const DEPTH_MOST = 5;
/** The protocols a NuGet proxy speaks to its remote, and serves: chosen once. */
export const PROTOCOLS = ["v3", "v2"] as const;

// The server's rule for a name, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
// A Docker repository's name is the first part of its images' names.
const DOCKER_NAME = /^[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*$/;
// The server's rule for an APT suite: the name in each machine's sources line.
const SUITE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

/** What the form holds. Numbers are text while they are typed. */
export type Draft = {
  name: string;
  format: string;
  type: RepositoryType;
  online: boolean;
  blobStore: string;
  /** Null until one is chosen: the form then shows, and sends, the server's own (H1). */
  deploymentPolicy: string | null;
  remoteUrl: string;
  contentMaxAge: string;
  metadataMaxAge: string;
  negativeCache: boolean;
  negativeCacheTtl: string;
  authType: string;
  authUsername: string;
  /** Typed now. Empty keeps the one that is stored, if there is one. */
  authSecret: string;
  /** Whether the server holds a secret for this proxy already. */
  hasSecret: boolean;
  blocked: boolean;
  autoBlock: boolean;
  members: string[];
  versionPolicy: string;
  layoutPolicy: string;
  /** A hosted APT repository's. Chosen once. */
  suite: string;
  /** How many directories down a hosted YUM repository's metadata is. Chosen once. */
  repodataDepth: string;
  /** A proxy's remote's public keys, as they are pasted. */
  remoteKeys: string;
  /** A NuGet proxy's protocol: v3 or v2. Chosen once. */
  protocol: string;
  /** The symbol server a NuGet proxy passes symbol requests on to; empty for none. */
  symbolUrl: string;
};

/** A form for a repository that is not there yet: the server's own defaults. */
export const EMPTY: Draft = {
  name: "",
  format: "maven",
  type: "hosted",
  online: true,
  blobStore: DEFAULT_BLOB_STORE,
  deploymentPolicy: null,
  remoteUrl: "",
  contentMaxAge: "1440",
  metadataMaxAge: "1440",
  negativeCache: true,
  negativeCacheTtl: "1440",
  authType: "none",
  authUsername: "",
  authSecret: "",
  hasSecret: false,
  blocked: false,
  autoBlock: true,
  members: [],
  versionPolicy: "release",
  layoutPolicy: "strict",
  suite: DEFAULT_SUITE,
  repodataDepth: "0",
  remoteKeys: "",
  protocol: "v3",
  symbolUrl: "",
};

const text = (value: unknown, otherwise: string): string =>
  typeof value === "string" ? value : otherwise;

/** The form of a repository as the server holds it. */
export function draftOf(repository: RepositoryOut): Draft {
  const { proxy, hosted, group, format_config: config } = repository;
  return {
    ...EMPTY,
    name: repository.name,
    format: repository.format,
    type: (TYPES as readonly string[]).includes(repository.type)
      ? (repository.type as RepositoryType)
      : "hosted",
    online: repository.online,
    blobStore: repository.blob_store ?? DEFAULT_BLOB_STORE,
    deploymentPolicy: hosted?.deployment_policy ?? null,
    remoteUrl: proxy?.remote_url ?? "",
    contentMaxAge: String(proxy?.content_max_age_minutes ?? EMPTY.contentMaxAge),
    metadataMaxAge: String(proxy?.metadata_max_age_minutes ?? EMPTY.metadataMaxAge),
    negativeCache: proxy?.negative_cache.enabled ?? true,
    negativeCacheTtl: String(proxy?.negative_cache.ttl_minutes ?? EMPTY.negativeCacheTtl),
    authType: proxy?.remote_auth.type ?? "none",
    authUsername: proxy?.remote_auth.username ?? "",
    hasSecret: proxy?.remote_auth.has_secret ?? false,
    blocked: proxy?.blocked ?? false,
    autoBlock: proxy?.auto_block ?? true,
    members: group?.members ?? [],
    versionPolicy: text(config.version_policy, EMPTY.versionPolicy),
    layoutPolicy: text(config.layout_policy, EMPTY.layoutPolicy),
    suite: text(config.suite, EMPTY.suite),
    repodataDepth: String(
      typeof config.repodata_depth === "number" ? config.repodata_depth : EMPTY.repodataDepth,
    ),
    remoteKeys: text(config.remote_keys, EMPTY.remoteKeys),
    protocol: text(config.protocol, EMPTY.protocol),
    symbolUrl: text(config.symbol_url, EMPTY.symbolUrl),
  };
}

/**
 * The deployment policy of a hosted repository: the one that was chosen, or the one the
 * server gives a repository that names none. A Maven repository for releases refuses to
 * replace what was deployed (a release is deployed once), and so does a NuGet one (a
 * version is pushed once, as nuget.org takes it); every other one allows it.
 */
export function policyOf(
  draft: Pick<Draft, "format" | "versionPolicy" | "deploymentPolicy">,
): string {
  if (draft.deploymentPolicy !== null) return draft.deploymentPolicy;
  const releases = draft.format === "maven" && draft.versionPolicy === "release";
  return releases || draft.format === "nuget" ? "disable_redeploy" : "allow_redeploy";
}

/** Whether a combination has settings of the format's own: a Maven repository that stores. */
export function hasMavenSettings(draft: Pick<Draft, "format" | "type">): boolean {
  return draft.format === "maven" && draft.type !== "group";
}

/** Whether a combination is given its remote's keys: a proxy of a format that signs. */
export function takesRemoteKeys(draft: Pick<Draft, "format" | "type">): boolean {
  return draft.type === "proxy" && SIGNED.has(draft.format);
}

/** Whether a combination has a key of its own: a hosted repository or a group that signs. */
export function hasSigningKey(repository: { format: string; type: string }): boolean {
  return repository.type !== "proxy" && SIGNED.has(repository.format);
}

/** Whether a combination has a NuGet proxy's settings: its protocol and its symbol server. */
export function isNuGetProxy(draft: { format: string; type: string }): boolean {
  return draft.format === "nuget" && draft.type === "proxy";
}

/** A whole number of at least `minimum`, or null for what is none. */
function whole(typed: string, minimum: number): number | null {
  if (!/^-?\d{1,9}$/.test(typed.trim())) return null;
  const value = Number(typed.trim());
  return value >= minimum ? value : null;
}

function isRemote(typed: string): boolean {
  try {
    const url = new URL(typed.trim());
    const web = url.protocol === "http:" || url.protocol === "https:";
    return web && url.hostname !== "" && !url.username && !url.password && !url.search && !url.hash;
  } catch {
    return false;
  }
}

/** What can be wrong before the server is asked, by the name of the message that says it. */
export type Problem =
  | "nameRule"
  | "nameDots"
  | "dockerNameRule"
  | "remoteRule"
  | "ageRule"
  | "ttlRule"
  | "usernameNeeded"
  | "secretNeeded"
  | "suiteRule"
  | "depthRule"
  | "symbolUrlRule";

export type Problems = Partial<
  Record<
    | "name"
    | "remoteUrl"
    | "contentMaxAge"
    | "metadataMaxAge"
    | "negativeCacheTtl"
    | "authUsername"
    | "authSecret"
    | "suite"
    | "repodataDepth"
    | "symbolUrl",
    Problem
  >
>;

/** `creating` is false for a repository that is there: its name is then not the form's to check. */
export function problemsOf(draft: Draft, creating: boolean): Problems {
  const problems: Problems = {};
  if (creating) {
    if (!NAME.test(draft.name)) problems.name = "nameRule";
    else if (!isAddressable(draft.name)) problems.name = "nameDots";
    else if (draft.format === "docker" && !DOCKER_NAME.test(draft.name)) {
      problems.name = "dockerNameRule";
    }
  }
  if (draft.type === "proxy") {
    if (!isRemote(draft.remoteUrl)) problems.remoteUrl = "remoteRule";
    if (whole(draft.contentMaxAge, -1) === null) problems.contentMaxAge = "ageRule";
    if (whole(draft.metadataMaxAge, -1) === null) problems.metadataMaxAge = "ageRule";
    if (draft.negativeCache && whole(draft.negativeCacheTtl, 1) === null) {
      problems.negativeCacheTtl = "ttlRule";
    }
    if (draft.authType === "basic" && draft.authUsername.trim() === "") {
      problems.authUsername = "usernameNeeded";
    }
    if (draft.authType !== "none" && draft.authSecret === "" && !draft.hasSecret) {
      problems.authSecret = "secretNeeded";
    }
    if (isNuGetProxy(draft) && draft.symbolUrl.trim() !== "" && !isRemote(draft.symbolUrl)) {
      problems.symbolUrl = "symbolUrlRule";
    }
  }
  // Chosen once: a repository that is there has the one it was made with.
  if (creating && draft.type === "hosted") {
    if (draft.format === "apt" && !SUITE.test(draft.suite.trim())) problems.suite = "suiteRule";
    const depth = whole(draft.repodataDepth, 0);
    if (draft.format === "yum" && (depth === null || depth > DEPTH_MOST)) {
      problems.repodataDepth = "depthRule";
    }
  }
  return problems;
}

/** The parts of a body that follow from the type. The others are null: there are none. */
function parts(draft: Draft) {
  const proxy = draft.type === "proxy";
  return {
    online: draft.online,
    // What the form shows is what is sent: the server is not left to choose again.
    hosted: draft.type === "hosted" ? { deployment_policy: policyOf(draft) as "read_only" } : null,
    proxy: proxy
      ? {
          remote_url: draft.remoteUrl.trim(),
          content_max_age_minutes: whole(draft.contentMaxAge, -1) ?? 1440,
          metadata_max_age_minutes: whole(draft.metadataMaxAge, -1) ?? 1440,
          negative_cache: {
            enabled: draft.negativeCache,
            // Kept as it was while the cache is off, so that turning it on again finds it.
            ttl_minutes: whole(draft.negativeCacheTtl, 1) ?? 1440,
          },
          remote_auth:
            draft.authType === "none"
              ? { type: "none" as const, username: "", secret: null }
              : {
                  type: draft.authType as "basic",
                  username: draft.authType === "basic" ? draft.authUsername.trim() : "",
                  // Not sent, the one that is stored is kept.
                  secret: draft.authSecret === "" ? null : draft.authSecret,
                },
          blocked: draft.blocked,
          auto_block: draft.autoBlock,
        }
      : null,
    group: draft.type === "group" ? { members: draft.members } : null,
    format_config: formatConfig(draft),
  };
}

/**
 * The settings of the format's own. What was chosen once is sent as it is held, and the
 * server takes it again unchanged. A proxy's keys are always sent: the settings are
 * replaced whole, and keys that were not sent would be none.
 */
function formatConfig(draft: Draft): Record<string, unknown> {
  if (hasMavenSettings(draft)) {
    return { version_policy: draft.versionPolicy, layout_policy: draft.layoutPolicy };
  }
  if (takesRemoteKeys(draft)) return { remote_keys: draft.remoteKeys };
  if (isNuGetProxy(draft)) {
    // Its protocol is sent as it is held: the server refuses to change it.
    const symbolUrl = draft.symbolUrl.trim();
    return { protocol: draft.protocol, ...(symbolUrl ? { symbol_url: symbolUrl } : {}) };
  }
  if (draft.type !== "hosted") return {};
  if (draft.format === "apt") return { suite: draft.suite.trim() };
  if (draft.format === "yum") return { repodata_depth: whole(draft.repodataDepth, 0) ?? 0 };
  return {};
}

/** What is sent to make a repository. A group stores nothing, and so names no blob store. */
export function createBody(draft: Draft): RepositoryCreate {
  return {
    name: draft.name,
    format: draft.format,
    type: draft.type,
    blob_store: draft.type === "group" ? null : draft.blobStore || DEFAULT_BLOB_STORE,
    ...parts(draft),
  };
}

/** What is sent to change one. What cannot change is not sent. */
export function updateBody(draft: Draft): RepositoryUpdate {
  return parts(draft);
}

/** A member, moved one place up (-1) or down (1). The list as it was if that is nowhere. */
export function moved(members: string[], name: string, by: -1 | 1): string[] {
  const from = members.indexOf(name);
  const to = from + by;
  if (from < 0 || to < 0 || to >= members.length) return members;
  const next = [...members];
  [next[from], next[to]] = [next[to] as string, next[from] as string];
  return next;
}
