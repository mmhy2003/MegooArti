# MA-1: Sidebar layout and the Cyberpunk theme

## Goal

The web UI's navigation moves from rows in the header to a collapsible sidebar on the left, with search, the mode switch and the account menu staying in a header above the content. The UI's colours and typefaces become those of the Knowledge Base's "Cyberpunk Theme" (rev 3): lavender surfaces in light mode, graphite with neon accents in dark mode, set in Geist, Geist Mono and Orbitron. Mockup v2 shows the result.

## Decisions

| # | Decision | Why |
| --- | --- | --- |
| 1 | **Layout A: sidebar + header** (your answer). Rejected: sidebar only (B), header over sidebar (C). | Search stays in the header, where `/` reaches it and the docs say it is. |
| 2 | **Typefaces: Geist, Geist Mono, Orbitron 700 for the wordmark** (your answer). Rejected: no Orbitron; keeping Oxanium, Inter and JetBrains Mono. | As the KB theme says. |
| 3 | **The accessibility tests stay; the KB palette is adjusted only where it fails them** (your answer). Rejected: KB values exactly with loosened tests. | BRD UI-11 (AA contrast) is a Must. |
| 4 | **The sidebar collapses to a rail of icons, and the choice is kept in the browser** (your answer). Rejected: always open. | Room for wide screens such as Browse and the Audit log. |
| 5 | The tokens keep this project's names (`page`, `panel`, `raised`, `field`, `line`, …) and take the KB's values. Rejected: renaming them to the KB's names (`bg`, `surface`, `surface-2`). | A rename would touch nearly every component for no change a person sees. |
| 6 | Shapes do not change: 2 px corners and the 8 px bevel stay. | The KB theme says nothing of shape; BRD UI-7 asks for angular ones. |
| 7 | Below 1024 px the sidebar is a modal drawer (Radix `Dialog`), not the in-flow panel of today. | It is a sidebar there too, and the dialog brings the focus trap, Escape and the scrim. `radix-ui` is already a dependency. |

## Architecture

### Theme

**`frontend/src/styles/tokens.css`** (the only place a colour is written) takes the KB values:

| Token | Light | Dark | From the KB |
| --- | --- | --- | --- |
| `page` | `#f6f3ff` | `#0e0f13` | `bg` |
| `panel` | `#ffffff` | `#17191f` | `surface` |
| `raised` | `#ece6ff` | `#121318` | `surface-2` |
| `field` | `#ffffff` | `#0e0f13` | `surface` in light, `bg` in dark |
| `line` | `#d6ccf5` | `#2a2d36` | `line` |
| `line-strong` | `#6b5f99` | `#8e94a3` | `muted-foreground` (adjustment 3 below) |
| `fg` | `#1a0b3d` | `#eceef3` | `fg` |
| `fg-muted` | `#6b5f99` | `#8e94a3` | `muted-foreground` |
| `primary` / `on-primary` | `#007a8f` / `#ffffff` | `#22e4ff` / `#0e0f13` | `cyan-ink` / `on-accent` |
| `danger` / `on-danger` | `#d4004f` / `#ffffff` | `#ff3d81` / `#0e0f13` | `pink` / `on-accent` |
| `neon-cyan` | `#0090a8` | `#22e4ff` | `cyan` |
| `neon-violet` | `#6d28d9` | `#c084fc` | `violet` |
| `ok` / `warn` / `bad` | `#1f8f2c` / `#a16207` / `#d4004f` | `#5bff9a` / `#ffe14d` / `#ff3d81` | `green` / `amber` / `pink` |
| `focus` | `#6d28d9` | `#c084fc` | `violet` (adjustment 2) |
| `grid` | `rgba(80, 40, 200, 0.06)` | `rgba(255, 255, 255, 0.03)` | `grid` |

The three adjustments decision 3 allows:

1. **Ink tones in light mode.** `ink-cyan`, `ink-ok`, `ink-warn` and `ink-bad` are each the KB colour darkened by the least that reaches 4.5 to 1 on every surface. By my arithmetic the KB values come to about 4.1 to 4.5 on `raised`, and values near `#007286`, `#197725`, `#965b06` and `#cf004d` pass. These four are estimates worked by hand: the token test settles the final values. `ink-violet` is the KB violet as it is. In dark mode every ink tone equals its neon tone, as in the KB.
2. **The focus ring is violet**, not cyan: a colour nothing else in a control has.
3. **`line-strong`**, the border of inputs and of what can be pressed, is the KB's muted text colour. The KB's `line` stays for borders that only divide.

Other token changes:

- `fg-subtle` folds into `fg-muted`: the KB has one secondary text tone. Its uses (22 files) are replaced.
- `neon-magenta` / `ink-magenta` become `neon-violet` / `ink-violet`; `neon-acid` / `ink-acid` are removed. They have four uses: the wordmark's bar becomes `neon-cyan`; the user icon, the empty-state icon and the folder icon become `neon-violet`.
- **Depth.** A new `--mg-lift` (utility `shadow-lift`) is a soft shadow in light and nothing in dark, on `Panel`, menus and dialogs. `--mg-glow-sm` and `--mg-glow-md` are cyan glows in dark and soft shadows in light, as the KB says (light has no glows, dark no shadows). Under reduced motion the glows are still none.
- Menus and dialogs stand on `panel` (the KB's `popover` is `surface`).

**`frontend/src/styles/globals.css`**: the `@theme` mapping follows the token changes. `--font-sans` is Geist, `--font-mono` Geist Mono, `--font-display` Orbitron. `h1` to `h3` are Geist with `-0.01em` tracking. `label-caps` becomes Geist, semibold, uppercase, widely tracked: it stays on buttons, badges and small labels (table column headers, field captions, the sidebar's area names). The grid background uses the new `grid` token.

**Type in components**: navigation links (sidebar and `AccountNav`) and page titles (`PageHeader`) go from capitals to sentence case. The wordmark is Orbitron 700 with a cyan bar.

**Fonts** (`frontend/src/fonts/`, `frontend/src/lib/fonts.ts`, `frontend/src/app/layout.tsx`): three Latin `woff2` files (Geist variable, Geist Mono variable, Orbitron 700), each with its SIL OFL licence text, replace the present three files and licences. They are loaded with `next/font/local` as today, so nothing is fetched from another host (UI-14). The present file names follow Fontsource's naming, which suggests the new ones can come from its Geist, Geist Mono and Orbitron packages; the files are copied in, not added as dependencies.

### Shell

**`frontend/src/components/app-shell.tsx`** keeps its interface (`session`, `bare`, `children`) and becomes:

- **Skip link**, first as today.
- **Sidebar**, from 1024 px: the wordmark (a link home), then `<nav aria-label="Main">` with the two areas from `lib/navigation.ts` as vertical lists, then the collapse button at its foot. It is as tall as the window and stays while the page scrolls; its list scrolls by itself when it is longer than the window. The current item keeps `aria-current="page"`, a cyan border and `ink-cyan` text.
- **Rail.** Collapsed, the sidebar shows icons only. Each link keeps its name for screen readers, and shows it in a Radix `Tooltip` on hover and on keyboard focus. Area names become a dividing line.
- **Header**, sticky: the search box, the mode switch and the user menu. Below 1024 px it also has the menu button and the wordmark. `scroll-padding-top` keeps a focused element from hiding under it.
- **Drawer**, below 1024 px: the menu button opens the same navigation in a Radix `Dialog` from the left, over a scrim. It has a "Close the navigation" button, closes on Escape, on a click outside, when a link is followed, and when the window grows past 1024 px. Below 768 px the search box is in it, as today. The rail does not apply to it.
- **`bare`** (a password must be changed first): no sidebar, no menu button, no search; the header has the wordmark, the mode switch and the user menu, as today.
- **Content**: `<main id="main">` beside the sidebar, with the same `max-w-7xl` limit.

`lib/navigation.ts`, `SearchBox`, `ThemeSwitch`, `UserMenu` and `SessionGate` keep their behaviour; only their colours and type change.

**`frontend/src/lib/sidebar.ts`** (new), written as `lib/preferences.ts` is: the storage key, reading and storing the choice, a `useSyncExternalStore` hook, and the choice kept for the page when storage is off. It sets `data-sidebar="rail"` on `<html>`, and exports a pre-paint script as `lib/theme.ts` does. `app/layout.tsx` runs it in the same nonce'd `<script>` as the mode's. The sidebar's width and its labels follow that attribute in CSS (a Tailwind custom variant), so a reload shows the rail at once with no jump.

### Documents

- `docs/web-ui.md`: the sidebar, its collapse, the drawer.
- `docs/BRD.md` UI-7 and UI-8: the accents named (cyan, pink, green, amber, violet) and the display typeface for the wordmark only.
- `docs/superpowers/specs/2026-10-12-frontend-design.md` sections 5 and 6: the token tables and the shell, which that spec says are kept equal to `tokens.css`.
- `README.md` (the three typefaces in the licence paragraph) and `CHANGELOG.md`.

## Data and interfaces

- `localStorage["megooarti-sidebar"]`: `"rail"` when collapsed, absent when open.
- `<html data-sidebar="rail">`: set before paint and when the button is pressed.
- New messages in `frontend/messages/en.json`: "Collapse the navigation" and "Expand the navigation". "Open the navigation" and "Close the navigation" are kept.
- No API, backend or database change.

## Error handling and edge cases

- **Storage off or full**: the sidebar starts open, and a choice lasts as long as the page.
- **Server render**: the markup is always the open sidebar; the script corrects it before paint, and the button's name follows after hydration.
- **A visitor** sees the sidebar with the Browse area only. An area with nothing in it is not shown.
- **A sign-out that fails** is still said under the header.
- **`/`** is taken only when a search box is on the screen, as today: not below 768 px with the drawer closed.
- **Reduced motion**: no transition on the sidebar or the drawer, and no glow.
- **A browser without `corner-shape`** gets square corners, as today.

## Testing

- **`tokens.test.ts`**: the contrast matrix runs on the new token names, with `ink-violet` and without magenta, acid and `fg-subtle`. A new test holds every token in the table above to the KB's value, except the four ink tones adjustment 1 allows.
- **`literals.test.ts`** stays as it is: no colour outside `tokens.css`.
- **`lib/sidebar.test.ts`** (new): the choice is kept and read, anything else in storage means open, storage that fails, and the pre-paint script agrees with the module.
- **`shell.test.tsx`**: the sidebar's links, order and current item; the collapse button's name and `aria-expanded`, that it sets `data-sidebar` and storage, and that links keep their names in the rail; the drawer opens, closes on a link and on its button; the two search boxes; the `bare` shell; an axe scan. The test of the navigation as a wrapping row is removed.
- **`e2e/ui.spec.ts`**: the existing axe scans of every screen in both modes run against the new palette; the narrow-window tests use the drawer; a new test collapses the sidebar, reloads, and expects the rail before the UI's code has run. The existing check that nothing is requested from another origin covers the new fonts.
- `pnpm lint`, `pnpm typecheck`, `pnpm test` and `pnpm e2e` pass.

## Out of scope

- The account pages keep their own row of links (`AccountNav`); only its type and colours change.
- No control for the sidebar on the Preferences screen, and no preference kept on the server.
- The KB's chart colours: the UI has no charts.
- The layout of the sign-in screen and of every other screen's content: they change in colour and type only.
- Any backend change.
