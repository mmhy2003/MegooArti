import axe from "axe-core";
import { expect } from "vitest";

/**
 * Fails if what is rendered breaks an accessibility rule: a control without a name, a
 * field without a label, a wrong role. Colour contrast is not judged here, because
 * jsdom draws nothing: the tokens' own test computes it, and the browser tests see it.
 */
export async function expectAccessible(container: Element = document.body): Promise<void> {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  const found = results.violations.map(
    (violation) => `${violation.id}: ${violation.nodes.map((node) => node.html).join(" | ")}`,
  );
  expect(found).toEqual([]);
}
