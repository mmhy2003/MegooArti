"use client";

import "@/styles/globals.css";

import messages from "../../messages/en.json";

/**
 * The layout itself threw, so nothing it provides is there: not the translations, not
 * the fonts, not the mode. This page stands entirely on its own.
 */
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  const t = messages.crash;
  return (
    <html lang="en" data-theme="dark">
      <body>
        <main className="mx-auto flex min-h-dvh max-w-xl flex-col items-start justify-center gap-3 px-4">
          <h1 className="text-xl font-semibold text-fg uppercase">{t.title}</h1>
          <p className="text-fg-muted">{t.body}</p>
          <button
            type="button"
            onClick={reset}
            className="bevel label-caps min-h-10 border border-line-strong bg-panel px-4 text-fg"
          >
            {t.reload}
          </button>
        </main>
      </body>
    </html>
  );
}
