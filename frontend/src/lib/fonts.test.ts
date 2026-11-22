// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { expect, test } from "vitest";

const FILES = {
  "geist-latin-wght-normal.woff2": "GEIST-LICENSE.txt",
  "geist-mono-latin-wght-normal.woff2": "GEIST-MONO-LICENSE.txt",
  "orbitron-latin-700-normal.woff2": "ORBITRON-LICENSE.txt",
};

test("the three typefaces are in the repository, each with its licence beside it (UI-14)", () => {
  expect(readdirSync("src/fonts").sort()).toEqual(
    [...Object.keys(FILES), ...Object.values(FILES)].sort(),
  );
  const loaded = readFileSync("src/lib/fonts.ts", "utf8");
  for (const [font, licence] of Object.entries(FILES)) {
    expect(readFileSync(`src/fonts/${font}`).subarray(0, 4).toString("latin1")).toBe("wOF2");
    expect(readFileSync(`src/fonts/${licence}`, "utf8")).toContain("SIL Open Font License");
    expect(loaded).toContain(`../fonts/${font}`);
  }
});
