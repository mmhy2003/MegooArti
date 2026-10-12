// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "vitest";

/** Every source file a colour could be written in, except where the tokens are defined. */
function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name).replaceAll("\\", "/");
    if (entry.isDirectory()) return path === "src/test" ? [] : sources(path);
    const kept = /\.(tsx?|css)$/.test(entry.name) && !/\.(test|d)\.tsx?$/.test(entry.name);
    return kept && path !== "src/styles/tokens.css" ? [path] : [];
  });
}

// A colour written out, in any of the ways CSS and Tailwind have for it.
const LITERALS = [
  /#[0-9a-fA-F]{3,8}\b/, // #0ff, #00e5ff
  /\b(rgb|rgba|hsl|hsla|oklch|oklab|lab|lch|hwb)\(/, // rgb(0 229 255)
  // Tailwind's own palette, which globals.css removes: text-red-500, bg-slate-900/50
  /\b(text|bg|border|ring|outline|fill|stroke|shadow|from|via|to|decoration|divide|accent|caret)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|black|white)(-\d{2,3})?\b/,
];

test("a colour is written in the tokens and nowhere else (UI-12)", () => {
  const files = sources("src");
  expect(files.length).toBeGreaterThan(5); // it is looking somewhere

  const found = files.flatMap((file) =>
    readFileSync(file, "utf8")
      .split("\n")
      .flatMap((line, index) =>
        LITERALS.some((literal) => literal.test(line))
          ? [`${file}:${index + 1}: ${line.trim()}`]
          : [],
      ),
  );

  expect(found).toEqual([]);
});

test("the check finds what it is there to find", () => {
  const caught = (line: string) => LITERALS.some((literal) => literal.test(line));

  expect(caught('className="text-[#00e5ff]"')).toBe(true);
  expect(caught("color: rgb(0 229 255 / 0.4);")).toBe(true);
  expect(caught('className="bg-slate-900 text-white"')).toBe(true);
  expect(caught('className="border-red-500/50"')).toBe(true);
  expect(caught('className="border-neon-cyan bg-panel text-ink-cyan"')).toBe(false);
  expect(caught('<a href="#main">')).toBe(false);
  expect(caught("background-color: var(--mg-page);")).toBe(false);
});
