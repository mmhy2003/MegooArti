import localFont from "next/font/local";

// The files are in the repository, with their licences beside them: nothing is fetched
// when the UI is built or when it is used (UI-14). Each is Latin only. A letter outside
// it is drawn with the system's own font.

/** Headings and text. */
export const geist = localFont({
  src: "../fonts/geist-latin-wght-normal.woff2",
  variable: "--font-geist",
  weight: "100 900",
  display: "swap",
});

/** Coordinates, paths, checksums and code. */
export const geistMono = localFont({
  src: "../fonts/geist-mono-latin-wght-normal.woff2",
  variable: "--font-geist-mono",
  weight: "100 900",
  display: "swap",
});

/** The wordmark only. */
export const orbitron = localFont({
  src: "../fonts/orbitron-latin-700-normal.woff2",
  variable: "--font-orbitron",
  weight: "700",
  display: "swap",
});
