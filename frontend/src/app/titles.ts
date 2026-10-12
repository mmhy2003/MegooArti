import type { Metadata } from "next";

import messages from "../../messages/en.json";

/** How a page is titled: the screen, then the product. A route gives the screen. */
export const TITLES = {
  default: messages.app.name,
  template: messages.app.title.replace("{screen}", "%s"),
};

/**
 * The title of a screen about one repository: `wording` with the repository's name, as
 * the address has it. A route exports what this returns as its `generateMetadata`.
 */
export function namedByRepository(wording = "{repository}") {
  return async ({ params }: { params: Promise<{ repository: string }> }): Promise<Metadata> => {
    const { repository } = await params;
    let name = repository;
    try {
      name = decodeURIComponent(repository);
    } catch {
      // Not an address of ours: the screen says so.
    }
    return { title: wording.replace("{repository}", () => name) };
  };
}
