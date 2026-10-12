import { expect, test } from "vitest";

import { metadata as password } from "./(shell)/account/password/page";
import { generateMetadata as browse } from "./(shell)/browse/[repository]/[[...path]]/page";
import { generateMetadata as component } from "./(shell)/components/[repository]/[id]/page";
import { metadata as home } from "./(shell)/page";
import { metadata as search } from "./(shell)/search/page";
import { generateMetadata as uploadTo } from "./(shell)/upload/[repository]/page";
import { metadata as upload } from "./(shell)/upload/page";
import { metadata as signIn } from "./login/page";
import { metadata as notFound } from "./not-found";
import { TITLES } from "./titles";

// Each route names its page (WCAG 2.4.2). Next.js writes the route's title again at
// every navigation, so it is the route that has to say it, not the screen.
test("each screen has a title of its own", () => {
  expect([
    home.title,
    signIn.title,
    password.title,
    notFound.title,
    search.title,
    upload.title,
  ]).toEqual([
    "Repositories",
    "Sign in",
    "Change password",
    "There is nothing at this address",
    "Search",
    "Upload",
  ]);
});

test("a screen about one repository is titled by it, as the address names it", async () => {
  const at = (repository: string) => ({ params: Promise.resolve({ repository }) });

  expect(await browse(at("releases"))).toEqual({ title: "releases" });
  expect(await component(at("my%20files"))).toEqual({ title: "my files" });
  expect(await uploadTo(at("releases"))).toEqual({ title: "Upload to releases" });
  expect(await uploadTo(at("$&"))).toEqual({ title: "Upload to $&" });
  expect(await browse(at("%E0%A4%A"))).toEqual({ title: "%E0%A4%A" }); // no address of ours
});

test("a title is the screen, then the product", () => {
  expect(TITLES).toEqual({ default: "MegooArti", template: "%s · MegooArti" });
});
