# Web UI design

**Date:** 2026-10-12
**Status:** Sections 1 to 11 are settled and are what plan 9 builds. Section 12 is an outline of plan 10, to be settled when that plan starts.
**Requirements:** [docs/BRD.md](../../BRD.md) UI-1 to UI-15, NFR-9, NFR-10, NFR-17, TC-2, TC-4, API-1, and the screens of every Phase 1 function.

## 1. Purpose

Give MegooArti a web UI: the place where a developer finds a package and copies how to use it, and where an administrator configures repositories, storage and access. It is written with Next.js and uses only the public REST API.

Success means:

- One address serves the UI, the API and the package clients, so one base URL setting is true for all of them.
- The UI works with no access to any other host: every font, icon and script is served by MegooArti.
- Both modes, light and dark, are complete, meet WCAG 2.1 AA contrast, and never flash the wrong one on load.
- Every screen can be used with the keyboard alone and names its parts to a screen reader.
- A browser that is handed hostile content from a repository cannot be made to run it: the UI has a strict content security policy.

## 2. Scope

One design, delivered as two plans.

| Plan | Contents |
| --- | --- |
| **9, the foundation** | The frontend project and its tooling; the design tokens and the cyberpunk theme in both modes; the component set every screen is made of; translation resources; the API client and the session; the application shell and its navigation; sign-in, sign-out and changing a password; the home screen (the repositories a caller may browse); the frontend image, the gateway and Compose; tests in a real browser |
| **10, the screens** | Browsing a repository as folders, files and components; search; upload; deleting; API tokens; and administration: repositories, blob stores, users, roles, anonymous access and system settings |

**Out of scope:**

| Item | Where it goes |
| --- | --- |
| A second language | Not planned. Text is in translation resources (UI-4), so one can be added |
| Server-side rendering of data | Not planned. The Next.js server renders the shell; the browser asks the API |
| TLS, HSTS, compression at the edge | The operator's reverse proxy (NFR-8) |
| Phase 2 screens (LDAP, OIDC, cleanup, tasks, webhooks, audit) | With their features |

## 3. Decisions

| # | Decision | Reason |
| --- | --- | --- |
| D1 | The UI, the API and the repositories share one origin. In Compose a gateway (nginx) is the one published port: `/api/`, `/repository/` and `/v2/` go to the backend, everything else to the frontend. In production the operator's own reverse proxy does the same; the README gives the rules. | Chosen by the product owner. The session cookie and the base URL need one origin, and artifacts must not pass through Node. |
| D2 | The Next.js server renders the shell and nothing else. It never calls the backend, holds no secret and reads no cookie. All data is fetched by the browser from `/api/v1`. | One way to call the API, one place that enforces access (the backend), and a frontend container that can be restarted or scaled without care. |
| D3 | The UI starts from `GET /auth/session`. A session is the backend's cookie; the CSRF token it returns is kept in memory and sent with every request that changes something. | The identity design. Nothing about the session is stored by the UI. |
| D4 | A visitor who is not signed in sees the browsing area if anonymous access is on, with a "Sign in" action; otherwise the sign-in screen. A user who must change their password sees only that screen until they have. | SEC-6. The API refuses everything else for such a user anyway. |
| D5 | Components are written in this repository, styled with Tailwind CSS from the design tokens, on Radix primitives for behaviour. | Chosen by the product owner. The look is ours; keyboard and screen-reader behaviour comes tested. |
| D6 | Colours, type, spacing, radii, glows and motion are CSS custom properties, one set for each mode. Components use only the utilities made from them. A test fails on a literal colour in a component, and another computes the contrast of every text and surface pair in both modes. | UI-11, UI-12. A rule that is only written down is broken by the third screen. |
| D7 | Typefaces: Oxanium for headings and navigation, Inter for text and tables, JetBrains Mono for coordinates, paths, checksums and code. Their files (variable fonts, Latin) are in the repository with their licences. | Chosen by the product owner. UI-8, UI-14: nothing is fetched at build time or at run time. |
| D8 | The mode is light, dark, or as the system says, chosen in the user menu and kept in the browser's local storage. A short script in the page's head sets it before anything is painted. | UI-9, UI-10. The server cannot know the system's mode, and a cookie would make every page depend on the request. |
| D9 | A strict content security policy with a nonce for each request, set by the Next.js proxy file. Every page is therefore rendered for its request, and the framework's cached components are left off. | NFR-9. Next.js cannot put a nonce into a page it built ahead of time. The shell is small, so rendering it each time costs little. |
| D10 | Text is in `messages/en.json`, read with `next-intl`. A lint rule refuses literal text in markup. | UI-4. |
| D11 | Navigation comes from one registry of areas and items. An item names the permission it needs, and is hidden from a caller whose permission patterns do not grant it, matched as the backend matches them. Hiding is a courtesy: the API decides. | UI-2. |
| D12 | Angular shapes are bevelled corners (`corner-shape: bevel`), with square corners where a browser does not have it. Glow is a shadow in an accent colour, and goes, with all motion, when the system asks for reduced motion. | UI-7, UI-13. A bevel made with `clip-path` cuts off the focus ring and the glow. |
| D13 | A neon accent is used for borders, glows and icons. Text in an accent colour uses a second, compliant tone of it. Status always has an icon and a word. | UI-11, UI-15. |
| D14 | The API's types are generated from the backend's OpenAPI document. A copy of that document is in the repository, and a backend test fails when it is out of date. | API-2. The UI and the API cannot drift apart unnoticed. |
| D15 | An error from the API is shown with its message, its code and the request's ID. | UI-5, NFR-14. Whoever reports a fault can say which request it was. |
| D16 | Unit and component tests run with Vitest and Testing Library. Tests in a real browser (Playwright) run against the Compose stack, through the gateway, as part of the `docker` suite, in both modes, with an accessibility scan and a check that no request leaves the origin. | NFR-17, UI-6, UI-11, UI-14. Contrast and focus are only real in a browser. |
| D17 | In Compose the backend is no longer published. The real-client tests reach it through the gateway: the package clients in their containers too, which address the gateway by its name. | The gateway's rules are then proven by Maven, npm, pip and Docker themselves, and are the rules an operator copies. |

## 4. Structure

```text
frontend/
  src/app/            routes: the shell's layout, sign-in, change password, home
  src/components/ui/  the component set: button, field, panel, alert, dialog, menu, table, states
  src/components/     the shell: header, navigation, user menu, theme
  src/lib/api/        the client, the error type, the generated types
  src/lib/session/    the session, permission matching, the guard
  src/lib/            navigation registry, theme, formatting
  src/styles/         tokens.css (both modes), globals.css
  src/fonts/          the three typefaces and their licences
  src/proxy.ts        the content security policy
  messages/en.json    every text of the UI
  e2e/                tests in a real browser
  Dockerfile
gateway/nginx.conf    the routing rules, for Compose
```

## 5. Design tokens

Each token has a value for the dark mode and one for the light mode. Surfaces, lines and text:

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `page` | `#07080d` | `#f2f4f9` | The page |
| `panel` | `#0d1018` | `#ffffff` | Panels, the header |
| `raised` | `#151a26` | `#e8ecf5` | Hover, selected rows, menus |
| `field` | `#10141e` | `#ffffff` | Inputs |
| `line` | `#2a3348` | `#c3cbde` | Borders that only divide |
| `line-strong` | `#5b6a8f` | `#6f7b99` | Borders of inputs and of what can be pressed |
| `fg` | `#e6ebf5` | `#10131c` | Text |
| `fg-muted` | `#a3aec4` | `#465069` | Secondary text |
| `fg-subtle` | `#8f9ab3` | `#566280` | Hints, placeholders |

Accents, each as a neon tone for borders, glows and icons, and an ink tone for text:

| Accent | Neon, dark | Ink, dark | Neon, light | Ink, light |
| --- | --- | --- | --- | --- |
| Cyan (primary) | `#00e5ff` | `#5cefff` | `#0090ad` | `#00647d` |
| Magenta | `#ff2bd6` | `#ff7ae5` | `#d400ab` | `#a30085` |
| Acid | `#c6ff00` | `#d4ff4d` | `#6c9100` | `#4a6400` |

Status (success, warning, danger, information) follows the same pair of tones, and always comes with an icon and a word. A filled primary button is `primary` with `on-primary` text: cyan with near-black text in the dark mode, deep cyan with white text in the light mode. The focus ring is the acid tone in the dark mode and the ink magenta in the light mode: a colour nothing else in a control has.

Type: a scale from 12 to 30 pixels in rem; Oxanium in capitals with wide tracking for navigation and small headings. Spacing is Tailwind's 4-pixel scale. Radii are 2 pixels where corners are square and an 8-pixel bevel on panels, buttons and tags. Glow has two strengths. Motion has two durations, both zero under reduced motion.

The values above are those of `frontend/src/styles/tokens.css`, which is the authority, with the contrast test (D6): a pair that fails it is changed there, and here.

## 6. The shell

- **Header:** the wordmark, and at its end the search box, the mode switch and the user menu (or "Sign in"). From 1024 pixels the navigation is a row of its own under them, which wraps where its items do not fit in one line (plan 10b, A14).
- **Navigation:** two areas, browsing and administration, each a list of items from the registry (D11). An area with no visible item is not shown. Below 1024 pixels the navigation is behind a menu button.
- **A skip link** is the first thing focus reaches, and leads to the main content.
- **The user menu:** the user's name, "Account" (plan 10b; it was "Change password"), and "Sign out".
- **States:** a screen that is loading shows a skeleton of itself; one with nothing to show says so and what to do; one that failed shows the error (D15) and a way to try again.

Plan 9 registers one item, the home screen. Plan 10 registers the rest.

## 7. The session

1. The shell asks `GET /auth/session`.
2. Signed in, and the password must be changed: the change-password screen, and nothing else.
3. Signed in: the screen that was asked for.
4. Not signed in, anonymous access on (the answer has a `method`): the browsing area.
5. Not signed in otherwise: the sign-in screen, which returns to the screen that was asked for. Only an address within the UI is returned to. It is read as a browser reads it, against the UI's own origin: its text alone does not say where it leads, since a browser drops a tab or a line break and takes a backslash for a slash.

Signing in posts the name and password, keeps the CSRF token, and fills the session from the answer. If the answer is a success and the session then says nobody is signed in, the browser did not keep the cookie, and the screen says why: the cookie is `Secure`, and the address is plain HTTP on a host that is not `localhost`.

A `401` from any later request means the session has ended: the session is asked for again, and the rules above apply. A `403` with the code `password_change_required` leads to the change-password screen.

Signing out ends the session and then loads the home screen afresh, so that nothing the page held in memory for whoever was signed in is left, and the next visitor starts where any visitor does.

## 8. The gateway

```text
/api/         -> backend     the REST API and its documentation
/repository/  -> backend     Maven, npm, PyPI and Raw repositories
/v2/          -> backend     the Docker registry
everything else -> frontend
```

Towards the backend the gateway must: pass the request path exactly as it was sent (an npm scope is an encoded slash); put no limit on the size of a body; pass a body on as it arrives and an answer as it is produced, without buffering either; wait as long as a proxy repository may need for its remote; and send `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`. The backend trusts those headers only from addresses named in `MEGOOARTI_FORWARDED_ALLOW_IPS`.

The gateway writes `X-Forwarded-For` itself, from the address it sees, and does not pass on what a client sent: the backend counts failed sign-ins by that address.

## 9. Security

- **Content security policy:** `default-src 'self'`; scripts only with the request's nonce; styles from the origin, with the nonce, or as attributes (Radix positions menus with them); images from the origin and `data:`; fonts and connections from the origin only; no frames, no objects, no base, forms to the origin only.
- **Other headers:** `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, and a `Permissions-Policy` that grants nothing.
- **What a repository holds is text:** a name, a path or a description is never put into the page as markup.
- **The return path after sign-in** must resolve, as a browser resolves it, to an address of the UI's own origin, and hold no control character or backslash. Otherwise the home screen is used.
- **The frontend container** runs as a user that is not root and has no secret in its environment.

## 10. Testing

- **Tokens:** every text tone on every surface it is used on, in both modes, at 4.5 to 1; neon tones against their surfaces at 3 to 1; the two modes define the same tokens; no component holds a literal colour.
- **Components:** each is rendered and used by keyboard, and scanned with axe.
- **The session:** each branch of section 7, with the API answered by the test.
- **Permission matching:** the same cases as the backend's own tests.
- **The API client:** the error envelope, the CSRF header on what changes something and not on what reads, the request ID, an answer that is not JSON.
- **In a real browser, against the stack:** the first sign-in with the generated password, the forced change, the home screen, signing out; the mode set before the first paint and kept after a reload; the whole flow by keyboard; an axe scan of each screen in each mode; a narrow window; the policy's header and no violation of it; and no request to another origin.
- **The gateway:** the existing real-client suites, which now pass through it (D17).

## 11. Risks

| Risk | Response |
| --- | --- |
| Next.js 16 differs from earlier versions in ways that are easy to get wrong. | Its own documentation, shipped in the package, was read for every point this design depends on. The project's `AGENTS.md` tells whoever works on it next to do the same. |
| Rendering every page for its request (D9) costs the frontend container work a static page would not. | The shell has no data in it. If it ever matters, the framework's experimental hash-based policy keeps pages static. |
| `corner-shape` is not in every browser. | Square corners there (D12). Nothing depends on the bevel. |
| The gateway changes what every existing real-client test passes through. | That is the point (D17), and the first thing the plan runs after adding it. |
| A session cookie marked `Secure` is not kept over plain HTTP on a host that is not `localhost`. | The sign-in screen says so (section 7), and the README names the setting. |

## 11a. Settled while building plan 9

- **The framework's cached components are off** (`cacheComponents`), and every page is rendered for its request. Next.js 16 can only put a nonce into a page it renders for the request, and says itself that the two do not combine.
- **Radix writes a style sheet of its own** into the page when a menu or a dialog opens. It is let in by the same nonce, which the layout hands to it.
- **The translations are given to the browser's code**, not read on the server: nothing on the server needs a locale, and `next-intl` then needs no configuration of its own.
- **The fonts are loaded with `next/font/local`** from files in the repository. `next/font/google` would fetch them from Google when the UI is built.
- **Tailwind's own palette is removed**, so a class naming one of its colours does not exist. With the test that refuses a literal colour, a component can only use tokens.
- **A confirmation gives focus back to whatever opened it.** Radix does that for a trigger of its own; this dialog is opened by its screen.
- **A table scrolls inside its panel.** Text hidden from sight inside a cell is placed absolutely, and widened the page on a narrow screen until the table's own box contained it. The browser test for a 375-pixel screen found it.
- **The gateway is nginx**, with the routing rules in `gateway/nginx.conf`. `/v2` without its slash is not the registry: every client asks for `/v2/`.
- **The browser tests run at `localhost`**, because a browser keeps a `Secure` cookie over plain HTTP only there.
- **Not in plan 9:** the home screen shows the first 200 repositories and says how many there are.

Changed after the whole-branch review:

- **The return path is resolved, not pattern-matched.** `/<tab>/evil.example` passed a check of its text and led to another site.
- **The mode is applied from storage and the system, never from what the server guessed.** While the page hydrated, the server's dark was applied for a moment over what the head's script had set. The head's script now also asks the system when storage cannot be read.
- **A refusal for a wrong CSRF token is treated as a session that changed**, like a `401`: the session is asked for again, which brings its token. A `401` for the session's own request is shown, and not asked for again without end.
- **A sign-out that fails says so**, under the header, with a way to try again.
- **The gateway writes the client's address itself.** With `$proxy_add_x_forwarded_for` a client could choose the address the backend counts failed sign-ins by.
- **A field that is wrong gets the keyboard**, so that a screen reader reads it and why. **Each screen names the page** ("Repositories · MegooArti").
- **The policy also forbids frames and a base address**, as section 9 says.

## 12. The screens (plan 10)

Delivered as three plans.

| Plan | Contents |
| --- | --- |
| **10a** | Browsing a repository, a component and its usage, search, upload, delete |
| **10b** | A person's own API tokens and preferences; users, roles and anonymous access |
| **10c** | Repositories, blob stores, the base URL and system information |

### 12.1 Decisions

| # | Decision | Reason |
| --- | --- | --- |
| S1 | A repository is browsed as one folder at a time: a path of breadcrumbs, and under it the folder's entries as a list. Choosing a file shows its details beside the list, or below it on a narrow screen. | Chosen by the product owner. Only one folder is ever listed, so a folder of a million entries opens as fast as one of ten, which is what the API's tree was built for. |
| S2 | Every folder and every file has an address: `/browse/<repository>/<folders...>`, with `?file=<name>` for a file chosen in it. | A link can be shared, and the browser's back button works. |
| S3 | A list that the API pages with a cursor (a folder) grows with "Show more". A list it pages with a total (search results, and the administration lists) has numbered pages. | A folder has no total. A page of results has. |
| S4 | Search is a box in the header on every screen, with `/` as its key, and a results page that has the filters: format, repository, group, name, version, and a checksum. | Chosen by the product owner. Finding a package is what most visitors come for. |
| S5 | A checksum is typed into one field. Its length says which it is. | Nobody knows whether what they copied is called `sha1`. |
| S6 | A component has a page of its own: its coordinates, its files, and how to use it, each snippet with a button that copies it. A file's details link to its component. | CMP-4. Search results are components. |
| S7 | Uploading is a page for one repository, with the fields its format needs, reached from the repository and from the navigation. Files are dropped onto it or chosen. While they are sent it shows how much has gone, and it can be stopped. | CMP-7. An artifact can be gigabytes. |
| S8 | What a caller may not do is not offered: no upload without `add` or `edit` on the repository, no delete without `delete`. A download is always offered: it is a link, and the server decides. | UI-2. The patterns a signed-in person holds do not include what is public, so hiding a download could hide what they may fetch. |
| S9 | Deleting a file or one version asks in a dialog, with Cancel focused. Deleting a folder, a repository, a blob store or a user asks for its name to be typed first, and says what goes with it. | Chosen by the product owner. A slip then cannot remove a repository. |
| S10 | Deleting a folder is done in the pieces the API does it in, with a count that grows, and can be stopped between pieces. | The API removes at most a thousand files a request. |
| S11 | What was done is said in a notification that a screen reader hears, and that goes by itself. What failed stays on the screen until it is dismissed. | After a delete, the thing that was acted on is gone: there is nowhere beside it to say so. |
| S12 | A time is shown as how long ago, with the exact time, in the reader's own zone, on hover and for a screen reader. A size is in binary units. | A person reads "3 days ago"; a log needs the minute. |
| S13 | A repository is created on one page that grows: the format and the type are chosen at its top, and the fields for that combination follow. Editing is the same page with the two fixed. | Chosen by the product owner. Everything is in view before it is saved. |

### 12.2 Browsing (plan 10a)

| Address | What it shows |
| --- | --- |
| `/` | The repositories a caller may browse. Each leads to its folders. |
| `/browse/<repository>/<folders...>` | Breadcrumbs, the folder's entries, and, with `?file=`, a file's details. For a group: its members, each a link. |
| `/components/<repository>/<id>` | A component: coordinates, files, usage, and deleting the version. |
| `/search` | The filters and a page of results. |
| `/upload` | The hosted repositories the caller may upload to. |
| `/upload/<repository>` | The upload form for that repository's format. |

- **A folder's entries** are folders and files in the order the API gives them. A file shows its size and when it changed.
- **A file's details** are everything the API says of it: size, content type, the four checksums (each with a copy button), blob store, who stored it and when, when it was last downloaded, the component it belongs to, and a download link.
- **A proxy** is browsed for what it has cached, and says so under its name. **A group** lists its members, those the caller may browse, each a link: the API refuses to list a group's own folders, as it holds none.
- **Upload forms:** Raw has a directory (filled in from where the upload was started) and files. Maven has group, artifact, version, packaging, whether to write a POM, the artifact, an optional POM, and further files each with a classifier. npm has one tarball and a tag. PyPI has files, and optionally a summary, the Python it requires and keywords. A refusal by the API is put at the field it names.
- **Names and paths are text.** A path is put into an address one segment at a time, each encoded; nothing from the API is put into the page as markup.

#### Settled while building plan 10a

| # | What | Why |
| --- | --- | --- |
| B1 | A name someone chose (a repository, a folder, a version) is never put in capitals: not in a screen's title, not in a dialog's title, and not in the label that asks for it to be typed. Titles that are the UI's own words stay in capitals. | Names tell capitals from small letters, and the name typed to confirm is compared exactly. A label that showed `V1` for `v1` asked for the wrong thing. |
| B2 | A folder that is not there says so and leads to the top of its repository. | Folders are not things of their own: deleting the last file of one removes it, and the folders above it that held nothing else. The screen a delete returns to can therefore be such a folder. |
| B3 | A folder or a file in a list is named to a screen reader with its kind: "Folder docs", "File guide.md". | The icon that tells them apart is not read. |
| B4 | The upload is the one request made with `XMLHttpRequest`. | `fetch` cannot say how much of a body has been sent (S7). Its failures are the same `ApiError` as every other request's. |
| B5 | The file field is emptied after each choice, so that files add up and one that was taken out can be chosen again. The browser's own "No file chosen" beside it is not shown: the list under the field says what is chosen. | The two contradicted each other. |
| B6 | What was fetched of a repository is forgotten after an upload or a delete in it: its folders are asked for again, and its files' and components' details are dropped. | An index or a metadata file can change with any of them. |
| B7 | A screen inside the shell that is given an address it cannot read says that nothing is there, inside the shell. The page for an address no route answers is a different one, with no shell. | Two `main` landmarks otherwise. |
| B8 | The lint refuses text written into a property that is read out (`aria-label`, `title`, `alt`, `placeholder`, `label`, `hint`), as it refuses text in markup. | Left open by plan 9: UI-4 is about every text a person meets. |
| B9 | A button that is busy keeps the keyboard: it is marked `aria-disabled` and ignores a press, where it used to be disabled. | A disabled button loses focus, and with it a keyboard user's place, each time something is sent. Left open by plan 9. |
| B10 | A download link is made only of an `http` or `https` address. | It is the one thing from the API that the UI makes into a link out of itself. |

#### Settled by the review of plan 10a

| # | What | Why |
| --- | --- | --- |
| B11 | When a screen changes under the keyboard, the keyboard is put at what changed: at the folder's place in the path when a folder is entered; at a file's entry when its details are closed, or at the folder if the file was deleted; at the first new entry after "Show more"; at the line above the results when another page of them is shown; at the Upload button when an upload is stopped; at the file field when a chosen file is taken out. Not on arrival: a page starts at its top. | What had the keyboard was removed, and a keyboard or screen-reader user was sent back to the top of the page with nothing said (UI-6, WCAG 2.4.3). |
| B12 | Where a screen last was is kept outside it (`lib/places.ts`), for as long as the page lives. | Next.js builds a screen anew when a part of its address changes, so the screen cannot remember it. Found in a real browser: the unit test, which renders the same screen again, passed without it. |
| B13 | A refused upload puts the keyboard at the first field that was refused, as every form does (section 11a). What was stored, and that an upload was stopped, is said in a notification (S11). | An error or a status that only appears is not reliably heard. |
| B14 | A request that is not made through the store of fetched data (the upload, with its progress; a folder deleted piece by piece) applies the store's rule itself: after a `401`, a password that must be changed or a wrong CSRF token, the session is asked for again. | Section 7 says it of every request. With the session replaced in another tab, an upload was refused at every press until the page was reloaded. |
| B15 | The dialog that asks for a name asks for it each time it opens, whoever closed it, and does not show what went wrong the time before. | After a folder delete that left files behind, the dialog opened with the name still typed and its button armed (S9). |
| B16 | The navigation shows "Upload" only to whoever holds a permission that could grant `add` or `edit` on some repository. A navigation item can name such shapes, with `?` for any value (`repository:?:?:add`). | UI-2. A visitor was led to a screen that said there was nowhere to upload to. |
| B17 | A group has no "Search this repository". The search form shows a repository or a format that the address names though it is none of its choices. | The search API looks in hosted and proxy repositories, so a search in a group found nothing, and the form said "Any". |
| B18 | On an upload screen, a file dropped anywhere but on a file field does nothing. | The browser opened the file in place of the page, and the form was lost. |
| B19 | A unit test fails when a screen asks for a text that `messages/en.json` does not have. | The upload page of a Docker repository showed a message key, and its test passed. |

Left open by plan 10a, and settled by A11 and A12 of plan 10b: `/` cannot be turned off. WCAG 2.1.4 (level A) asks that a shortcut of one character can be turned off or changed; the switch belongs with a person's own settings, which plan 10b adds. Below 768 px, with the navigation closed, the key does nothing, and should then not be taken.

### 12.3 Account and security (plan 10b)

A person's own account, and what an administrator does about people: users, roles and anonymous access. No change to the API.

#### Decisions

| # | Decision | Reason |
| --- | --- | --- |
| A1 | A person's own settings are one Account area of three pages, each with an address: API tokens, Password, Preferences. The user menu leads to it, and the pages link to each other. | Chosen by the product owner. The forced change of password keeps the page it has. |
| A2 | A role's permissions are written as rows. A row says what it is about: a repository (format, repository and action, each from a list with "any"), an administration area (area and "read" or "write", each with "any"), everything, or a pattern typed by hand. The pattern a row makes is shown beside it, with what it grants in words. | Chosen by the product owner. Someone who does not know the grammar can still write a role, and someone who does is not held back. |
| A3 | A permission the rows cannot express (a pattern of another shape, or one the server gave that this UI does not know) is a typed row. Nothing is lost by opening and saving a role. | A role written through the API may hold anything the grammar allows. |
| A4 | Creating an API token asks for a name, an expiry (never, 30 days, 90 days, a year, or a date), and what it may do: everything its owner may, only read, or custom. Custom is the rows of A2. | Chosen by the product owner. The usual token is for one's own build. |
| A5 | A new token's secret is shown once, on the page that made it, with a button that copies it, and is gone when the page is left. It is kept nowhere: not in what was fetched, not in the address, not in the browser's storage. | The API never returns it again. |
| A6 | A password that an administrator sets for someone can be typed or generated. A generated one is 20 characters from letters and digits that are not mistaken for each other, made by the browser's own random numbers, and shown so that it can be passed on. "Must choose a new password at the next sign-in" is ticked. | The administrator has to tell it to someone. |
| A7 | What the server protects is not offered: deleting or disabling one's own account, deleting a built-in user or role, changing the `admin` role, a password for the anonymous user. The screen says why. What the server refuses beyond that (the last administrator, a role that would contain itself) is said as it says it. | UI-2, UI-5. |
| A8 | Deleting a user asks for the user name to be typed (S9). Deleting a role or revoking a token asks in a plain dialog that says what follows from it. | A user's tokens and sessions go with it. |
| A9 | Anonymous access is a page with one switch. Turning it on asks first, and says what it means: anyone who can reach the server acts as the `anonymous` user. The page shows what that user may do now, in words, and leads to the user and its roles. | It is the one setting that makes content public. |
| A10 | After a user or a role is changed, the session is asked for again. | The change may be to what the person who made it may do. |
| A11 | Preferences are kept in the browser, as the mode is: the mode, and whether `/` goes to the search box. The page is open to a visitor too, and the mode menu in the header leads to it. | WCAG 2.1.4: a shortcut of one character can be turned off. A visitor has a keyboard as well. |
| A12 | `/` is taken only when it leads somewhere: a search box that is on the screen. | Below 768 px, with the navigation closed, the key was taken and did nothing. |
| A13 | The lists of users and roles have numbered pages (S3), 50 to a page. A user's or a role's page is addressed by its id or name: `/admin/users/<id>`, `/admin/roles/<name>`. | The API pages them with a total. |

#### Addresses

| Address | What it shows | Shown to |
| --- | --- | --- |
| `/account/tokens` | One's API tokens: name, how it begins, what it may do, when it expires and was last used. Create and revoke. | Whoever is signed in |
| `/account/password` | Changing one's password (plan 9). | Whoever is signed in |
| `/account/preferences` | The mode, and the `/` key. | Everybody |
| `/admin/users` | The users: name, roles, state, last sign-in. | `admin:users:read` |
| `/admin/users/new` | A new user. | `admin:users:write` |
| `/admin/users/<id>` | One user: details and roles, state, a new password, API tokens, delete. | `admin:users:read`; tokens need `admin:tokens:read` |
| `/admin/roles` | The roles: name, what they hold. | `admin:roles:read` |
| `/admin/roles/new`, `/admin/roles/<name>` | A role: description, permissions as rows, the roles it contains, delete. | `admin:roles:read`, `write` to change |
| `/admin/anonymous-access` | The switch, and what the anonymous user may do. | `admin:settings:read`, `write` to change |

- **The navigation** gets its Administration area: Users, Roles, Anonymous access, each shown to whoever holds the permission to read it.
- **A screen whose data the caller may not read** says so (the API's `403`), as every screen does. A form whose data they may read but not change is shown with its fields and without the button that saves.
- **The areas of administration** the rows know are those the API has: users, roles, tokens, settings, blob stores, repositories. The actions on a repository are browse, read, add, edit, delete.

#### Settled while building plan 10b

| # | What | Why |
| --- | --- | --- |
| A14 | In a wide window the navigation is a row of its own in the header, under the wordmark and the search box, and wraps where it does not fit. | With the administration's three items beside the browsing ones, the navigation ran under the search box, which then took the clicks meant for "Roles". Plan 10c adds more. A sidebar is the other way to do it, and is put to the product owner. |
| A15 | Whether an element is on the screen is asked of the browser in one place (`lib/browser.ts`), where a test can stand in for it. | A12 needs it, and the test environment lays nothing out. |
| A16 | The rows of a role keep to themselves once they are shown: a pattern typed by hand stays a typed row, though it becomes one the lists could say. | Otherwise the field would turn into lists under the hands that are typing in it. |
| A17 | A row that is added gets the keyboard. Where a thing that had the keyboard goes (a row removed, a token revoked, the panel of a token or a user that was just made), the keyboard is put at what is nearest to it: the button that adds, the list of tokens, the form's first field. | B11 of plan 10a, kept to. |
| A18 | A new user's password is shown once more after the user is made, with a button that copies it, until the page is left. A password set for an existing user stays in its field for the same reason. | The administrator has to pass it on, and may not have copied it before pressing the button. |
| A19 | What a visitor may do is shown as the patterns of the anonymous user's roles and of the roles they contain, and of those only what concerns repositories. | The server allows a request without credentials nothing else, whatever the roles say. |
| A20 | A token's secret is not kept by the store of what was fetched: the request that makes it is forgotten as soon as its answer is handed over. | A5. |

### 12.4 Repositories and the system (plan 10c, outline)

Repositories (create and edit as S13 says, delete, invalidate a proxy's cache, rebuild an index). Blob stores (create, delete, what they hold). The base URL. System information: the version, the schema's revision and the blob stores' state, which needs a small addition to the API.

## 13. Requirement coverage

| Requirement | Where |
| --- | --- |
| UI-1 | Sections 2, 12 |
| UI-2 | D11, section 6 |
| UI-3 | Section 6 |
| UI-4 | D10 |
| UI-5 | Section 6, D15 |
| UI-6 | D5, D16 |
| UI-7, UI-8 | D7, D12, section 5 |
| UI-9, UI-10 | D8 |
| UI-11, UI-15 | D6, D13 |
| UI-12 | D6 |
| UI-13 | D12 |
| UI-14 | D7, D16 |
| NFR-9, NFR-10 | Section 9 |
| NFR-17 | D16 |
| TC-2, TC-4 | D1, D2, D17 |
| API-1, API-2 | D2, D14 |
