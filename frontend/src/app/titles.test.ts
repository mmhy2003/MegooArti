import { expect, test } from "vitest";

import { metadata as password } from "./(shell)/account/password/page";
import { metadata as home } from "./(shell)/page";
import { metadata as signIn } from "./login/page";
import { metadata as notFound } from "./not-found";
import { TITLES } from "./titles";

// Each route names its page (WCAG 2.4.2). Next.js writes the route's title again at
// every navigation, so it is the route that has to say it, not the screen.
test("each screen has a title of its own", () => {
  expect([home.title, signIn.title, password.title, notFound.title]).toEqual([
    "Repositories",
    "Sign in",
    "Change password",
    "There is nothing at this address",
  ]);
});

test("a title is the screen, then the product", () => {
  expect(TITLES).toEqual({ default: "MegooArti", template: "%s · MegooArti" });
});
