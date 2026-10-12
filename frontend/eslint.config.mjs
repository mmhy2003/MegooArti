import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// The properties whose value a person reads or hears.
const READ =
  "/^(aria-label|aria-description|aria-valuetext|aria-roledescription|title|alt|placeholder|label|hint)$/";
const FROM_MESSAGES = "Text a person reads or hears comes from messages/en.json (UI-4).";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Text a person reads comes from messages/en.json (UI-4), never from markup.
    files: ["src/**/*.tsx"],
    ignores: ["src/**/*.test.tsx", "src/test/**"],
    rules: {
      "react/jsx-no-literals": ["error", { noStrings: true, ignoreProps: true }],
      // That rule cannot tell a property that is read out from a class name: this one can.
      "no-restricted-syntax": [
        "error",
        { selector: `JSXAttribute[name.name=${READ}] > Literal`, message: FROM_MESSAGES },
        {
          selector: `JSXAttribute[name.name=${READ}] > JSXExpressionContainer > :matches(Literal, TemplateLiteral)`,
          message: FROM_MESSAGES,
        },
      ],
    },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "playwright-report/**",
    "test-results/**",
    "src/lib/api/schema.d.ts",
  ]),
]);

export default eslintConfig;
