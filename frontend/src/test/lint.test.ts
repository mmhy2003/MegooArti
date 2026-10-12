// @vitest-environment node
import { ESLint } from "eslint";
import { expect, test } from "vitest";

const eslint = new ESLint();
// The two rules that keep text out of the source. What else the lint says is not asked here.
const RULES = ["react/jsx-no-literals", "no-restricted-syntax"];
const SLOW = 60_000; // the lint reads its whole configuration for the first file

/** Which of them a screen with this markup breaks, as the project's own lint finds it. */
async function broken(markup: string): Promise<string[]> {
  const source = `export function Sample({ said }: { said: string }) {\n  return ${markup};\n}\n`;
  const [result] = await eslint.lintText(source, { filePath: "src/screens/sample.tsx" });
  const found = (result?.messages ?? []).map((message) => message.ruleId ?? message.message);
  return found.filter((rule) => RULES.includes(rule));
}

// What a person reads or hears is in messages/en.json (UI-4): the lint holds it there.
test(
  "text written into markup is refused",
  async () => {
    expect(await broken("<p>Hello</p>")).toEqual(["react/jsx-no-literals"]);
    expect(await broken("<p>{said}</p>")).toEqual([]);
  },
  SLOW,
);

test.each([
  '<button aria-label="Close" />',
  '<abbr title="Mebibyte">{said}</abbr>',
  '<img alt="A diagram" src="/a.svg" />',
  '<input placeholder="Search" />',
  '<input aria-label={"Search"} />',
  "<input aria-label={`Search ${said}`} />",
  '<progress aria-valuetext="Half" />',
])(
  "text written into a property that is read out is refused: %s",
  async (markup) => {
    expect(await broken(markup)).toEqual(["no-restricted-syntax"]);
  },
  SLOW,
);

test.each([
  "<button aria-label={said} />",
  '<button type="button" className="p-4" aria-hidden="true" role="status" />',
  '<a href="/search" aria-current="page">{said}</a>',
  '<input aria-keyshortcuts="/" name="q" />',
])(
  "what nobody reads is let be: %s",
  async (markup) => {
    expect(await broken(markup)).toEqual([]);
  },
  SLOW,
);
