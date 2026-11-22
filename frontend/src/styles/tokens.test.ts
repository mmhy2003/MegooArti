// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, test } from "vitest";

const css = readFileSync("src/styles/tokens.css", "utf8");

type Tokens = Record<string, string>;

/** The tokens of one mode: the first block that is written for it. */
function tokensOf(mode: "dark" | "light"): Tokens {
  const block = new RegExp(`:root\\[data-theme="${mode}"\\]\\s*\\{([^}]*)\\}`).exec(css);
  if (block === null) throw new Error(`no tokens for the ${mode} mode`);
  const found: Tokens = {};
  for (const [, name, value] of (block[1] ?? "").matchAll(/--mg-([a-z-]+):\s*([^;]+);/g)) {
    if (name && value) found[name] = value.trim();
  }
  return found;
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  const [red = 0, green = 0, blue = 0] = channels.map((value) =>
    value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** The contrast of two colours, as WCAG 2.1 computes it: from 1 to 21. */
function contrast(one: string, other: string): number {
  const [lighter = 0, darker = 0] = [luminance(one), luminance(other)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

const MODES = { dark: tokensOf("dark"), light: tokensOf("light") };
const SURFACES = ["page", "panel", "raised", "field"];
// What is read: 4.5 to 1 on every surface it may stand on (WCAG 2.1 AA, 1.4.3).
const TEXT = ["fg", "fg-muted", "ink-cyan", "ink-violet", "ink-ok", "ink-warn", "ink-bad"];
// What is seen, not read: borders of controls, icons, the focus ring. 3 to 1 (1.4.11).
const SEEN = [
  "line-strong",
  "neon-cyan",
  "neon-violet",
  "ok",
  "warn",
  "bad",
  "focus",
  "primary",
  "danger",
];
// Text on a filled control.
const FILLED = [
  ["on-primary", "primary"],
  ["on-danger", "danger"],
] as const;

function colour(tokens: Tokens, name: string): string {
  const value = tokens[name];
  if (value === undefined || !/^#[0-9a-f]{6}$/.test(value)) {
    throw new Error(`--mg-${name} is not a six-digit colour: ${value}`);
  }
  return value;
}

// The KB's "Cyberpunk Theme", rev 3, under this project's names (MA-1). The light mode's
// ink-cyan, ink-ok, ink-warn and ink-bad are left out: they are the KB's colour darkened
// by the least that can be read on every surface.
const KB: Record<"light" | "dark", Tokens> = {
  light: {
    page: "#f6f3ff",
    panel: "#ffffff",
    raised: "#ece6ff",
    field: "#ffffff",
    line: "#d6ccf5",
    "line-strong": "#6b5f99",
    fg: "#1a0b3d",
    "fg-muted": "#6b5f99",
    primary: "#007a8f",
    "on-primary": "#ffffff",
    danger: "#d4004f",
    "on-danger": "#ffffff",
    "neon-cyan": "#0090a8",
    "neon-violet": "#6d28d9",
    "ink-violet": "#6d28d9",
    ok: "#1f8f2c",
    warn: "#a16207",
    bad: "#d4004f",
    focus: "#6d28d9",
    grid: "rgba(80, 40, 200, 0.06)",
  },
  dark: {
    page: "#0e0f13",
    panel: "#17191f",
    raised: "#121318",
    field: "#0e0f13",
    line: "#2a2d36",
    "line-strong": "#8e94a3",
    fg: "#eceef3",
    "fg-muted": "#8e94a3",
    primary: "#22e4ff",
    "on-primary": "#0e0f13",
    danger: "#ff3d81",
    "on-danger": "#0e0f13",
    "neon-cyan": "#22e4ff",
    "ink-cyan": "#22e4ff",
    "neon-violet": "#c084fc",
    "ink-violet": "#c084fc",
    ok: "#5bff9a",
    "ink-ok": "#5bff9a",
    warn: "#ffe14d",
    "ink-warn": "#ffe14d",
    bad: "#ff3d81",
    "ink-bad": "#ff3d81",
    focus: "#c084fc",
    grid: "rgba(255, 255, 255, 0.03)",
  },
};
// What the light mode's ink tones were darkened from.
const KB_INK = {
  "ink-cyan": "#007a8f",
  "ink-ok": "#1a7a27",
  "ink-warn": "#a16207",
  "ink-bad": "#d4004f",
};

test.each(["light", "dark"] as const)("the %s mode has the KB theme's colours", (mode) => {
  const ours = Object.fromEntries(Object.keys(KB[mode]).map((name) => [name, MODES[mode][name]]));
  expect(ours).toEqual(KB[mode]);
});

test.each(Object.entries(KB_INK))("the light %s is the KB's, or darker", (name, theirs) => {
  expect(luminance(colour(MODES.light, name))).toBeLessThanOrEqual(luminance(theirs));
});

test("there is one secondary text tone, and no magenta or acid", () => {
  for (const gone of ["fg-subtle", "neon-magenta", "ink-magenta", "neon-acid", "ink-acid"]) {
    expect(Object.keys(MODES.dark)).not.toContain(gone);
    expect(Object.keys(MODES.light)).not.toContain(gone);
  }
});

describe.each(Object.entries(MODES))("the %s mode", (_mode, tokens) => {
  test.each(TEXT.flatMap((text) => SURFACES.map((surface) => [text, surface] as const)))(
    "%s can be read on %s",
    (text, surface) => {
      expect(contrast(colour(tokens, text), colour(tokens, surface))).toBeGreaterThanOrEqual(4.5);
    },
  );

  test.each(SEEN.flatMap((seen) => SURFACES.map((surface) => [seen, surface] as const)))(
    "%s can be seen on %s",
    (seen, surface) => {
      expect(contrast(colour(tokens, seen), colour(tokens, surface))).toBeGreaterThanOrEqual(3);
    },
  );

  test.each(FILLED)("%s can be read on %s", (text, fill) => {
    expect(contrast(colour(tokens, text), colour(tokens, fill))).toBeGreaterThanOrEqual(4.5);
  });

  test("the focus ring is not the colour of what it surrounds", () => {
    for (const other of ["primary", "danger", "line-strong", "neon-cyan"]) {
      expect(colour(tokens, "focus")).not.toBe(colour(tokens, other));
    }
  });
});

test("both modes define the same tokens, and neither is a fallback for the other", () => {
  expect(Object.keys(MODES.light).sort()).toEqual(Object.keys(MODES.dark).sort());
  expect(Object.keys(MODES.dark).length).toBeGreaterThan(25);
  for (const surface of SURFACES) {
    expect(MODES.light[surface]).not.toBe(MODES.dark[surface]);
  }
});

test("the contrast is computed as the standard computes it", () => {
  expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
  expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2); // the well-known near miss
  expect(contrast("#ffffff", "#ffffff")).toBe(1);
});

test("whoever asks for less motion gets none, and no glow", () => {
  const reduced = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$/.exec(css);
  expect(reduced).not.toBeNull();
  const block = reduced?.[1] ?? "";
  expect(block).toContain(':root[data-theme="dark"]');
  expect(block).toContain(':root[data-theme="light"]');
  expect(block).toMatch(/--mg-duration-fast:\s*0ms/);
  expect(block).toMatch(/--mg-duration:\s*0ms/);
  expect(block).toMatch(/--mg-glow-sm:\s*none/);
  expect(block).toMatch(/--mg-glow-md:\s*none/);
});
