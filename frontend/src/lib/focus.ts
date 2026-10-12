"use client";

/**
 * Where the keyboard goes when a screen changes under it by itself: a form that was
 * refused, a list that turned a page. What had the keyboard is then gone or beside the
 * point, and whoever uses a keyboard or a screen reader would be left at the top of the
 * page with nothing said (B11, and section 11a of the design).
 */
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * A form that says what is wrong with it. `attempt()` is called at every press of its
 * button, and `tried` says whether there was one: until then nothing is said to be
 * wrong. After every attempt, and whenever `refused` changes (the server's answer), the
 * keyboard goes to the first field that is wrong, where a screen reader reads the
 * field and, with it, why.
 *
 * Every attempt, and not only the first: when one field is put right and the next is
 * still wrong, the button would otherwise seem to do nothing.
 */
export function useAttempts(refused: unknown): {
  form: RefObject<HTMLFormElement | null>;
  tried: boolean;
  attempt: () => void;
  /** The form starts over, as after it was sent and emptied: nothing is wrong with it yet. */
  forget: () => void;
} {
  const form = useRef<HTMLFormElement>(null);
  const [attempts, setAttempts] = useState(0);
  useEffect(() => {
    if (attempts > 0) form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [attempts, refused]);
  return {
    form,
    tried: attempts > 0,
    attempt: () => setAttempts((made) => made + 1),
    forget: () => setAttempts(0),
  };
}

/**
 * A list with numbered pages. The link that led to another page goes while the page
 * loads: once it has `arrived`, the keyboard is put at what this returns a reference
 * to (something named, above the list, with `tabIndex={-1}`). Not on arrival at the
 * screen: a page starts at its top.
 */
export function usePageFocus<Element extends HTMLElement>(
  page: number,
  arrived: boolean,
): RefObject<Element | null> {
  const top = useRef<Element>(null);
  const shown = useRef(page);
  useEffect(() => {
    if (!arrived || shown.current === page) return;
    shown.current = page;
    top.current?.focus();
  }, [page, arrived]);
  return top;
}

/**
 * A page past the last has nothing on it, and would say that there is nothing at all.
 * It is reached by an address typed by hand, and by removing the last thing of the last
 * page. The visitor is taken to the last page there is. `pages` is undefined until the
 * list has answered. It returns whether that is happening: there is then nothing to show.
 */
export function useWithinPages(
  page: number,
  pages: number | undefined,
  hrefFor: (page: number) => Route,
): boolean {
  const router = useRouter();
  const last = pages === undefined ? undefined : Math.max(1, pages);
  const beyond = last !== undefined && page > last;
  const address = beyond ? hrefFor(last) : null;
  useEffect(() => {
    if (address !== null) router.replace(address);
  }, [address, router]);
  return beyond;
}
