import messages from "../../messages/en.json";

/** How a page is titled: the screen, then the product. A route gives the screen. */
export const TITLES = {
  default: messages.app.name,
  template: messages.app.title.replace("{screen}", "%s"),
};
