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
  draftOf,
  EMPTY,
  hasMavenSettings,
  moved,
  problemsOf,
  updateBody,
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
