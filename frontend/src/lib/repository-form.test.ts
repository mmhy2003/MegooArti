import { describe, expect, test } from "vitest";

import type { RepositoryOut } from "@/lib/api/types";
import {
  MANAGE_REPOSITORIES,
  NEW_REPOSITORY,
  parseRepositorySettings,
  repositorySettingsHref,
} from "@/lib/paths";

import {
  createBody,
  defaultRemoteOf,
  draftOf,
  EMPTY,
  FORMATS,
  hasMavenSettings,
  hasSigningKey,
  isNuGetProxy,
  moved,
  policyOf,
  problemsOf,
  publicRemotesOf,
  takesRemoteKeys,
  updateBody,
  withDefaultRemote,
  type Draft,
} from "./repository-form";

const draft = (change: Partial<Draft>): Draft => ({ ...EMPTY, name: "releases", ...change });
const PROXY = draft({
  name: "central",
  type: "proxy",
  remoteUrl: " https://repo.example.org/maven2/ ",
});

const stored = (change: Partial<RepositoryOut>): RepositoryOut => ({
  name: "releases",
  format: "maven",
  type: "hosted",
  online: true,
  blob_store: "default",
  url_path: "/repository/releases/",
  hosted: { deployment_policy: "disable_redeploy" },
  format_config: { version_policy: "snapshot", layout_policy: "permissive" },
  proxy: null,
  group: null,
  status: null,
  ...change,
});

describe("the deployment policy of a hosted repository (H1)", () => {
  test.each([
    // A release is deployed once: a Maven repository for releases refuses a second time.
    [{ format: "maven", versionPolicy: "release" }, "disable_redeploy"],
    // A snapshot is replaced by its nature, and a mixed repository takes snapshots.
    [{ format: "maven", versionPolicy: "snapshot" }, "allow_redeploy"],
    [{ format: "maven", versionPolicy: "mixed" }, "allow_redeploy"],
    // The version policy is Maven's: of another format it says nothing.
    [{ format: "npm", versionPolicy: "release" }, "allow_redeploy"],
    [{ format: "raw", versionPolicy: "release" }, "allow_redeploy"],
    [{ format: "docker", versionPolicy: "release" }, "allow_redeploy"],
  ])("is the server's own until one is chosen: %o", (combination, policy) => {
    expect(policyOf(draft(combination))).toBe(policy);
    expect(createBody(draft(combination)).hosted).toEqual({ deployment_policy: policy });
  });

  test("is the one that was chosen, whatever the server would have given", () => {
    const chosen = draft({ deploymentPolicy: "allow_redeploy" });

    expect(policyOf(chosen)).toBe("allow_redeploy");
    expect(policyOf({ ...chosen, versionPolicy: "snapshot" })).toBe("allow_redeploy");
    expect(policyOf(draft({ format: "raw", deploymentPolicy: "read_only" }))).toBe("read_only");
  });

  test("of a repository that is there is the one the server holds", () => {
    // Made before the rule, or by somebody who chose: it is not the form's to change.
    const held = draftOf(stored({ hosted: { deployment_policy: "allow_redeploy" } }));

    expect(held.deploymentPolicy).toBe("allow_redeploy");
    expect(policyOf({ ...held, format: "maven", versionPolicy: "release" })).toBe("allow_redeploy");
    expect(updateBody(held).hosted).toEqual({ deployment_policy: "allow_redeploy" });
  });
});

describe("what is sent to make a repository", () => {
  test("a hosted Maven repository has its policies, and no part of another type", () => {
    expect(createBody(draft({ deploymentPolicy: "read_only", versionPolicy: "mixed" }))).toEqual({
      name: "releases",
      format: "maven",
      type: "hosted",
      online: true,
      blob_store: "default",
      hosted: { deployment_policy: "read_only" },
      proxy: null,
      group: null,
      format_config: { version_policy: "mixed", layout_policy: "strict" },
    });
  });

  test("a proxy has its remote, how long it trusts what it cached, and how it signs in", () => {
    const body = createBody({
      ...PROXY,
      contentMaxAge: "-1",
      metadataMaxAge: " 60 ",
      negativeCache: false,
      negativeCacheTtl: "5",
      authType: "basic",
      authUsername: " robot ",
      authSecret: "the secret ",
      blocked: true,
      autoBlock: false,
    });

    expect(body.hosted).toBeNull();
    expect(body.proxy).toEqual({
      remote_url: "https://repo.example.org/maven2/",
      content_max_age_minutes: -1,
      metadata_max_age_minutes: 60,
      negative_cache: { enabled: false, ttl_minutes: 5 },
      // The secret as it was typed: a space at its end may be part of it.
      remote_auth: { type: "basic", username: "robot", secret: "the secret " },
      blocked: true,
      auto_block: false,
    });
  });

  test("a secret that is not typed is not sent, so that the one that is stored is kept", () => {
    const kept = updateBody({ ...PROXY, authType: "bearer", authSecret: "", hasSecret: true });
    expect(kept.proxy?.remote_auth).toEqual({ type: "bearer", username: "", secret: null });

    // And a proxy that signs in with nothing sends neither a name nor a secret that was
    // typed before the choice was changed.
    const none = updateBody({ ...PROXY, authType: "none", authUsername: "x", authSecret: "y" });
    expect(none.proxy?.remote_auth).toEqual({ type: "none", username: "", secret: null });
  });

  test("a group has its members in order, and neither a blob store nor settings of the format", () => {
    const body = createBody(draft({ name: "all", type: "group", members: ["b", "a"] }));

    expect(body.group).toEqual({ members: ["b", "a"] });
    expect(body.blob_store).toBeNull(); // it stores nothing
    expect(body.format_config).toEqual({}); // a Maven group has no policy of its own
    expect([body.hosted, body.proxy]).toEqual([null, null]);
  });

  test("another format than Maven has no settings of its own", () => {
    expect(createBody(draft({ format: "npm" })).format_config).toEqual({});
    expect(hasMavenSettings({ format: "maven", type: "proxy" })).toBe(true);
    expect(hasMavenSettings({ format: "maven", type: "group" })).toBe(false);
    expect(hasMavenSettings({ format: "raw", type: "hosted" })).toBe(false);
  });

  test("what cannot change is not sent when a repository is changed", () => {
    const body = updateBody(draft({ online: false }));

    expect(Object.keys(body).sort()).toEqual([
      "format_config",
      "group",
      "hosted",
      "online",
      "proxy",
    ]);
    expect(body.online).toBe(false);
  });
});

describe("the form of a repository that is there", () => {
  test("starts from what the server holds", () => {
    const form = draftOf(stored({}));

    expect(form).toMatchObject({
      name: "releases",
      format: "maven",
      type: "hosted",
      deploymentPolicy: "disable_redeploy",
      versionPolicy: "snapshot",
      layoutPolicy: "permissive",
      blobStore: "default",
    });
  });

  test("of a proxy has everything but the secret, and knows that one is stored", () => {
    const form = draftOf(
      stored({
        type: "proxy",
        hosted: null,
        proxy: {
          remote_url: "https://repo.example.org/maven2",
          content_max_age_minutes: -1,
          metadata_max_age_minutes: 30,
          negative_cache: { enabled: false, ttl_minutes: 10 },
          remote_auth: { type: "basic", username: "robot", has_secret: true },
          blocked: true,
          auto_block: false,
        },
      }),
    );

    expect(form).toMatchObject({
      type: "proxy",
      remoteUrl: "https://repo.example.org/maven2",
      contentMaxAge: "-1",
      metadataMaxAge: "30",
      negativeCache: false,
      negativeCacheTtl: "10",
      authType: "basic",
      authUsername: "robot",
      authSecret: "",
      hasSecret: true,
      blocked: true,
      autoBlock: false,
    });
    // Saved as it stands, it keeps the secret and changes nothing.
    expect(updateBody(form).proxy).toMatchObject({
      remote_url: "https://repo.example.org/maven2",
      content_max_age_minutes: -1,
      remote_auth: { type: "basic", username: "robot", secret: null },
    });
  });

  test("of a group has its members, and of a format without settings none", () => {
    const form = draftOf(
      stored({
        type: "group",
        format: "raw",
        hosted: null,
        format_config: {},
        group: { members: ["a", "b"] },
        blob_store: null,
      }),
    );

    expect(form.members).toEqual(["a", "b"]);
    expect(form.layoutPolicy).toBe("strict"); // not shown, and not sent
    expect(updateBody(form)).toMatchObject({ group: { members: ["a", "b"] }, format_config: {} });
  });

  test("takes a type it does not know for what it shows no parts of", () => {
    expect(draftOf(stored({ type: "mirror" })).type).toBe("hosted");
  });
});

describe("what is wrong with a form before the server is asked", () => {
  test("nothing, with a hosted repository that has a name", () => {
    expect(problemsOf(draft({}), true)).toEqual({});
  });

  test.each([
    ["", "nameRule"],
    ["has space", "nameRule"],
    ["a/b", "nameRule"],
    ["x".repeat(65), "nameRule"],
    [".", "nameDots"],
    ["..", "nameDots"],
  ])("a name %j: %s", (name, problem) => {
    expect(problemsOf(draft({ name }), true).name).toBe(problem);
  });

  test("a name is not the form's to check once the repository is there", () => {
    expect(problemsOf(draft({ name: ".." }), false)).toEqual({});
  });

  test("a Docker repository is named as the first part of an image's name", () => {
    const docker = (name: string) => problemsOf(draft({ format: "docker", name }), true).name;

    expect(docker("images")).toBeUndefined();
    expect(docker("team-1.images_x")).toBeUndefined();
    expect(docker("Images")).toBe("dockerNameRule");
    expect(docker("images-")).toBe("dockerNameRule");
    expect(docker("my..images")).toBe("dockerNameRule");
    // The same name is a good one for another format.
    expect(problemsOf(draft({ format: "raw", name: "Images" }), true)).toEqual({});
  });

  test.each([
    "",
    "repo.example.org",
    "ftp://repo.example.org",
    "https://",
    "https://user:secret@repo.example.org",
    "https://repo.example.org/?a=1",
    "https://repo.example.org/#x",
    "javascript:alert(1)",
  ])("a remote address %j is none", (remoteUrl) => {
    expect(problemsOf({ ...PROXY, remoteUrl }, true).remoteUrl).toBe("remoteRule");
  });

  test("how long a proxy trusts what it cached is a whole number, from -1", () => {
    const ages = (contentMaxAge: string, metadataMaxAge: string) =>
      problemsOf({ ...PROXY, contentMaxAge, metadataMaxAge }, true);

    expect(ages("-1", "0")).toEqual({});
    expect(ages("-2", "1.5")).toMatchObject({
      contentMaxAge: "ageRule",
      metadataMaxAge: "ageRule",
    });
    expect(ages("", "ten").contentMaxAge).toBe("ageRule");
    expect(ages("99999999999999999999", "1").contentMaxAge).toBe("ageRule");
  });

  test("how long a missing path is remembered is at least a minute, when it is remembered at all", () => {
    expect(problemsOf({ ...PROXY, negativeCacheTtl: "0" }, true).negativeCacheTtl).toBe("ttlRule");
    expect(problemsOf({ ...PROXY, negativeCache: false, negativeCacheTtl: "0" }, true)).toEqual({});
  });

  test("a proxy that signs in needs what it signs in with, unless a secret is stored", () => {
    const basic = { ...PROXY, authType: "basic" };

    expect(problemsOf(basic, true)).toEqual({
      authUsername: "usernameNeeded",
      authSecret: "secretNeeded",
    });
    expect(problemsOf({ ...basic, authUsername: "robot", hasSecret: true }, false)).toEqual({});
    expect(problemsOf({ ...PROXY, authType: "bearer" }, true)).toEqual({
      authSecret: "secretNeeded",
    });
    expect(problemsOf({ ...PROXY, authType: "bearer", authSecret: "t" }, true)).toEqual({});
  });

  test("what a hosted repository or a group does not have is not checked", () => {
    expect(problemsOf(draft({ remoteUrl: "nonsense", contentMaxAge: "x" }), true)).toEqual({});
    expect(problemsOf(draft({ type: "group", remoteUrl: "" }), true)).toEqual({});
  });
});

describe("APT, YUM and apk", () => {
  const KEYS = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n...\n-----END PGP PUBLIC KEY BLOCK-----\n";

  test("are formats a repository can have", () => {
    expect(FORMATS).toEqual(expect.arrayContaining(["apt", "yum", "apk"]));
  });

  test("a hosted APT repository is made with its suite, and the server's own unless one is typed", () => {
    expect(createBody(draft({ format: "apt" })).format_config).toEqual({ suite: "stable" });
    expect(createBody(draft({ format: "apt", suite: " trixie " })).format_config).toEqual({
      suite: "trixie",
    });
  });

  test("a hosted YUM repository is made with the depth of its metadata, as a number", () => {
    expect(createBody(draft({ format: "yum" })).format_config).toEqual({ repodata_depth: 0 });
    expect(createBody(draft({ format: "yum", repodataDepth: " 2 " })).format_config).toEqual({
      repodata_depth: 2,
    });
  });

  test("a hosted apk repository, and a group of any of them, has no settings of its own", () => {
    expect(createBody(draft({ format: "apk" })).format_config).toEqual({});
    for (const format of ["apt", "yum", "apk"]) {
      expect(createBody(draft({ format, type: "group" })).format_config).toEqual({});
    }
  });

  test("a proxy always sends its remote's keys: settings that are sent are replaced whole", () => {
    for (const format of ["apt", "yum", "apk"]) {
      const proxy = { ...PROXY, format };
      expect(createBody({ ...proxy, remoteKeys: KEYS }).format_config).toEqual({
        remote_keys: KEYS,
      });
      // Saved without a change, the keys it has are sent back, and kept.
      expect(updateBody({ ...proxy, remoteKeys: KEYS }).format_config).toEqual({
        remote_keys: KEYS,
      });
      expect(updateBody(proxy).format_config).toEqual({ remote_keys: "" });
    }
  });

  test("the form of one that is there starts from its suite, its depth and its keys", () => {
    const apt = draftOf(stored({ format: "apt", format_config: { suite: "trixie" } }));
    const yum = draftOf(stored({ format: "yum", format_config: { repodata_depth: 2 } }));
    const mirror = draftOf(
      stored({ format: "apk", type: "proxy", format_config: { remote_keys: KEYS } }),
    );

    expect(apt.suite).toBe("trixie");
    expect(yum.repodataDepth).toBe("2");
    expect(mirror.remoteKeys).toBe(KEYS);
    // Sent back as they are held: the server takes again what it has.
    expect(updateBody(apt).format_config).toEqual({ suite: "trixie" });
    expect(updateBody(yum).format_config).toEqual({ repodata_depth: 2 });
    // One made before there were settings has the server's own.
    expect(draftOf(stored({ format: "apt", format_config: {} })).suite).toBe("stable");
    expect(draftOf(stored({ format: "yum", format_config: {} })).repodataDepth).toBe("0");
  });

  test.each([
    ["", "suiteRule"],
    ["-x", "suiteRule"],
    ["has space", "suiteRule"],
    ["x".repeat(65), "suiteRule"],
    ["trixie", undefined],
    ["stable-updates", undefined],
    ["9.4", undefined],
  ])("a suite %j: %s", (suite, problem) => {
    expect(problemsOf(draft({ format: "apt", suite }), true).suite).toBe(problem);
  });

  test.each([
    ["", "depthRule"],
    ["-1", "depthRule"],
    ["6", "depthRule"],
    ["1.5", "depthRule"],
    ["0", undefined],
    ["5", undefined],
  ])("a depth %j: %s", (repodataDepth, problem) => {
    expect(problemsOf(draft({ format: "yum", repodataDepth }), true).repodataDepth).toBe(problem);
  });

  test("a suite and a depth are checked only when they are chosen: as one is made, hosted", () => {
    expect(problemsOf(draft({ format: "apt", suite: "" }), false)).toEqual({});
    expect(problemsOf(draft({ format: "yum", repodataDepth: "9" }), false)).toEqual({});
    expect(problemsOf(draft({ format: "apt", type: "group", suite: "" }), true)).toEqual({});
    expect(problemsOf({ ...PROXY, format: "yum", repodataDepth: "9" }, true)).toEqual({});
  });

  test("a proxy of them is given its remote's keys, and a hosted one or a group has a key of its own", () => {
    for (const format of ["apt", "yum", "apk"]) {
      expect(takesRemoteKeys({ format, type: "proxy" })).toBe(true);
      expect(takesRemoteKeys({ format, type: "hosted" })).toBe(false);
      expect(hasSigningKey({ format, type: "hosted" })).toBe(true);
      expect(hasSigningKey({ format, type: "group" })).toBe(true);
      expect(hasSigningKey({ format, type: "proxy" })).toBe(false);
    }
    expect(takesRemoteKeys({ format: "maven", type: "proxy" })).toBe(false);
    expect(hasSigningKey({ format: "raw", type: "hosted" })).toBe(false);
  });
});

describe("NuGet", () => {
  const SYMBOLS = "https://symbols.nuget.org/download/symbols";

  test("is a format a repository can have, hosted by default a version pushed once", () => {
    expect(FORMATS).toContain("nuget");
    // As nuget.org takes one: a second push of a version is refused (D6).
    expect(policyOf(draft({ format: "nuget" }))).toBe("disable_redeploy");
    expect(createBody(draft({ format: "nuget" })).hosted).toEqual({
      deployment_policy: "disable_redeploy",
    });
    expect(createBody(draft({ format: "nuget" })).format_config).toEqual({});
    expect(createBody(draft({ format: "nuget", type: "group" })).format_config).toEqual({});
  });

  test("a proxy is made with its protocol, V3 unless V2 is chosen, and a symbol server if one is given", () => {
    const proxy = { ...PROXY, format: "nuget" };

    expect(isNuGetProxy(proxy)).toBe(true);
    expect(isNuGetProxy({ ...proxy, type: "hosted" })).toBe(false);
    expect(createBody(proxy).format_config).toEqual({ protocol: "v3" });
    expect(createBody({ ...proxy, protocol: "v2" }).format_config).toEqual({ protocol: "v2" });
    expect(createBody({ ...proxy, symbolUrl: ` ${SYMBOLS} ` }).format_config).toEqual({
      protocol: "v3",
      symbol_url: SYMBOLS,
    });
  });

  test("the form of a proxy that is there starts from its protocol and its symbol server, and sends them back", () => {
    const held = draftOf(
      stored({
        format: "nuget",
        type: "proxy",
        format_config: { protocol: "v2", symbol_url: SYMBOLS },
      }),
    );

    expect([held.protocol, held.symbolUrl]).toEqual(["v2", SYMBOLS]);
    expect(updateBody(held).format_config).toEqual({ protocol: "v2", symbol_url: SYMBOLS });
    // One made before there were settings speaks V3, as the server has it.
    expect(draftOf(stored({ format: "nuget", type: "proxy", format_config: {} })).protocol).toBe(
      "v3",
    );
  });

  test.each([
    ["", undefined],
    [SYMBOLS, undefined],
    ["ftp://symbols.example.org", "symbolUrlRule"],
    ["https://user:secret@symbols.example.org", "symbolUrlRule"],
    ["not an address", "symbolUrlRule"],
  ])("a symbol server %j: %s", (symbolUrl, problem) => {
    expect(problemsOf({ ...PROXY, format: "nuget", symbolUrl }, true).symbolUrl).toBe(problem);
    // Of another format it is not the form's.
    expect(problemsOf({ ...PROXY, symbolUrl }, true).symbolUrl).toBeUndefined();
  });
});

describe("the order of a group's members", () => {
  test("a member moves one place up or down", () => {
    expect(moved(["a", "b", "c"], "c", -1)).toEqual(["a", "c", "b"]);
    expect(moved(["a", "b", "c"], "a", 1)).toEqual(["b", "a", "c"]);
  });

  test("the first does not move up, the last not down, and what is no member not at all", () => {
    const members = ["a", "b"];

    expect(moved(members, "a", -1)).toBe(members);
    expect(moved(members, "b", 1)).toBe(members);
    expect(moved(members, "z", 1)).toBe(members);
  });
});

describe("the addresses of a repository's settings", () => {
  test("are under the list, with the name as one segment", () => {
    expect(repositorySettingsHref("releases")).toBe("/admin/repositories/releases");
    expect(repositorySettingsHref("odd name#")).toBe("/admin/repositories/odd%20name%23");
    expect(parseRepositorySettings("/admin/repositories/odd%20name%23")).toEqual({
      name: "odd name#",
    });
    expect(parseRepositorySettings(MANAGE_REPOSITORIES)).toBeNull();
    expect(parseRepositorySettings("/admin/repositories/a/b")).toBeNull();
  });

  test("the form for a new one is where no repository's name can be", () => {
    expect(NEW_REPOSITORY).toBe("/admin/repositories/~new");
    // A repository may be called "new", and its settings are then its own page.
    expect(repositorySettingsHref("new")).toBe("/admin/repositories/new");
  });
});

describe("the remote a proxy is made with", () => {
  const making = (change: Partial<Draft>): Draft => ({ ...EMPTY, ...change });
  // As the server gives them (GET /formats).
  const REMOTES = publicRemotesOf([
    { name: "maven", types: [], public_remotes: { "": "https://repo1.maven.org/maven2" } },
    { name: "npm", types: [], public_remotes: { "": "https://registry.npmjs.org" } },
    { name: "pypi", types: [], public_remotes: { "": "https://pypi.org" } },
    { name: "docker", types: [], public_remotes: { "": "https://registry-1.docker.io" } },
    { name: "apt", types: [], public_remotes: { "": "http://deb.debian.org/debian" } },
    { name: "apk", types: [], public_remotes: { "": "https://dl-cdn.alpinelinux.org/alpine" } },
    {
      name: "nuget",
      types: [],
      public_remotes: {
        "": "https://api.nuget.org/v3/index.json",
        v3: "https://api.nuget.org/v3/index.json",
        v2: "https://community.chocolatey.org/api/v2/",
      },
    },
    { name: "yum", types: [], public_remotes: {} },
    { name: "raw", types: [], public_remotes: {} },
  ]);

  test.each([
    ["maven", "v3", "https://repo1.maven.org/maven2"],
    ["npm", "v3", "https://registry.npmjs.org"],
    ["pypi", "v3", "https://pypi.org"],
    ["docker", "v3", "https://registry-1.docker.io"],
    ["apt", "v3", "http://deb.debian.org/debian"],
    ["apk", "v3", "https://dl-cdn.alpinelinux.org/alpine"],
    ["nuget", "v3", "https://api.nuget.org/v3/index.json"],
    ["nuget", "v2", "https://community.chocolatey.org/api/v2/"],
    ["yum", "v3", ""],
    ["raw", "v3", ""],
  ])("of %s (%s) is its public one, or none where there is no one", (format, protocol, remote) => {
    expect(defaultRemoteOf(making({ format, type: "proxy", protocol }), REMOTES)).toBe(remote);
    expect(defaultRemoteOf(making({ format, type: "hosted", protocol }), REMOTES)).toBe("");
  });

  test("is given as a proxy is chosen, and follows the format, the type and the protocol", () => {
    let held = making({});
    const change = (one: Partial<Draft>) => {
      held = { ...held, ...withDefaultRemote(held, one, REMOTES) };
      return held.remoteUrl;
    };

    expect(change({ name: "mirror" })).toBe("");
    expect(change({ type: "proxy" })).toBe("https://repo1.maven.org/maven2");
    expect(change({ format: "npm" })).toBe("https://registry.npmjs.org");
    expect(change({ format: "nuget" })).toBe("https://api.nuget.org/v3/index.json");
    expect(change({ protocol: "v2" })).toBe("https://community.chocolatey.org/api/v2/");
    expect(change({ format: "yum" })).toBe("");
    expect(change({ format: "docker" })).toBe("https://registry-1.docker.io");
    expect(change({ type: "group" })).toBe("");
  });

  test("an address that was typed is kept, whatever else changes", () => {
    let held = making({ type: "proxy", remoteUrl: "https://mirror.example.org/maven2" });
    for (const one of [
      { format: "npm" },
      { type: "hosted" as const },
      { type: "proxy" as const },
    ]) {
      held = { ...held, ...withDefaultRemote(held, one, REMOTES) };
      expect(held.remoteUrl).toBe("https://mirror.example.org/maven2");
    }
    expect(withDefaultRemote(held, { remoteUrl: "" }, REMOTES)).toEqual({ remoteUrl: "" });
  });

  test("is none while the server has not said what its formats' are", () => {
    expect(defaultRemoteOf(making({ format: "maven", type: "proxy" }), {})).toBe("");
  });
});
