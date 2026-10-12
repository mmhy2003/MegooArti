import localFont from "next/font/local";

// The files are in the repository, with their licences beside them: nothing is fetched
// when the UI is built or when it is used (UI-14). Each is a variable font, Latin only.
// A letter outside it is drawn with the system's own font.

/** Headings and navigation. */
export const oxanium = localFont({
  src: "../fonts/oxanium-latin-wght-normal.woff2",
  variable: "--font-oxanium",
  weight: "200 800",
  display: "swap",
});

/** Text and tables. */
export const inter = localFont({
  src: "../fonts/inter-latin-wght-normal.woff2",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});

/** Coordinates, paths, checksums and code. */
export const jetbrainsMono = localFont({
  src: "../fonts/jetbrains-mono-latin-wght-normal.woff2",
  variable: "--font-jetbrains-mono",
  weight: "100 800",
  display: "swap",
});
