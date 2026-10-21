import { createTranslator } from "next-intl";
import { describe, expect, test } from "vitest";

import messages from "../../messages/en.json";
import { criteriaInWords } from "./cleanup";
import {
  CLEANUP_POLICIES,
  cleanupPolicyHref,
  NEW_CLEANUP_POLICY,
  parseCleanupPolicy,
} from "./paths";

const t = createTranslator({ locale: "en", messages, namespace: "cleanup.criteria" });
const none = { updated_days: null, downloaded_days: null, release_type: null, asset_pattern: null };

describe("a cleanup policy's criteria, in words (W2)", () => {
  test("say each criterion the policy has, in the order of the form", () => {
    expect(criteriaInWords({ ...none, updated_days: 14, release_type: "prerelease" }, t)).toBe(
      "Not updated in 14 days, pre-releases",
    );
    expect(
      criteriaInWords(
        {
          updated_days: 14,
          downloaded_days: 90,
          release_type: "release",
          asset_pattern: "/.*\\.tmp",
        },
        t,
      ),
    ).toBe(
      "Not updated in 14 days, not downloaded in 90 days, releases, a file matching /.*\\.tmp",
    );
  });

  test("say one day as one", () => {
    expect(criteriaInWords({ ...none, downloaded_days: 1 }, t)).toBe("Not downloaded in 1 day");
  });

  test("begin with a capital, whichever comes first", () => {
    expect(criteriaInWords({ ...none, release_type: "prerelease" }, t)).toBe("Pre-releases");
  });
});

describe("a cleanup policy's address", () => {
  test("is its name, made safe, under the list", () => {
    expect(CLEANUP_POLICIES).toBe("/admin/cleanup-policies");
    expect(cleanupPolicyHref("a b")).toBe("/admin/cleanup-policies/a%20b");
    expect(parseCleanupPolicy("/admin/cleanup-policies/a%20b")).toEqual({ name: "a b" });
  });

  test("of a new one is no policy's", () => {
    expect(NEW_CLEANUP_POLICY).toBe("/admin/cleanup-policies/~new");
    expect(parseCleanupPolicy(NEW_CLEANUP_POLICY)).toBeNull();
  });
});
