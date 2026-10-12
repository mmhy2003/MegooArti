import { expect, test } from "vitest";

import { metadata as password } from "./(shell)/account/password/page";
import { metadata as preferences } from "./(shell)/account/preferences/page";
import { metadata as tokens } from "./(shell)/account/tokens/page";
import { metadata as anonymousAccess } from "./(shell)/admin/anonymous-access/page";
import { metadata as blobStores } from "./(shell)/admin/blob-stores/page";
import { generateMetadata as repositorySettings } from "./(shell)/admin/repositories/[repository]/page";
import { metadata as manageRepositories } from "./(shell)/admin/repositories/page";
import { metadata as newRepository } from "./(shell)/admin/repositories/~new/page";
import { metadata as role } from "./(shell)/admin/roles/[name]/page";
import { metadata as newRole } from "./(shell)/admin/roles/~new/page";
import { metadata as roles } from "./(shell)/admin/roles/page";
import { metadata as user } from "./(shell)/admin/users/[id]/page";
import { metadata as newUser } from "./(shell)/admin/users/new/page";
import { metadata as system } from "./(shell)/admin/system/page";
import { metadata as users } from "./(shell)/admin/users/page";
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

test("the screens of the account and of the administration have titles of their own", () => {
  expect([tokens.title, preferences.title]).toEqual(["API tokens", "Preferences"]);
  expect([users.title, newUser.title, user.title]).toEqual(["Users", "New user", "User"]);
  expect([roles.title, newRole.title, role.title]).toEqual(["Roles", "New role", "Role"]);
  expect(anonymousAccess.title).toBe("Anonymous access");
});

test("the screens of the repositories' and the system's administration have titles", async () => {
  expect([manageRepositories.title, newRepository.title]).toEqual([
    "Manage repositories",
    "New repository",
  ]);
  expect([blobStores.title, system.title]).toEqual(["Blob stores", "System"]);
  // A repository's settings are titled by it, and so told from its folders.
  expect(await repositorySettings({ params: Promise.resolve({ repository: "releases" }) })).toEqual(
    { title: "Settings of releases" },
  );
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
